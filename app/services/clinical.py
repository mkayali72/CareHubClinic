"""Clinical documentation rules, calculations, locking, and structured notes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    AuditAction,
    DeliveryOutcome,
    DiagnosisCode,
    Patient,
    PhraseTemplate,
    PregnancyEpisode,
    PregnancyEpisodeStatus,
    ProcedureRecord,
    ProcedureType,
    ReminderDismissal,
    User,
    UserRole,
    Visit,
    VisitAmendment,
    VisitDiagnosis,
    VisitPhraseUse,
    VisitType,
)
from app.services.audit import record_audit_event

CLINICAL_ROLES = (
    UserRole.PHYSICIAN,
    UserRole.NURSE_MA,
    UserRole.CLINIC_ADMIN,
)
PHRASE_TEMPLATE_CREATOR_ROLES = (UserRole.PHYSICIAN,)
VISIT_LOCK_WINDOW_HOURS = 48
VISIT_LOCK_WINDOW = timedelta(hours=VISIT_LOCK_WINDOW_HOURS)
FREE_TEXT_FIELDS = ("hpi", "assessment", "plan")


def ensure_clinical_role(user: User) -> None:
    """Require a role permitted to view or document clinical information."""

    if user.role not in CLINICAL_ROLES:
        raise PermissionError("Clinical documentation requires a clinical role.")


def _ensure_same_clinic(user: User, clinic_id: int) -> None:
    """Reject cross-clinic clinical operations."""

    if user.clinic_id != clinic_id:
        raise PermissionError("The record does not belong to this clinic.")


def _patient_for_clinic(db: Session, clinic_id: int, patient_id: int) -> Patient:
    """Load an active patient from one clinic."""

    patient = db.scalar(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
        )
    )
    if patient is None:
        raise ValueError("Patient not found in this clinic.")
    return patient


def _episode_for_clinic(
    db: Session,
    clinic_id: int,
    episode_id: int,
    patient_id: int | None = None,
) -> PregnancyEpisode:
    """Load a pregnancy episode and optionally verify its patient."""

    conditions = [
        PregnancyEpisode.id == episode_id,
        PregnancyEpisode.clinic_id == clinic_id,
    ]
    if patient_id is not None:
        conditions.append(PregnancyEpisode.patient_id == patient_id)
    episode = db.scalar(select(PregnancyEpisode).where(*conditions))
    if episode is None:
        raise ValueError("Pregnancy episode not found in this clinic.")
    return episode


def calculate_edd(lmp: date) -> date:
    """Calculate an estimated due date using the standard 280-day rule."""

    return lmp + timedelta(days=280)


def effective_edd(episode: PregnancyEpisode) -> date:
    """Return corrected EDD when present, otherwise the original EDD."""

    return episode.corrected_edd or episode.edd


def gestational_age(
    episode: PregnancyEpisode,
    on_date: date | None = None,
) -> dict[str, Any]:
    """Calculate gestational age using the episode's effective dating."""

    target_date = on_date or date.today()
    # Once ultrasound dating is accepted, the corrected EDD becomes the
    # reference point for gestational age while preserving the original LMP.
    total_days = max(0, 280 - (effective_edd(episode) - target_date).days)
    weeks, days = divmod(total_days, 7)
    return {
        "weeks": weeks,
        "days": days,
        "total_days": total_days,
        "display": f"{weeks}w {days}d",
        "edd": effective_edd(episode).isoformat(),
    }


def prenatal_follow_up_recommendation(
    episode: PregnancyEpisode,
    on_date: date | None = None,
) -> dict[str, Any]:
    """Return the routine prenatal follow-up interval for the current dating.

    The cadence follows the clinic's lightweight prenatal workflow:
    every four weeks before 28 weeks, every two weeks from 28 through 35
    weeks, and weekly from 36 weeks onward.
    """

    age = gestational_age(episode, on_date)
    if age["weeks"] < 28:
        interval_weeks = 4
    elif age["weeks"] < 36:
        interval_weeks = 2
    else:
        interval_weeks = 1
    return {
        "interval_weeks": interval_weeks,
        "interval_label": (
            f"{interval_weeks} week" if interval_weeks == 1 else f"{interval_weeks} weeks"
        ),
        "suggested_date": (
            (on_date or date.today()) + timedelta(weeks=interval_weeks)
        ).isoformat(),
        "gestational_age": age,
    }


