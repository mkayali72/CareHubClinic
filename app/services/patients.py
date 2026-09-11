"""Patient demographic business rules, payload normalization, and projections."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import AuditAction, Patient, User, UserRole
from app.services.audit import record_audit_event

PATIENT_ROLES = (
    UserRole.PHYSICIAN,
    UserRole.NURSE_MA,
    UserRole.FRONT_DESK,
    UserRole.BILLING_CLERK,
    UserRole.CLINIC_ADMIN,
)


def can_view_clinical_patient_fields(user: User) -> bool:
    """Return whether a staff user may view sensitive patient fields.

    Args:
        user: Authenticated staff user.

    Returns:
        True for physician, nurse_ma, and clinic_admin users.
    """

    return user.role in {
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.CLINIC_ADMIN,
    }


def normalize_structured_items(
    primary_field: str,
    primary_values: Sequence[str],
    additional_fields: Mapping[str, Sequence[str]],
) -> list[dict[str, str]]:
    """Normalize repeated form rows into structured JSON objects.

    Args:
        primary_field: Required field that identifies a non-empty row.
        primary_values: Values for the primary field, such as medication names.
        additional_fields: Parallel optional field values for each row.

    Returns:
        A list of trimmed structured objects with empty values omitted.

    Raises:
        ValueError: If a row contains secondary data without its primary value.
    """

    row_count = max(
        [len(primary_values), *[len(values) for values in additional_fields.values()]],
        default=0,
    )
    items: list[dict[str, str]] = []
    for index in range(row_count):
        values: dict[str, str] = {}
        primary_value = (
            primary_values[index].strip() if index < len(primary_values) else ""
        )
        for field_name, field_values in additional_fields.items():
            value = field_values[index].strip() if index < len(field_values) else ""
            if value:
                values[field_name] = value
        if not primary_value:
            if values:
                raise ValueError(f"{primary_field} is required for every structured row.")
            continue
        values = {primary_field: primary_value, **values}
        items.append(values)
    return items


def compact_fields(values: Mapping[str, str]) -> dict[str, str]:
    """Return a structured object containing only non-empty trimmed values.

    Args:
        values: User-entered key/value fields.

    Returns:
        A dictionary with blank values removed.
    """

    return {
        key: value.strip()
        for key, value in values.items()
        if value and value.strip()
    }


def build_patient_payload(
    name: str,
    date_of_birth: date,
    contact_phone: str,
    contact_email: str,
    contact_address: str,
    insurance_provider: str,
    insurance_member_id: str,
    insurance_group_number: str,
    emergency_name: str,
    emergency_relationship: str,
    emergency_phone: str,
    allergy_name: Sequence[str],
    allergy_reaction: Sequence[str],
    allergy_severity: Sequence[str],
    medication_name: Sequence[str],
    medication_dose: Sequence[str],
    medication_frequency: Sequence[str],
    contraception_method: str,
    include_clinical_fields: bool,
) -> dict[str, Any]:
    """Build a validated Patient payload from the structured form fields.

    Args:
        name: Patient display name.
        date_of_birth: Patient date of birth.
        contact_phone: Primary phone.
        contact_email: Email address.
        contact_address: Mailing address.
        insurance_provider: Insurance payer.
        insurance_member_id: Insurance member identifier.
        insurance_group_number: Insurance group identifier.
        emergency_name: Emergency contact name.
        emergency_relationship: Emergency contact relationship.
        emergency_phone: Emergency contact phone.
        allergy_name: Repeated allergy names.
        allergy_reaction: Repeated allergy reactions.
        allergy_severity: Repeated allergy severities.
        medication_name: Repeated medication names.
        medication_dose: Repeated medication doses.
        medication_frequency: Repeated medication frequencies.
        contraception_method: Standing contraception method.
        include_clinical_fields: Whether the user may write sensitive fields.

    Returns:
        A dictionary ready to assign to a Patient model.

    Raises:
        ValueError: If a structured allergy or medication row is malformed.
    """

    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Patient name is required.")

    payload: dict[str, Any] = {
        "name": normalized_name,
        "date_of_birth": date_of_birth,
        "contact_info": compact_fields(
            {
                "phone": contact_phone,
                "email": contact_email,
                "address": contact_address,
            }
        ),
        "insurance_info": compact_fields(
            {
                "provider": insurance_provider,
                "member_id": insurance_member_id,
                "group_number": insurance_group_number,
            }
        ),
    }
    if include_clinical_fields:
        payload.update(
            {
                "emergency_contact": compact_fields(
                    {
                        "name": emergency_name,
                        "relationship": emergency_relationship,
                        "phone": emergency_phone,
                    }
                ),
                "allergies": normalize_structured_items(
                    "name",
                    allergy_name,
                    {
                        "reaction": allergy_reaction,
                        "severity": allergy_severity,
                    },
                ),
                "current_medications": normalize_structured_items(
                    "name",
                    medication_name,
                    {
                        "dose": medication_dose,
                        "frequency": medication_frequency,
                    },
                ),
                "contraception_method": contraception_method.strip() or None,
            }
        )
    return payload


def create_patient(
    db: Session,
    clinic_id: int,
    actor: User,
    payload: Mapping[str, Any],
) -> Patient:
    """Create a patient and append a create audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        clinic_id: Clinic tenant that owns the new patient.
        actor: Staff user creating the patient.
        payload: Validated patient field mapping.

    Returns:
        The pending Patient instance. The caller controls transaction commit.
    """

    patient = Patient(clinic_id=clinic_id, **payload)
    db.add(patient)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="patient",
        entity_id=patient.id,
    )
    return patient


def update_patient(
    db: Session,
    patient: Patient,
    actor: User,
    payload: Mapping[str, Any],
) -> Patient:
    """Update a patient and append an update audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        patient: Existing active patient record.
        actor: Staff user authorizing the update.
        payload: Validated fields allowed for the actor's role.

    Returns:
        The updated pending Patient instance. The caller controls the commit.
    """

    changed_fields: list[str] = []
    for field_name, value in payload.items():
        if getattr(patient, field_name) != value:
            setattr(patient, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="patient",
            entity_id=patient.id,
            details={"fields": changed_fields},
        )
    return patient


def get_patient_for_user(
    db: Session,
    patient_id: int,
    user: User,
) -> Patient | None:
    """Load an active patient only when it belongs to the user's clinic.

    Args:
        db: Request-scoped SQLAlchemy session.
        patient_id: Patient identifier.
        user: Authenticated staff user requesting the record.

    Returns:
        The clinic-scoped active patient with its clinic loaded, or None.
    """

    return db.scalar(
        select(Patient)
        .options(joinedload(Patient.clinic))
        .where(
            Patient.id == patient_id,
            Patient.clinic_id == user.clinic_id,
        )
    )


def serialize_patient(patient: Patient, user: User) -> dict[str, Any]:
    """Project a Patient into an API-safe role-specific dictionary.

    Args:
        patient: Patient record to serialize.
        user: Authenticated staff user receiving the projection.

    Returns:
        A dictionary that omits sensitive clinical fields for billing_clerk.
    """

    projection: dict[str, Any] = {
        "id": patient.id,
        "name": patient.name,
        "date_of_birth": patient.date_of_birth.isoformat(),
        "contact_info": patient.contact_info,
        "insurance_info": patient.insurance_info,
        "clinic_id": patient.clinic_id,
        "created_at": patient.created_at.isoformat() if patient.created_at else None,
    }
    if can_view_clinical_patient_fields(user):
        projection.update(
            {
                "emergency_contact": patient.emergency_contact,
                "allergies": patient.allergies,
                "current_medications": patient.current_medications,
                "contraception_method": patient.contraception_method,
            }
        )
    return projection


def patient_form_values(patient: Patient | None) -> dict[str, Any]:
    """Flatten a Patient record into template-friendly form values.

    Args:
        patient: Existing patient for edit mode, or None for create mode.

    Returns:
        A dictionary containing scalar values and structured row lists.
    """

    if patient is None:
        return {
            "name": "",
            "date_of_birth": "",
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": "",
        }
    return {
        "name": patient.name,
        "date_of_birth": patient.date_of_birth.isoformat(),
        "contact_info": patient.contact_info,
        "insurance_info": patient.insurance_info,
        "emergency_contact": patient.emergency_contact,
        "allergies": patient.allergies,
        "current_medications": patient.current_medications,
        "contraception_method": patient.contraception_method or "",
    }