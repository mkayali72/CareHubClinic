"""Scheduling business rules, clinic scoping, and calendar projections."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Appointment,
    AppointmentStatus,
    AppointmentType,
    AuditAction,
    Patient,
    User,
    UserRole,
)
from app.services.audit import record_audit_event
from app.services.patients import create_patient

SCHEDULING_ROLES = (
    UserRole.PHYSICIAN,
    UserRole.NURSE_MA,
    UserRole.FRONT_DESK,
    UserRole.CLINIC_ADMIN,
)
SCHEDULING_WRITE_ROLES = (
    UserRole.FRONT_DESK,
    UserRole.CLINIC_ADMIN,
)
APPOINTMENT_TYPE_ADMIN_ROLES = (UserRole.CLINIC_ADMIN,)
CALENDAR_START_HOUR = 7
CALENDAR_END_HOUR = 19
CALENDAR_MINUTES = (CALENDAR_END_HOUR - CALENDAR_START_HOUR) * 60

STATUS_TRANSITIONS: dict[AppointmentStatus, AppointmentStatus] = {
    AppointmentStatus.SCHEDULED: AppointmentStatus.CHECKED_IN,
    AppointmentStatus.CHECKED_IN: AppointmentStatus.IN_ROOM,
    AppointmentStatus.IN_ROOM: AppointmentStatus.WITH_DOCTOR,
    AppointmentStatus.WITH_DOCTOR: AppointmentStatus.DONE,
}


def ensure_role(user: User, allowed_roles: Iterable[UserRole]) -> None:
    """Require one of the supplied staff roles in service-layer code.

    Args:
        user: Staff user attempting the operation.
        allowed_roles: Roles allowed to continue.

    Raises:
        PermissionError: If the user's role is not allowed.
    """

    if user.role not in allowed_roles:
        raise PermissionError("Insufficient scheduling permissions.")


def get_appointment_types(db: Session, clinic_id: int) -> list[AppointmentType]:
    """Return active appointment types for one clinic, ordered by name."""

    return list(
        db.scalars(
            select(AppointmentType)
            .where(AppointmentType.clinic_id == clinic_id)
            .order_by(AppointmentType.name.asc(), AppointmentType.id.asc())
        )
    )


def get_physicians(db: Session, clinic_id: int) -> list[User]:
    """Return active physician users for a clinic."""

    return list(
        db.scalars(
            select(User)
            .where(
                User.clinic_id == clinic_id,
                User.role == UserRole.PHYSICIAN,
                User.is_active.is_(True),
            )
            .order_by(User.full_name.asc(), User.id.asc())
        )
    )


def get_schedulable_patients(db: Session, clinic_id: int) -> list[Patient]:
    """Return active patients available for appointment creation."""

    return list(
        db.scalars(
            select(Patient)
            .where(Patient.clinic_id == clinic_id)
            .order_by(Patient.name.asc(), Patient.id.asc())
        )
    )


def _clinic_patient(db: Session, clinic_id: int, patient_id: int) -> Patient:
    """Load an active patient belonging to the requested clinic."""

    patient = db.scalar(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
        )
    )
    if patient is None:
        raise ValueError("The selected patient does not belong to this clinic.")
    return patient


def _clinic_physician(db: Session, clinic_id: int, doctor_id: int) -> User:
    """Load an active physician belonging to the requested clinic."""

    doctor = db.scalar(
        select(User).where(
            User.id == doctor_id,
            User.clinic_id == clinic_id,
            User.role == UserRole.PHYSICIAN,
            User.is_active.is_(True),
        )
    )
    if doctor is None:
        raise ValueError("The selected doctor is not an active physician in this clinic.")
    return doctor


def _clinic_appointment_type(
    db: Session,
    clinic_id: int,
    appointment_type_id: int,
) -> AppointmentType:
    """Load an active appointment type belonging to the requested clinic."""

    appointment_type = db.scalar(
        select(AppointmentType).where(
            AppointmentType.id == appointment_type_id,
            AppointmentType.clinic_id == clinic_id,
        )
    )
    if appointment_type is None:
        raise ValueError("The selected appointment type does not belong to this clinic.")
    return appointment_type


def validate_appointment_inputs(
    db: Session,
    clinic_id: int,
    patient_id: int,
    doctor_id: int,
    appointment_type_id: int,
    scheduled_at: datetime,
    duration_minutes: int | None,
) -> tuple[Patient, User, AppointmentType, int]:
    """Validate cross-tenant references and resolve appointment duration."""

    if scheduled_at is None:
        raise ValueError("Scheduled time is required.")
    patient = _clinic_patient(db, clinic_id, patient_id)
    doctor = _clinic_physician(db, clinic_id, doctor_id)
    appointment_type = _clinic_appointment_type(
        db,
        clinic_id,
        appointment_type_id,
    )
    resolved_duration = duration_minutes or appointment_type.default_duration_minutes
    if resolved_duration <= 0:
        raise ValueError("Appointment duration must be greater than zero.")
    return patient, doctor, appointment_type, resolved_duration


def create_appointment(
    db: Session,
    clinic_id: int,
    actor: User,
    patient_id: int,
    doctor_id: int,
    appointment_type_id: int,
    scheduled_at: datetime,
    duration_minutes: int | None = None,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
    client_request_id: str | None = None,
) -> Appointment:
    """Create and audit a clinic-scoped appointment.

    Args:
        db: Request-scoped database session.
        clinic_id: Clinic tenant that owns the appointment.
        actor: Staff user creating the appointment.
        patient_id: Existing patient identifier.
        doctor_id: Physician identifier.
        appointment_type_id: Appointment type identifier.
        scheduled_at: Clinic-local appointment date and time.
        duration_minutes: Optional override for the type default.
        status: Initial appointment status.
        client_request_id: Optional browser request identity used for safe retries.

    Returns:
        A pending Appointment row. The caller controls the transaction commit.

    Raises:
        PermissionError: If the actor cannot create appointments.
        ValueError: If a reference is outside the clinic or inputs are invalid.
    """

    ensure_role(actor, SCHEDULING_WRITE_ROLES)
    if actor.clinic_id != clinic_id:
        raise PermissionError("The actor does not belong to this clinic.")
    patient, doctor, appointment_type, resolved_duration = validate_appointment_inputs(
        db,
        clinic_id,
        patient_id,
        doctor_id,
        appointment_type_id,
        scheduled_at,
        duration_minutes,
    )
    appointment = Appointment(
        clinic_id=clinic_id,
        patient=patient,
        doctor=doctor,
        appointment_type=appointment_type,
        scheduled_at=scheduled_at,
        duration_minutes=resolved_duration,
        status=status,
        client_request_id=client_request_id,
    )
    db.add(appointment)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="appointment",
        entity_id=appointment.id,
        details={
            "patient_id": patient.id,
            "doctor_id": doctor.id,
            "status": status.value,
        },
    )
    return appointment


def create_walk_in(
    db: Session,
    clinic_id: int,
    actor: User,
    name: str,
    date_of_birth: date,
    phone: str,
    doctor_id: int,
    appointment_type_id: int,
) -> Appointment:
    """Create a new patient and a checked-in appointment atomically."""

    ensure_role(actor, SCHEDULING_WRITE_ROLES)
    if actor.clinic_id != clinic_id:
        raise PermissionError("The actor does not belong to this clinic.")
    if not name.strip():
        raise ValueError("Walk-in patient name is required.")
    if date_of_birth is None:
        raise ValueError("Walk-in patient date of birth is required.")

    appointment_type = _clinic_appointment_type(
        db,
        clinic_id,
        appointment_type_id,
    )
    doctor = _clinic_physician(db, clinic_id, doctor_id)
    patient = create_patient(
        db=db,
        clinic_id=clinic_id,
        actor=actor,
        payload={
            "name": name.strip(),
            "date_of_birth": date_of_birth,
            "contact_info": {"phone": phone.strip()} if phone.strip() else {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    appointment = Appointment(
        clinic_id=clinic_id,
        patient=patient,
        doctor=doctor,
        appointment_type=appointment_type,
        scheduled_at=datetime.now().replace(second=0, microsecond=0),
        duration_minutes=appointment_type.default_duration_minutes,
        status=AppointmentStatus.CHECKED_IN,
    )
    db.add(appointment)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="appointment",
        entity_id=appointment.id,
        details={
            "patient_id": patient.id,
            "doctor_id": doctor.id,
            "status": AppointmentStatus.CHECKED_IN.value,
            "walk_in": True,
        },
    )
    return appointment


def update_appointment(
    db: Session,
    appointment: Appointment,
    actor: User,
    patient_id: int,
    doctor_id: int,
    appointment_type_id: int,
    scheduled_at: datetime,
    duration_minutes: int | None = None,
) -> Appointment:
    """Edit an active appointment while preserving its audit history.

    Args:
        db: Request-scoped database session.
        appointment: Existing appointment to edit.
        actor: Staff user performing the edit.
        patient_id: Replacement patient identifier.
        doctor_id: Replacement physician identifier.
        appointment_type_id: Replacement appointment type identifier.
        scheduled_at: Replacement clinic-local date and time.
        duration_minutes: Optional replacement duration, or the type default.

    Returns:
        The edited appointment.

    Raises:
        PermissionError: If the actor cannot edit appointments.
        ValueError: If the appointment is terminal or any reference is invalid.
    """

    ensure_role(actor, SCHEDULING_WRITE_ROLES)
    if actor.clinic_id != appointment.clinic_id:
        raise PermissionError("The appointment does not belong to this clinic.")
    if appointment.status in (
        AppointmentStatus.DONE,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    ):
        raise ValueError("Completed or closed appointments cannot be edited.")
    patient, doctor, appointment_type, resolved_duration = validate_appointment_inputs(
        db,
        appointment.clinic_id,
        patient_id,
        doctor_id,
        appointment_type_id,
        scheduled_at,
        duration_minutes,
    )
    changed_fields: list[str] = []
    if appointment.patient_id != patient.id:
        appointment.patient = patient
        changed_fields.append("patient_id")
    if appointment.doctor_id != doctor.id:
        appointment.doctor = doctor
        changed_fields.append("doctor_id")
    if appointment.appointment_type_id != appointment_type.id:
        appointment.appointment_type = appointment_type
        changed_fields.append("appointment_type_id")
    if appointment.scheduled_at != scheduled_at:
        appointment.scheduled_at = scheduled_at
        changed_fields.append("scheduled_at")
    if appointment.duration_minutes != resolved_duration:
        appointment.duration_minutes = resolved_duration
        changed_fields.append("duration_minutes")
    if changed_fields:
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="appointment",
            entity_id=appointment.id,
            details={"fields": changed_fields},
        )
    return appointment


def cancel_appointment(
    db: Session,
    appointment: Appointment,
    actor: User,
) -> Appointment:
    """Cancel an active appointment and write an immutable audit event."""

    ensure_role(actor, SCHEDULING_WRITE_ROLES)
    if actor.clinic_id != appointment.clinic_id:
        raise PermissionError("The appointment does not belong to this clinic.")
    if appointment.status in (
        AppointmentStatus.DONE,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    ):
        raise ValueError("This appointment is already closed.")
    previous_status = appointment.status
    appointment.status = AppointmentStatus.CANCELLED
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="appointment",
        entity_id=appointment.id,
        details={
            "field": "status",
            "from": previous_status.value,
            "to": AppointmentStatus.CANCELLED.value,
        },
    )
    return appointment


def get_appointment_for_user(
    db: Session,
    appointment_id: int,
    user: User,
) -> Appointment | None:
    """Load an active appointment scoped to the user's clinic."""

    return db.scalar(
        select(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor),
            joinedload(Appointment.appointment_type),
        )
        .where(
            Appointment.id == appointment_id,
            Appointment.clinic_id == user.clinic_id,
        )
    )