def _aware_utc(value: datetime) -> datetime:
    """Normalize a database timestamp to an aware UTC timestamp."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_visit_locked(
    visit: Visit,
    at: datetime | None = None,
) -> bool:
    """Return whether a visit is manually or time-window locked."""

    if visit.locked_at is not None:
        return True
    if visit.created_at is None:
        return False
    now = at or datetime.now(timezone.utc)
    return _aware_utc(visit.created_at) + VISIT_LOCK_WINDOW <= _aware_utc(now)


def _number(value: Any) -> float | None:
    """Convert an optional form value to a finite numeric value."""

    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid numeric clinical value: {value}") from error
    if parsed < 0:
        raise ValueError("Clinical numeric values cannot be negative.")
    return parsed


def normalize_visit_sections(
    visit_type: VisitType,
    vitals: Mapping[str, Any],
    prenatal_data: Mapping[str, Any] | None = None,
    gyn_data: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Normalize shared and template-specific visit fields."""

    normalized_vitals = {
        "blood_pressure": str(vitals.get("blood_pressure", "")).strip(),
        "weight_kg": _number(vitals.get("weight_kg")),
        "height_cm": _number(vitals.get("height_cm")),
    }
    normalized_prenatal: dict[str, Any] = {}
    normalized_gyn: dict[str, Any] = {}
    if visit_type is VisitType.PRENATAL:
        source = prenatal_data or {}
        normalized_prenatal = {
            "fundal_height_cm": _number(source.get("fundal_height_cm")),
            "fetal_heart_tones": str(source.get("fetal_heart_tones", "")).strip(),
            "fetal_position": str(source.get("fetal_position", "")).strip(),
            "presentation": str(source.get("presentation", "")).strip(),
            "ultrasound": {
                "efw_grams": _number(source.get("ultrasound_efw_grams")),
                "afi_cm": _number(source.get("ultrasound_afi_cm")),
                "placenta_location": str(
                    source.get("ultrasound_placenta_location", "")
                ).strip(),
                "presentation": str(
                    source.get("ultrasound_presentation", "")
                ).strip(),
                "biometry": str(source.get("ultrasound_biometry", "")).strip(),
            },
        }
    if visit_type is VisitType.GYN_ANNUAL:
        source = gyn_data or {}
        normalized_gyn = {
            "menstrual_history": str(source.get("menstrual_history", "")).strip(),
            "pap_due_date": (
                source.get("pap_due_date").isoformat()
                if isinstance(source.get("pap_due_date"), date)
                else str(source.get("pap_due_date", "")).strip()
            ),
            "hpv_due_date": (
                source.get("hpv_due_date").isoformat()
                if isinstance(source.get("hpv_due_date"), date)
                else str(source.get("hpv_due_date", "")).strip()
            ),
        }
    return normalized_vitals, normalized_prenatal, normalized_gyn


def _validate_diagnoses(
    db: Session,
    diagnosis_code_ids: Iterable[int],
) -> list[DiagnosisCode]:
    """Resolve active ICD-10 codes from the global lookup."""

    ids = list(dict.fromkeys(diagnosis_code_ids))
    if not ids:
        return []
    codes = list(
        db.scalars(
            select(DiagnosisCode).where(
                DiagnosisCode.id.in_(ids),
                DiagnosisCode.active.is_(True),
            )
        )
    )
    if len(codes) != len(ids):
        raise ValueError("One or more diagnosis codes are not available.")
    return sorted(codes, key=lambda code: ids.index(code.id))


