"""Formulary, prescription ordering, and patient-safety warning rules.

Prescription safety checks are deliberately advisory rather than silently
blocking. A warning is raised when a patient has an active PregnancyEpisode
and the selected medication is marked ``false`` (unsafe) or ``unknown`` in the
clinic formulary. A separate allergy warning is raised when a recorded allergy
matches the medication name or its configured allergy_category, including the
small set of common category aliases handled below.

The service never trusts the browser's warning state. It recalculates warnings
from current database rows on every create request. If a warning exists, the
request must include the corresponding explicit acknowledgment checkbox before
the Prescription row is created. This keeps the workflow usable for a
physician who has made a clinically informed decision while making the
override visible in the saved audit fields. A hard block is intentionally not
used because formulary classifications are broad screening signals, not
patient-specific prescribing guidance; exceptions can be clinically necessary.
The warning and acknowledgment do not replace physician judgment or a drug
interaction reference.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    AuditAction,
    MedicationDefinition,
    Patient,
    PregnancyEpisode,
    PregnancyEpisodeStatus,
    Prescription,
    PregnancySafetyFlag,
    User,
    UserRole,
    Visit,
)
from app.services.audit import record_audit_event, soft_delete_record
from app.services.clinical import CLINICAL_ROLES, ensure_clinical_role


DEFAULT_MEDICATIONS: tuple[dict[str, str], ...] = (
    {
        "name": "Prenatal vitamin",
        "description": "Daily prenatal multivitamin",
        "pregnancy_safety_flag": "true",
        "allergy_category": "vitamin",
    },
    {
        "name": "Folic acid",
        "description": "Folate supplementation",
        "pregnancy_safety_flag": "true",
        "allergy_category": "vitamin",
    },
    {
        "name": "Ferrous sulfate",
        "description": "Oral iron supplementation",
        "pregnancy_safety_flag": "true",
        "allergy_category": "iron",
    },
    {
        "name": "Acetaminophen",
        "description": "Non-opioid analgesic and antipyretic",
        "pregnancy_safety_flag": "true",
        "allergy_category": "analgesic",
    },
    {
        "name": "Ibuprofen",
        "description": "NSAID analgesic; review pregnancy timing carefully",
        "pregnancy_safety_flag": "false",
        "allergy_category": "nsaid",
    },
    {
        "name": "Low-dose aspirin",
        "description": "Low-dose aspirin when clinically indicated",
        "pregnancy_safety_flag": "unknown",
        "allergy_category": "nsaid",
    },
    {
        "name": "Amoxicillin",
        "description": "Penicillin-class antibiotic",
        "pregnancy_safety_flag": "true",
        "allergy_category": "penicillin",
    },
    {
        "name": "Cephalexin",
        "description": "Cephalosporin antibiotic",
        "pregnancy_safety_flag": "true",
        "allergy_category": "cephalosporin",
    },
    {
        "name": "Nitrofurantoin",
        "description": "Urinary antibiotic; review gestational timing",
        "pregnancy_safety_flag": "unknown",
        "allergy_category": "antibiotic",
    },
    {
        "name": "Metronidazole",
        "description": "Antimicrobial",
        "pregnancy_safety_flag": "true",
        "allergy_category": "antibiotic",
    },
    {
        "name": "Fluconazole",
        "description": "Azole antifungal",
        "pregnancy_safety_flag": "false",
        "allergy_category": "antifungal",
    },
    {
        "name": "Ondansetron",
        "description": "Antiemetic",
        "pregnancy_safety_flag": "unknown",
        "allergy_category": "antiemetic",
    },
    {
        "name": "Labetalol",
        "description": "Antihypertensive",
        "pregnancy_safety_flag": "true",
        "allergy_category": "antihypertensive",
    },
    {
        "name": "Nifedipine",
        "description": "Calcium-channel blocker",
        "pregnancy_safety_flag": "true",
        "allergy_category": "antihypertensive",
    },
    {
        "name": "Levothyroxine",
        "description": "Thyroid hormone replacement",
        "pregnancy_safety_flag": "true",
        "allergy_category": "thyroid",
    },
)

_CATEGORY_ALIASES: dict[str, frozenset[str]] = {
    "penicillin": frozenset({"penicillin", "amoxicillin", "ampicillin", "beta lactam"}),
    "cephalosporin": frozenset({"cephalosporin", "cephalexin", "beta lactam"}),
    "nsaid": frozenset({"nsaid", "nsaids", "ibuprofen", "naproxen", "aspirin"}),
    "sulfa": frozenset({"sulfa", "sulfonamide", "sulfamethoxazole"}),
}


class PrescriptionWarningRequired(ValueError):
    """Signal that a physician must explicitly acknowledge safety warnings."""

    def __init__(self, warnings: dict[str, str]) -> None:
        self.warnings = warnings
        super().__init__("Prescription warnings require explicit acknowledgment.")


def _normalize(value: str | None) -> str:
    """Normalize a medication/allergy label for conservative comparison."""

    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _same_category(left: str, right: str) -> bool:
    """Return whether two labels describe the same known allergy category."""

    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    for aliases in _CATEGORY_ALIASES.values():
        if left_normalized in aliases and right_normalized in aliases:
            return True
    return False


def _allergy_conflicts(
    patient: Patient,
    definition: MedicationDefinition,
) -> list[str]:
    """Return recorded allergy labels that conflict with a formulary entry."""

    candidates = (
        _normalize(definition.name),
        _normalize(definition.allergy_category),
    )
    conflicts: list[str] = []
    for allergy in patient.allergies or []:
        allergy_name = str(allergy.get("name", "")).strip()
        normalized_allergy = _normalize(allergy_name)
        if not normalized_allergy:
            continue
        direct_match = any(
            candidate
            and (
                candidate == normalized_allergy
                or candidate in normalized_allergy
                or normalized_allergy in candidate
            )
            for candidate in candidates
        )
        category_match = _same_category(
            definition.allergy_category,
            normalized_allergy,
        )
        if direct_match or category_match:
            conflicts.append(allergy_name)
    return list(dict.fromkeys(conflicts))


def get_prescription_warnings(
    db: Session,
    patient: Patient,
    definition: MedicationDefinition,
) -> dict[str, str]:
    """Calculate current pregnancy and allergy warnings for one medication.

    Pregnancy warning trigger:
        The same-clinic patient has at least one non-deleted
        ``PregnancyEpisode`` with status ``active`` and the definition is
        marked ``false`` or ``unknown``. ``false`` produces an unsafe warning;
        ``unknown`` produces an uncertainty warning because unknown must not be
        silently treated as safe.

    Allergy warning trigger:
        At least one structured patient allergy name matches the definition's
        name or allergy category, after case/punctuation normalization and
        known category aliases. Free-text reaction and severity fields are
        included in the warning context but are not used as independent
        matches.

    Returns:
        A mapping with optional ``pregnancy`` and ``allergy`` messages. An
        empty mapping means no warning was found; it is not a guarantee of
        safety or absence of drug interactions.
    """

    warnings: dict[str, str] = {}
    active_pregnancy = db.scalar(
        select(PregnancyEpisode.id).where(
            PregnancyEpisode.clinic_id == patient.clinic_id,
            PregnancyEpisode.patient_id == patient.id,
            PregnancyEpisode.status == PregnancyEpisodeStatus.ACTIVE,
        )
    )
    safety = definition.pregnancy_safety_flag
    safety_value = getattr(safety, "value", safety)
    if active_pregnancy is not None and safety_value in {"false", "unknown"}:
        if safety_value == "false":
            warnings["pregnancy"] = (
                f"{definition.name} is marked unsafe during an active pregnancy."
            )
        else:
            warnings["pregnancy"] = (
                f"The pregnancy safety of {definition.name} is unknown in the clinic formulary."
            )

    conflicts = _allergy_conflicts(patient, definition)
    if conflicts:
        labels = ", ".join(conflicts)
        warnings["allergy"] = (
            f"Possible allergy conflict: this medication matches recorded allergy "
            f"{labels}."
        )
    return warnings


def check_prescription_warnings(
    db: Session,
    patient: Patient,
    definition: MedicationDefinition,
) -> dict[str, str]:
    """Backward-compatible descriptive alias for the safety-check function."""

    return get_prescription_warnings(db, patient, definition)


def ensure_default_medication_definitions(
    db: Session,
    clinic_id: int,
) -> list[MedicationDefinition]:
    """Seed the OB/GYN starter formulary once for a clinic."""

    existing = list(
        db.scalars(
            select(MedicationDefinition).where(
                MedicationDefinition.clinic_id == clinic_id,
            )
        )
    )
    if existing:
        return existing
    definitions = [
        MedicationDefinition(clinic_id=clinic_id, **item)
        for item in DEFAULT_MEDICATIONS
    ]
    db.add_all(definitions)
    db.flush()
    return definitions


def get_medication_definitions(
    db: Session,
    clinic_id: int,
    *,
    active_only: bool = False,
) -> list[MedicationDefinition]:
    """Return a clinic formulary, lazily seeding new clinics."""

    ensure_default_medication_definitions(db, clinic_id)
    conditions: list[Any] = [MedicationDefinition.clinic_id == clinic_id]
    if active_only:
        conditions.append(MedicationDefinition.active.is_(True))
    return list(
        db.scalars(
            select(MedicationDefinition)
            .where(*conditions)
            .order_by(MedicationDefinition.name.asc())
        )
    )


def _definition_for_clinic(
    db: Session,
    clinic_id: int,
    definition_id: int,
    *,
    active_only: bool = True,
) -> MedicationDefinition:
    conditions: list[Any] = [
        MedicationDefinition.id == definition_id,
        MedicationDefinition.clinic_id == clinic_id,
    ]
    if active_only:
        conditions.append(MedicationDefinition.active.is_(True))
    definition = db.scalar(select(MedicationDefinition).where(*conditions))
    if definition is None:
        raise ValueError("Medication is unavailable in this clinic formulary.")
    return definition


def create_medication_definition(
    db: Session,
    actor: User,
    name: str,
    description: str,
    pregnancy_safety_flag: str | PregnancySafetyFlag,
    allergy_category: str,
) -> MedicationDefinition:
    """Create one active clinic formulary entry as a clinic administrator."""

    if actor.role is not UserRole.CLINIC_ADMIN:
        raise PermissionError("Only clinic_admin can manage the medication formulary.")
    normalized_name = name.strip()
    normalized_category = allergy_category.strip().casefold()
    if not normalized_name:
        raise ValueError("Medication name is required.")
    try:
        safety = PregnancySafetyFlag(pregnancy_safety_flag)
    except ValueError as error:
        raise ValueError("Pregnancy safety must be true, false, or unknown.") from error
    duplicate = db.scalar(
        select(MedicationDefinition).where(
            MedicationDefinition.clinic_id == actor.clinic_id,
            MedicationDefinition.name == normalized_name,
        )
    )
    if duplicate is not None:
        raise ValueError("A medication with this name already exists.")
    definition = MedicationDefinition(
        clinic_id=actor.clinic_id,
        name=normalized_name,
        description=description.strip(),
        pregnancy_safety_flag=safety,
        allergy_category=normalized_category,
    )
    db.add(definition)
    db.flush()
    record_audit_event(
        db,
        actor.id,
        AuditAction.CREATE,
        "medication_definition",
        definition.id,
    )
    return definition


def update_medication_definition(
    db: Session,
    definition: MedicationDefinition,
    actor: User,
    name: str,
    description: str,
    pregnancy_safety_flag: str | PregnancySafetyFlag,
    allergy_category: str,
    active: bool,
) -> MedicationDefinition:
    """Edit a formulary entry without changing previously issued prescriptions."""

    if actor.role is not UserRole.CLINIC_ADMIN:
        raise PermissionError("Only clinic_admin can manage the medication formulary.")
    if definition.clinic_id != actor.clinic_id:
        raise PermissionError("The medication does not belong to this clinic.")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Medication name is required.")
    try:
        safety = PregnancySafetyFlag(pregnancy_safety_flag)
    except ValueError as error:
        raise ValueError("Pregnancy safety must be true, false, or unknown.") from error
    duplicate = db.scalar(
        select(MedicationDefinition).where(
            MedicationDefinition.clinic_id == definition.clinic_id,
            MedicationDefinition.name == normalized_name,
            MedicationDefinition.id != definition.id,
        )
    )
    if duplicate is not None:
        raise ValueError("A medication with this name already exists.")
    changes: list[str] = []
    values = {
        "name": normalized_name,
        "description": description.strip(),
        "pregnancy_safety_flag": safety,
        "allergy_category": allergy_category.strip().casefold(),
        "active": active,
    }
    for field, value in values.items():
        if getattr(definition, field) != value:
            setattr(definition, field, value)
            changes.append(field)
    if changes:
        record_audit_event(
            db,
            actor.id,
            AuditAction.UPDATE,
            "medication_definition",
            definition.id,
            details={"fields": changes},
        )
    return definition


def _visit_and_patient(
    db: Session,
    actor: User,
    visit_id: int,
) -> tuple[Visit, Patient]:
    """Load a visit and its patient within the actor's clinic."""

    visit = db.scalar(
        select(Visit)
        .options(joinedload(Visit.patient))
        .where(
            Visit.id == visit_id,
            Visit.clinic_id == actor.clinic_id,
        )
    )
    if visit is None:
        raise ValueError("Visit not found in this clinic.")
    return visit, visit.patient