def get_appointments_for_date(
    db: Session,
    user: User,
    selected_date: date,
    doctor_id: int | None = None,
) -> list[Appointment]:
    """Return clinic appointments for a date, optionally filtered to a doctor."""

    start = datetime.combine(selected_date, time.min)
    end = start + timedelta(days=1)
    conditions = [
        Appointment.clinic_id == user.clinic_id,
        Appointment.scheduled_at >= start,
        Appointment.scheduled_at < end,
    ]
    if doctor_id is not None:
        conditions.append(Appointment.doctor_id == doctor_id)
    return list(
        db.scalars(
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor),
                joinedload(Appointment.appointment_type),
            )
            .where(*conditions)
            .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
        )
    )


def advance_appointment_status(
    db: Session,
    appointment: Appointment,
    actor: User,
) -> Appointment:
    """Advance an appointment by exactly one allowed queue transition."""

    ensure_role(actor, SCHEDULING_ROLES)
    if actor.clinic_id != appointment.clinic_id:
        raise PermissionError("The appointment does not belong to this clinic.")
    next_status = STATUS_TRANSITIONS.get(appointment.status)
    if next_status is None:
        raise ValueError("This appointment has no further queue transition.")
    previous_status = appointment.status
    appointment.status = next_status
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="appointment",
        entity_id=appointment.id,
        details={
            "field": "status",
            "from": previous_status.value,
            "to": next_status.value,
        },
    )
    return appointment