def _replace_diagnoses(
    db: Session,
    visit: Visit,
    diagnosis_codes: list[DiagnosisCode],
) -> None:
    """Replace structured diagnosis links for a visit."""

    db.execute(delete(VisitDiagnosis).where(VisitDiagnosis.visit_id == visit.id))
    visit.diagnosis_links = [
        VisitDiagnosis(visit_id=visit.id, diagnosis_code_id=code.id)
        for code in diagnosis_codes
    ]


def create_pregnancy_episode(
    db: Session,
    actor: User,
    patient_id: int,
    lmp: date,
    edd: date | None = None,
    corrected_edd: date | None = None,
) -> PregnancyEpisode:
    """Create an active pregnancy episode with calculated dating."""

    ensure_clinical_role(actor)
    patient = _patient_for_clinic(db, actor.clinic_id, patient_id)
    if lmp > date.today():
        raise ValueError("LMP cannot be in the future.")
    original_edd = edd or calculate_edd(lmp)
    if original_edd < lmp:
        raise ValueError("EDD cannot be earlier than LMP.")
    if corrected_edd is not None and corrected_edd < lmp:
        raise ValueError("Corrected EDD cannot be earlier than LMP.")
    episode = PregnancyEpisode(
        clinic_id=actor.clinic_id,
        patient=patient,
        lmp=lmp,
        edd=original_edd,
        corrected_edd=corrected_edd,
        status=PregnancyEpisodeStatus.ACTIVE,
    )
    db.add(episode)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="pregnancy_episode",
        entity_id=episode.id,
        details={"patient_id": patient.id, "edd": original_edd.isoformat()},
    )
    return episode