def create_prescription(
    db: Session,
    actor: User,
    visit_id: int,
    medication_definition_id: int,
    dosage: str,
    frequency: str,
    duration: str,
    *,
    acknowledge_pregnancy_warning: bool = False,
    acknowledge_allergy_warning: bool = False,
) -> Prescription:
    """Create a physician prescription after recalculating warnings.

    The two acknowledgment flags are meaningful only when their corresponding
    warning exists. A missing acknowledgment raises
    ``PrescriptionWarningRequired`` and leaves the transaction to the caller;
    it never creates a partially confirmed prescription.
    """

    if actor.role is not UserRole.PHYSICIAN:
        raise PermissionError("Only physicians can confirm prescriptions.")
    visit, patient = _visit_and_patient(db, actor, visit_id)
    definition = _definition_for_clinic(
        db,
        actor.clinic_id,
        medication_definition_id,
        active_only=True,
    )
    values = {
        "dosage": dosage.strip(),
        "frequency": frequency.strip(),
        "duration": duration.strip(),
    }
    if any(not value for value in values.values()):
        raise ValueError("Dosage, frequency, and duration are required.")
    warnings = get_prescription_warnings(db, patient, definition)
    missing = {
        key: message
        for key, message in warnings.items()
        if not (
            acknowledge_pregnancy_warning
            if key == "pregnancy"
            else acknowledge_allergy_warning
        )
    }
    if missing:
        raise PrescriptionWarningRequired(missing)
    prescription = Prescription(
        clinic_id=actor.clinic_id,
        visit_id=visit.id,
        patient_id=patient.id,
        medication_definition_id=definition.id,
        prescribed_by_user_id=actor.id,
        **values,
        pregnancy_warning_acknowledged=(
            "pregnancy" in warnings and acknowledge_pregnancy_warning
        ),
        allergy_warning_acknowledged=(
            "allergy" in warnings and acknowledge_allergy_warning
        ),
    )
    db.add(prescription)
    db.flush()
    record_audit_event(
        db,
        actor.id,
        AuditAction.CREATE,
        "prescription",
        prescription.id,
        details={
            "visit_id": visit.id,
            "patient_id": patient.id,
            "medication_definition_id": definition.id,
            "warnings_acknowledged": list(warnings),
        },
    )
    return prescription