def create_appointment_type(
    db: Session,
    clinic_id: int,
    actor: User,
    name: str,
    default_duration_minutes: int,
) -> AppointmentType:
    """Create a clinic appointment type as a clinic administrator."""

    ensure_role(actor, APPOINTMENT_TYPE_ADMIN_ROLES)
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Appointment type name is required.")
    if default_duration_minutes <= 0:
        raise ValueError("Default duration must be greater than zero.")
    existing = db.scalar(
        select(AppointmentType).where(
            AppointmentType.clinic_id == clinic_id,
            AppointmentType.name == normalized_name,
        )
    )
    if existing is not None:
        raise ValueError("An appointment type with this name already exists.")
    appointment_type = AppointmentType(
        clinic_id=clinic_id,
        name=normalized_name,
        default_duration_minutes=default_duration_minutes,
    )
    db.add(appointment_type)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.CREATE,
        entity_type="appointment_type",
        entity_id=appointment_type.id,
    )
    return appointment_type


def update_appointment_type(
    db: Session,
    appointment_type: AppointmentType,
    actor: User,
    name: str,
    default_duration_minutes: int,
) -> AppointmentType:
    """Edit a clinic appointment type as a clinic administrator."""

    ensure_role(actor, APPOINTMENT_TYPE_ADMIN_ROLES)
    if actor.clinic_id != appointment_type.clinic_id:
        raise PermissionError("The appointment type does not belong to this clinic.")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Appointment type name is required.")
    if default_duration_minutes <= 0:
        raise ValueError("Default duration must be greater than zero.")
    duplicate = db.scalar(
        select(AppointmentType).where(
            AppointmentType.clinic_id == appointment_type.clinic_id,
            AppointmentType.name == normalized_name,
            AppointmentType.id != appointment_type.id,
        )
    )
    if duplicate is not None:
        raise ValueError("An appointment type with this name already exists.")
    changed_fields: list[str] = []
    if appointment_type.name != normalized_name:
        appointment_type.name = normalized_name
        changed_fields.append("name")
    if appointment_type.default_duration_minutes != default_duration_minutes:
        appointment_type.default_duration_minutes = default_duration_minutes
        changed_fields.append("default_duration_minutes")
    if changed_fields:
        record_audit_event(
            db=db,
            actor_user_id=actor.id,
            action=AuditAction.UPDATE,
            entity_type="appointment_type",
            entity_id=appointment_type.id,
            details={"fields": changed_fields},
        )
    return appointment_type