def update_pregnancy_episode(
    db: Session,
    episode: PregnancyEpisode,
    actor: User,
    lmp: date,
    edd: date | None = None,
    corrected_edd: date | None = None,
    status: PregnancyEpisodeStatus = PregnancyEpisodeStatus.ACTIVE,
) -> PregnancyEpisode:
    """Update pregnancy dating or lifecycle status."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, episode.clinic_id)
    if lmp > date.today():
        raise ValueError("LMP cannot be in the future.")
    original_edd = edd or calculate_edd(lmp)
    if original_edd < lmp or (
        corrected_edd is not None and corrected_edd < lmp
    ):
        raise ValueError("Pregnancy dates are inconsistent.")
    changed: list[str] = []
    for field, value in (
        ("lmp", lmp),
        ("edd", original_edd),
        ("corrected_edd", corrected_edd),
        ("status", status),
    ):
        if getattr(episode, field) != value:
            setattr(episode, field, value)
            changed.append(field)
    if changed:
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="pregnancy_episode",
            entity_id=episode.id,
            details={"fields": changed},
        )
    return episode


def create_visit(
    db: Session,
    actor: User,
    patient_id: int,
    visit_type: VisitType,
    pregnancy_episode_id: int | None,
    vitals: Mapping[str, Any],
    prenatal_data: Mapping[str, Any] | None,
    gyn_data: Mapping[str, Any] | None,
    hpi: str,
    assessment: str,
    plan: str,
    diagnosis_code_ids: Iterable[int],
    visit_date: date | None = None,
) -> Visit:
    """Create a structured, clinic-scoped visit note."""

    ensure_clinical_role(actor)
    patient = _patient_for_clinic(db, actor.clinic_id, patient_id)
    episode = None
    if visit_type is VisitType.PRENATAL:
        if pregnancy_episode_id is None:
            raise ValueError("Prenatal visits require a pregnancy episode.")
        episode = _episode_for_clinic(
            db,
            actor.clinic_id,
            pregnancy_episode_id,
            patient_id=patient.id,
        )
    elif pregnancy_episode_id is not None:
        raise ValueError("Only prenatal visits may be linked to a pregnancy episode.")
    diagnosis_codes = _validate_diagnoses(db, diagnosis_code_ids)
    normalized = normalize_visit_sections(
        visit_type,
        vitals,
        prenatal_data,
        gyn_data,
    )
    visit = Visit(
        clinic_id=actor.clinic_id,
        patient=patient,
        pregnancy_episode=episode,
        visit_type=visit_type,
        visit_date=visit_date or date.today(),
        vitals=normalized[0],
        prenatal_data=normalized[1],
        gyn_data=normalized[2],
        hpi=hpi.strip(),
        assessment=assessment.strip(),
        plan=plan.strip(),
    )
    db.add(visit)
    db.flush()
    _replace_diagnoses(db, visit, diagnosis_codes)
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="visit",
        entity_id=visit.id,
        details={
            "patient_id": patient.id,
            "visit_type": visit_type.value,
            "diagnosis_codes": [code.code for code in diagnosis_codes],
        },
    )
    return visit


def get_visit_for_user(
    db: Session,
    visit_id: int,
    user: User,
) -> Visit | None:
    """Load an active visit and its clinical relationships for one clinic."""

    ensure_clinical_role(user)
    return db.scalar(
        select(Visit)
        .options(
            joinedload(Visit.patient),
            joinedload(Visit.pregnancy_episode),
            selectinload(Visit.diagnosis_links).joinedload(
                VisitDiagnosis.diagnosis_code
            ),
            selectinload(Visit.amendments).joinedload(
                VisitAmendment.amended_by_user
            ),
            selectinload(Visit.procedures),
            selectinload(Visit.phrase_uses),
        )
        .where(
            Visit.id == visit_id,
            Visit.clinic_id == user.clinic_id,
        )
    )


def get_patient_visits(
    db: Session,
    user: User,
    patient_id: int,
) -> list[Visit]:
    """Return a patient's active visits ordered newest first."""

    _patient_for_clinic(db, user.clinic_id, patient_id)
    return list(
        db.scalars(
            select(Visit)
            .options(
                joinedload(Visit.pregnancy_episode),
                selectinload(Visit.diagnosis_links).joinedload(
                    VisitDiagnosis.diagnosis_code
                ),
            )
            .where(
                Visit.clinic_id == user.clinic_id,
                Visit.patient_id == patient_id,
            )
            .order_by(Visit.visit_date.desc(), Visit.id.desc())
        )
    )


def get_patient_episodes(
    db: Session,
    user: User,
    patient_id: int,
) -> list[PregnancyEpisode]:
    """Return active and historical pregnancy episodes for a patient."""

    _patient_for_clinic(db, user.clinic_id, patient_id)
    return list(
        db.scalars(
            select(PregnancyEpisode)
            .where(
                PregnancyEpisode.clinic_id == user.clinic_id,
                PregnancyEpisode.patient_id == patient_id,
            )
            .order_by(PregnancyEpisode.created_at.desc(), PregnancyEpisode.id.desc())
        )
    )