def get_visit_prescriptions(
    db: Session,
    actor: User,
    visit_id: int,
) -> list[Prescription]:
    """Return active prescriptions for a clinic-scoped visit."""

    ensure_clinical_role(actor)
    return list(
        db.scalars(
            select(Prescription)
            .options(
                joinedload(Prescription.medication_definition),
                joinedload(Prescription.prescribed_by_user),
            )
            .where(
                Prescription.visit_id == visit_id,
                Prescription.clinic_id == actor.clinic_id,
            )
            .order_by(Prescription.prescribed_at.desc(), Prescription.id.desc())
        )
    )


def get_current_prescriptions(
    db: Session,
    actor: User,
    patient_id: int,
) -> list[Prescription]:
    """Return active prescriptions for a patient, newest first."""

    ensure_clinical_role(actor)
    return list(
        db.scalars(
            select(Prescription)
            .options(
                joinedload(Prescription.medication_definition),
                joinedload(Prescription.visit),
                joinedload(Prescription.prescribed_by_user),
            )
            .where(
                Prescription.patient_id == patient_id,
                Prescription.clinic_id == actor.clinic_id,
            )
            .order_by(Prescription.prescribed_at.desc(), Prescription.id.desc())
        )
    )


def get_prescription_for_user(
    db: Session,
    actor: User,
    prescription_id: int,
) -> Prescription:
    """Load one active prescription with clinic and patient context."""

    ensure_clinical_role(actor)
    prescription = db.scalar(
        select(Prescription)
        .options(
            joinedload(Prescription.medication_definition),
            joinedload(Prescription.patient).joinedload(Patient.clinic),
            joinedload(Prescription.visit),
            joinedload(Prescription.prescribed_by_user),
        )
        .where(
            Prescription.id == prescription_id,
            Prescription.clinic_id == actor.clinic_id,
        )
    )
    if prescription is None:
        raise ValueError("Prescription not found in this clinic.")
    return prescription


def soft_delete_prescription(
    db: Session,
    prescription: Prescription,
    actor: User,
) -> None:
    """Soft-delete a prescription through the clinic-admin audit boundary."""

    if prescription.clinic_id != actor.clinic_id:
        raise PermissionError("The prescription does not belong to this clinic.")
    soft_delete_record(
        db,
        prescription,
        actor,
        "prescription",
        prescription.id,
    )