def calendar_columns(
    doctors: list[User],
    appointments: list[Appointment],
) -> list[dict[str, Any]]:
    """Build lightweight doctor columns for the vanilla calendar template."""

    by_doctor: dict[int, list[dict[str, Any]]] = {doctor.id: [] for doctor in doctors}
    for appointment in appointments:
        minutes_from_start = (
            appointment.scheduled_at.hour * 60
            + appointment.scheduled_at.minute
            - CALENDAR_START_HOUR * 60
        )
        top = max(0, min(minutes_from_start, CALENDAR_MINUTES - 20))
        height = max(
            28,
            min(appointment.duration_minutes, CALENDAR_MINUTES - top),
        )
        by_doctor.setdefault(appointment.doctor_id, []).append(
            {
                "appointment": appointment,
                "top": top,
                "height": height,
            }
        )
    return [
        {"doctor": doctor, "appointments": by_doctor.get(doctor.id, [])}
        for doctor in doctors
    ]


def serialize_appointment(appointment: Appointment) -> dict[str, Any]:
    """Return an API-safe appointment representation."""

    return {
        "id": appointment.id,
        "patient_id": appointment.patient_id,
        "patient_name": appointment.patient.name,
        "doctor_id": appointment.doctor_id,
        "doctor_name": appointment.doctor.full_name,
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "duration_minutes": appointment.duration_minutes,
        "appointment_type_id": appointment.appointment_type_id,
        "appointment_type": appointment.appointment_type.name,
        "status": appointment.status.value,
    }