def update_visit(
    db: Session,
    visit: Visit,
    actor: User,
    visit_type: VisitType,
    pregnancy_episode_id: int | None,
    vitals: Mapping[str, Any],
    prenatal_data: Mapping[str, Any] | None,
    gyn_data: Mapping[str, Any] | None,
    hpi: str,
    assessment: str,
    plan: str,
    diagnosis_code_ids: Iterable[int],
    visit_date: date | None = None,
) -> Visit:
    """Update an unlocked visit note and its structured diagnosis links."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, visit.clinic_id)
    if is_visit_locked(visit):
        raise PermissionError("Locked visits can only receive amendments.")
    if visit_type is VisitType.PRENATAL and pregnancy_episode_id is None:
        raise ValueError("Prenatal visits require a pregnancy episode.")
    if visit_type is not VisitType.PRENATAL and pregnancy_episode_id is not None:
        raise ValueError("Only prenatal visits may be linked to a pregnancy episode.")
    episode = (
        _episode_for_clinic(
            db,
            visit.clinic_id,
            pregnancy_episode_id,
            patient_id=visit.patient_id,
        )
        if pregnancy_episode_id is not None
        else None
    )
    diagnosis_codes = _validate_diagnoses(db, diagnosis_code_ids)
    sections = normalize_visit_sections(
        visit_type,
        vitals,
        prenatal_data,
        gyn_data,
    )
    changes: list[str] = []
    for field, value in (
        ("visit_type", visit_type),
        ("visit_date", visit_date or date.today()),
        ("pregnancy_episode", episode),
        ("vitals", sections[0]),
        ("prenatal_data", sections[1]),
        ("gyn_data", sections[2]),
        ("hpi", hpi.strip()),
        ("assessment", assessment.strip()),
        ("plan", plan.strip()),
    ):
        current = (
            visit.pregnancy_episode
            if field == "pregnancy_episode"
            else getattr(visit, field)
        )
        if field == "pregnancy_episode":
            comparable = current.id if current is not None else None
            replacement = episode.id if episode is not None else None
        else:
            comparable = current
            replacement = value
        if comparable != replacement:
            setattr(visit, field, value)
            changes.append(field)
    _replace_diagnoses(db, visit, diagnosis_codes)
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="visit",
        entity_id=visit.id,
        details={
            "fields": changes or ["diagnosis_links"],
            "diagnosis_codes": [code.code for code in diagnosis_codes],
        },
    )
    return visit


def lock_visit(db: Session, visit: Visit, actor: User) -> Visit:
    """Manually lock a visit note before the automatic window expires."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, visit.clinic_id)
    if not is_visit_locked(visit):
        visit.locked_at = datetime.now(timezone.utc)
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="visit",
            entity_id=visit.id,
            details={"field": "locked_at"},
        )
    return visit


def create_amendment(
    db: Session,
    visit: Visit,
    actor: User,
    content: str,
) -> VisitAmendment:
    """Append an amendment to a locked visit without changing its note fields."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, visit.clinic_id)
    if not is_visit_locked(visit):
        raise ValueError("Amendments are only available after a visit is locked.")
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("Amendment content is required.")
    amendment = VisitAmendment(
        visit=visit,
        amended_by_user_id=actor.id,
        content=normalized_content,
    )
    db.add(amendment)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="visit_amendment",
        entity_id=amendment.id,
        details={"visit_id": visit.id},
    )
    return amendment


def get_diagnosis_codes(db: Session, clinic_id: int) -> list[DiagnosisCode]:
    """Return active global and clinic-specific ICD-10 choices."""

    return list(
        db.scalars(
            select(DiagnosisCode)
            .where(
                DiagnosisCode.active.is_(True),
                or_(
                    DiagnosisCode.clinic_id.is_(None),
                    DiagnosisCode.clinic_id == clinic_id,
                ),
            )
            .order_by(DiagnosisCode.code.asc())
        )
    )


def get_phrase_templates(db: Session, clinic_id: int) -> list[PhraseTemplate]:
    """Return reusable phrase templates for a clinic."""

    return list(
        db.scalars(
            select(PhraseTemplate)
            .where(PhraseTemplate.clinic_id == clinic_id)
            .order_by(PhraseTemplate.name.asc())
        )
    )


def create_phrase_template(
    db: Session,
    actor: User,
    name: str,
    body: str,
) -> PhraseTemplate:
    """Create a physician-owned clinic phrase template."""

    if actor.role not in PHRASE_TEMPLATE_CREATOR_ROLES:
        raise PermissionError("Only physicians can create phrase templates.")
    normalized_name = name.strip()
    normalized_body = body.strip()
    if not normalized_name or not normalized_body:
        raise ValueError("Phrase template name and text are required.")
    duplicate = db.scalar(
        select(PhraseTemplate).where(
            PhraseTemplate.clinic_id == actor.clinic_id,
            PhraseTemplate.name == normalized_name,
        )
    )
    if duplicate is not None:
        raise ValueError("A phrase template with this name already exists.")
    template = PhraseTemplate(
        clinic_id=actor.clinic_id,
        created_by_user_id=actor.id,
        name=normalized_name,
        body=normalized_body,
    )
    db.add(template)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="phrase_template",
        entity_id=template.id,
    )
    return template


def update_phrase_template(
    db: Session,
    template: PhraseTemplate,
    actor: User,
    name: str,
    body: str,
) -> PhraseTemplate:
    """Edit a phrase template without changing prior phrase snapshots."""

    if actor.role not in CLINICAL_ROLES:
        raise PermissionError("Clinical documentation requires a clinical role.")
    _ensure_same_clinic(actor, template.clinic_id)
    if actor.role is not UserRole.CLINIC_ADMIN and template.created_by_user_id != actor.id:
        raise PermissionError("Only the template creator or clinic admin can edit it.")
    normalized_name = name.strip()
    normalized_body = body.strip()
    if not normalized_name or not normalized_body:
        raise ValueError("Phrase template name and text are required.")
    duplicate = db.scalar(
        select(PhraseTemplate).where(
            PhraseTemplate.clinic_id == template.clinic_id,
            PhraseTemplate.name == normalized_name,
            PhraseTemplate.id != template.id,
        )
    )
    if duplicate is not None:
        raise ValueError("A phrase template with this name already exists.")
    changed = []
    if template.name != normalized_name:
        template.name = normalized_name
        changed.append("name")
    if template.body != normalized_body:
        template.body = normalized_body
        changed.append("body")
    if changed:
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="phrase_template",
            entity_id=template.id,
            details={"fields": changed},
        )
    return template


def insert_phrase_into_visit(
    db: Session,
    visit: Visit,
    template: PhraseTemplate,
    actor: User,
    field_name: str,
) -> VisitPhraseUse:
    """Insert a copied phrase into a note field and retain its snapshot."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, visit.clinic_id)
    _ensure_same_clinic(actor, template.clinic_id)
    if field_name not in FREE_TEXT_FIELDS:
        raise ValueError("Phrases may only be inserted into HPI, assessment, or plan.")
    if is_visit_locked(visit):
        raise PermissionError("Locked visits can only receive amendments.")
    existing = getattr(visit, field_name)
    copied_text = template.body
    setattr(
        visit,
        field_name,
        f"{existing}\n\n{copied_text}".strip() if existing.strip() else copied_text,
    )
    use = VisitPhraseUse(
        visit=visit,
        phrase_template=template,
        inserted_by_user_id=actor.id,
        field_name=field_name,
        text_snapshot=copied_text,
    )
    db.add(use)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="visit",
        entity_id=visit.id,
        details={"phrase_template_id": template.id, "field": field_name},
    )
    return use


def create_procedure_record(
    db: Session,
    visit: Visit,
    actor: User,
    procedure_type: ProcedureType,
    details: Mapping[str, Any],
) -> ProcedureRecord:
    """Add structured procedure documentation to an unlocked visit."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, visit.clinic_id)
    if is_visit_locked(visit):
        raise PermissionError("Locked visits can only receive amendments.")
    record = ProcedureRecord(
        visit=visit,
        procedure_type=procedure_type,
        details=dict(details),
        performed_by_user_id=actor.id,
        performed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="procedure_record",
        entity_id=record.id,
        details={"visit_id": visit.id, "procedure_type": procedure_type.value},
    )
    return record


def create_delivery_outcome(
    db: Session,
    episode: PregnancyEpisode,
    actor: User,
    delivery_date: date,
    mode: str,
    complications: str,
    birth_weight_grams: int | None,
    apgar_one_minute: int | None,
    apgar_five_minutes: int | None,
) -> DeliveryOutcome:
    """Record delivery details and move the episode to delivered."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, episode.clinic_id)
    if episode.delivery_outcome is not None:
        raise ValueError("This pregnancy episode already has a delivery outcome.")
    if delivery_date < episode.lmp:
        raise ValueError("Delivery date cannot be earlier than LMP.")
    outcome = DeliveryOutcome(
        pregnancy_episode=episode,
        delivery_date=delivery_date,
        mode=mode.strip(),
        complications=complications.strip(),
        birth_weight_grams=birth_weight_grams,
        apgar_one_minute=apgar_one_minute,
        apgar_five_minutes=apgar_five_minutes,
    )
    episode.status = PregnancyEpisodeStatus.DELIVERED
    db.add(outcome)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="delivery_outcome",
        entity_id=outcome.id,
        details={"pregnancy_episode_id": episode.id},
    )
    return outcome


def pregnancy_trend(
    db: Session,
    episode: PregnancyEpisode,
) -> list[dict[str, Any]]:
    """Build lightweight weight, BP, and fundal-height chart points."""

    visits = list(
        db.scalars(
            select(Visit)
            .where(
                Visit.pregnancy_episode_id == episode.id,
                Visit.visit_type == VisitType.PRENATAL,
            )
            .order_by(Visit.visit_date.asc(), Visit.id.asc())
        )
    )
    return [
        {
            "date": visit.visit_date.isoformat(),
            "weight_kg": visit.vitals.get("weight_kg"),
            "blood_pressure": visit.vitals.get("blood_pressure", ""),
            "fundal_height_cm": visit.prenatal_data.get("fundal_height_cm"),
        }
        for visit in visits
    ]


def screening_reminders(
    db: Session,
    episode: PregnancyEpisode,
    on_date: date | None = None,
    visit_type: VisitType | None = None,
) -> list[dict[str, Any]]:
    """Calculate trimester screening prompts without marking tests complete."""

    if visit_type is not None and visit_type is not VisitType.PRENATAL:
        return []
    age = gestational_age(episode, on_date)
    dismissed = {
        dismissal.reminder_key
        for dismissal in db.scalars(
            select(ReminderDismissal).where(
                ReminderDismissal.pregnancy_episode_id == episode.id
            )
        )
    }
    candidates = (
        ("glucose_tolerance", "Glucose tolerance test", 24, 28),
        ("rhogam", "Rhogam review", 28, 30),
        ("group_b_strep", "Group B Strep culture", 36, 37),
    )
    reminders: list[dict[str, Any]] = []
    for key, label, start_week, end_week in candidates:
        if age["weeks"] >= start_week:
            reminders.append(
                {
                    "key": key,
                    "label": label,
                    "status": "due" if age["weeks"] <= end_week else "overdue",
                    "dismissed": key in dismissed,
                    "gestational_age": age["display"],
                }
            )
    return [reminder for reminder in reminders if not reminder["dismissed"]]


def dismiss_screening_reminder(
    db: Session,
    episode: PregnancyEpisode,
    actor: User,
    reminder_key: str,
) -> ReminderDismissal:
    """Hide a reminder without changing any screening completion state."""

    ensure_clinical_role(actor)
    _ensure_same_clinic(actor, episode.clinic_id)
    allowed = {"glucose_tolerance", "rhogam", "group_b_strep"}
    if reminder_key not in allowed:
        raise ValueError("Unknown screening reminder.")
    existing = db.scalar(
        select(ReminderDismissal).where(
            ReminderDismissal.pregnancy_episode_id == episode.id,
            ReminderDismissal.reminder_key == reminder_key,
        )
    )
    if existing is not None:
        return existing
    dismissal = ReminderDismissal(
        pregnancy_episode=episode,
        reminder_key=reminder_key,
        dismissed_by_user_id=actor.id,
    )
    db.add(dismissal)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="screening_reminder",
        entity_id=dismissal.id,
        details={"pregnancy_episode_id": episode.id, "reminder_key": reminder_key},
    )
    return dismissal