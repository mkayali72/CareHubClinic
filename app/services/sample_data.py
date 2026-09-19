"""First-run sample records and clinic-admin sample-data management."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Appointment,
    AppointmentType,
    AuditAction,
    LabOrder,
    LabOrderStatus,
    LabResult,
    LabTestDefinition,
    Patient,
    User,
    UserRole,
    Visit,
    VisitType,
    Clinic,
)
from app.services.audit import record_audit_event, soft_delete_record
from app.services.auth import (
    STAFF_ROLES,
    create_user,
    deactivate_user,
    validate_password,
)

SAMPLE_DATA_KEY = "sample_data"
SAMPLE_PASSWORD = "Admin22446688"
SAMPLE_STAFF_USERNAMES = (
    ("sample_dr_1", "Sample_Dr_1", UserRole.PHYSICIAN),
    ("sample_dr_2", "Sample_Dr_2", UserRole.PHYSICIAN),
    ("sample_dr_3", "Sample_Dr_3", UserRole.PHYSICIAN),
    ("sample_front", "Sample_Front_Office", UserRole.FRONT_DESK),
    ("sample_nurse", "Sample_Nurse", UserRole.NURSE_MA),
    ("sample_billing", "Sample_Billing_Clerk", UserRole.BILLING_CLERK),
)
SAMPLE_APPOINTMENT_TYPES = (
    ("Sample - New patient", 45),
    ("Sample - Follow-up", 30),
    ("Sample - Prenatal visit", 45),
    ("Sample - Annual gynecology visit", 60),
    ("Sample - Urgent visit", 30),
)
SAMPLE_LAB_DEFINITIONS = (
    ("Sample CBC", "Complete blood count"),
    ("Sample Urinalysis", "Routine urine screening"),
    ("Sample Pregnancy Panel", "Basic prenatal laboratory panel"),
)


def _empty_registry() -> dict[str, Any]:
    return {
        "initialized": False,
        "staff_ids": [],
        "appointment_type_ids": [],
        "patient_ids": [],
        "lab_definition_ids": [],
        "lab_order_ids": [],
        "visit_ids": [],
    }


def sample_registry(clinic: Clinic) -> dict[str, Any]:
    """Return a normalized copy of the clinic's sample-record registry."""

    stored = clinic.settings.get(SAMPLE_DATA_KEY, {}) if clinic.settings else {}
    registry = _empty_registry()
    registry.update(deepcopy(stored))
    for key in _empty_registry():
        if key.endswith("_ids"):
            registry[key] = [int(value) for value in registry.get(key, [])]
    return registry


def _save_registry(clinic: Clinic, registry: dict[str, Any]) -> None:
    settings = dict(clinic.settings or {})
    settings[SAMPLE_DATA_KEY] = registry
    clinic.settings = settings


def _registered(registry: dict[str, Any], key: str, record_id: int) -> bool:
    return record_id in registry.get(key, [])


def _remove_id(registry: dict[str, Any], key: str, record_id: int) -> None:
    registry[key] = [value for value in registry.get(key, []) if value != record_id]


def ensure_sample_data(db: Session, clinic: Clinic, admin: User) -> bool:
    """Create the demo staff, lookup records, patients, and lab orders once."""

    registry = sample_registry(clinic)
    if registry["initialized"]:
        return False
    if admin.clinic_id != clinic.id or admin.role is not UserRole.CLINIC_ADMIN:
        raise ValueError("Sample data must be initialized by a clinic administrator.")
    validate_password(SAMPLE_PASSWORD)

    for username, full_name, role in SAMPLE_STAFF_USERNAMES:
        user = db.scalar(
            select(User)
            .execution_options(include_deleted=True)
            .where(User.username == username)
        )
        if user is None:
            user = create_user(
                db,
                clinic.id,
                username,
                SAMPLE_PASSWORD,
                full_name,
                role,
                actor=admin,
            )
        elif user.clinic_id != clinic.id:
            raise ValueError(f"Sample username {username!r} belongs to another clinic.")
        registry["staff_ids"].append(user.id)

    for name, duration in SAMPLE_APPOINTMENT_TYPES:
        appointment_type = db.scalar(
            select(AppointmentType)
            .execution_options(include_deleted=True)
            .where(
                AppointmentType.clinic_id == clinic.id,
                AppointmentType.name == name,
            )
        )
        if appointment_type is None:
            appointment_type = AppointmentType(
                clinic_id=clinic.id,
                name=name,
                default_duration_minutes=duration,
            )
            db.add(appointment_type)
            db.flush()
            record_audit_event(
                db,
                admin.id,
                AuditAction.CREATE,
                "appointment_type",
                appointment_type.id,
                {"sample_data": True},
            )
        registry["appointment_type_ids"].append(appointment_type.id)

    patients: list[Patient] = []
    patient_details = (
        ("Sample_Patient_1", date(1990, 1, 15), "+974 5555 0101"),
        ("Sample_Patient_2", date(1985, 6, 20), "+974 5555 0102"),
        ("Sample_Patient_3", date(1992, 11, 3), "+974 5555 0103"),
    )
    for name, date_of_birth, phone in patient_details:
        patient = db.scalar(
            select(Patient)
            .execution_options(include_deleted=True)
            .where(Patient.clinic_id == clinic.id, Patient.name == name)
        )
        if patient is None:
            patient = Patient(
                clinic_id=clinic.id,
                name=name,
                date_of_birth=date_of_birth,
                contact_info={"phone": phone},
                insurance_info={},
                emergency_contact={},
                allergies=[],
                current_medications=[],
                contraception_method=None,
            )
            db.add(patient)
            db.flush()
            record_audit_event(
                db,
                admin.id,
                AuditAction.CREATE,
                "patient",
                patient.id,
                {"sample_data": True},
            )
        patients.append(patient)
        registry["patient_ids"].append(patient.id)

    definitions: list[LabTestDefinition] = []
    for name, description in SAMPLE_LAB_DEFINITIONS:
        definition = db.scalar(
            select(LabTestDefinition)
            .where(
                LabTestDefinition.clinic_id == clinic.id,
                LabTestDefinition.name == name,
            )
        )
        if definition is None:
            definition = LabTestDefinition(
                clinic_id=clinic.id,
                name=name,
                description=description,
                active=True,
            )
            db.add(definition)
            db.flush()
        definitions.append(definition)
        registry["lab_definition_ids"].append(definition.id)

    visit = Visit(
        clinic_id=clinic.id,
        patient=patients[0],
        visit_type=VisitType.PROBLEM_FOCUSED,
        visit_date=date.today(),
        vitals={},
        prenatal_data={},
        gyn_data={},
        hpi="Sample visit created for laboratory-order demonstration.",
        assessment="Sample demonstration visit.",
        plan="Review sample laboratory results.",
    )
    db.add(visit)
    db.flush()
    registry["visit_ids"].append(visit.id)
    for definition in definitions:
        order = LabOrder(
            clinic_id=clinic.id,
            visit=visit,
            patient=patients[0],
            lab_test_definition=definition,
            status=LabOrderStatus.ORDERED,
            ordered_by_user_id=admin.id,
        )
        db.add(order)
        db.flush()
        registry["lab_order_ids"].append(order.id)
        record_audit_event(
            db,
            admin.id,
            AuditAction.CREATE,
            "lab_order",
            order.id,
            {"sample_data": True},
        )

    registry["initialized"] = True
    _save_registry(clinic, registry)
    return True


def _clinic_and_registry(
    db: Session,
    actor: User,
) -> tuple[Clinic, dict[str, Any]]:
    clinic = db.scalar(select(Clinic).where(Clinic.id == actor.clinic_id))
    if clinic is None:
        raise ValueError("Clinic not found.")
    return clinic, sample_registry(clinic)


def _require_sample_admin(actor: User) -> None:
    if actor.role is not UserRole.CLINIC_ADMIN:
        raise PermissionError("Only clinic administrators can manage sample data.")


def get_sample_data(db: Session, actor: User) -> dict[str, Any]:
    """Load all current sample rows for the administrator management page."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    staff = list(
        db.scalars(
            select(User)
            .where(User.id.in_(registry["staff_ids"]))
            .order_by(User.full_name, User.id)
        )
    )
    appointment_types = list(
        db.scalars(
            select(AppointmentType)
            .where(AppointmentType.id.in_(registry["appointment_type_ids"]))
            .order_by(AppointmentType.name, AppointmentType.id)
        )
    )
    patients = list(
        db.scalars(
            select(Patient)
            .where(Patient.id.in_(registry["patient_ids"]))
            .order_by(Patient.name, Patient.id)
        )
    )
    lab_orders = list(
        db.scalars(
            select(LabOrder)
            .options(
                joinedload(LabOrder.patient),
                joinedload(LabOrder.lab_test_definition),
            )
            .where(LabOrder.id.in_(registry["lab_order_ids"]))
            .order_by(LabOrder.id)
        )
    )
    lab_definitions = list(
        db.scalars(
            select(LabTestDefinition)
            .where(LabTestDefinition.id.in_(registry["lab_definition_ids"]))
            .order_by(LabTestDefinition.name)
        )
    )
    return {
        "clinic": clinic,
        "registry": registry,
        "staff": staff,
        "appointment_types": appointment_types,
        "patients": patients,
        "lab_orders": lab_orders,
        "lab_definitions": lab_definitions,
        "lab_statuses": list(LabOrderStatus),
    }


def update_sample_staff(
    db: Session,
    actor: User,
    target: User,
    username: str,
    full_name: str,
    role: UserRole,
) -> User:
    """Edit a registered sample staff account."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if target.clinic_id != clinic.id or not _registered(registry, "staff_ids", target.id):
        raise ValueError("That account is not a registered sample account.")
    if target.id == actor.id:
        raise ValueError("The signed-in administrator cannot be a sample account.")
    normalized_username = username.strip().lower()
    normalized_name = full_name.strip()
    if not normalized_username or len(normalized_username) > 16:
        raise ValueError("Username must be 1–16 characters.")
    if not normalized_name:
        raise ValueError("Full name is required.")
    if role not in STAFF_ROLES:
        raise ValueError("Select a supported staff role.")
    duplicate = db.scalar(
        select(User)
        .execution_options(include_deleted=True)
        .where(User.username == normalized_username, User.id != target.id)
    )
    if duplicate is not None:
        raise ValueError("That username is already in use.")
    changed = []
    if target.username != normalized_username:
        target.username = normalized_username
        changed.append("username")
    if target.full_name != normalized_name:
        target.full_name = normalized_name
        changed.append("full_name")
    if target.role is not role:
        target.role = role
        changed.append("role")
    if changed:
        record_audit_event(
            db,
            actor.id,
            AuditAction.UPDATE,
            "user",
            target.id,
            {"fields": changed, "sample_data": True},
        )
    return target


def update_sample_lab_order(
    db: Session,
    actor: User,
    order: LabOrder,
    lab_test_definition_id: int,
    status: LabOrderStatus,
) -> LabOrder:
    """Edit the test and lifecycle status of a registered sample order."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if order.clinic_id != clinic.id or not _registered(registry, "lab_order_ids", order.id):
        raise ValueError("That lab order is not a registered sample order.")
    definition = db.scalar(
        select(LabTestDefinition).where(
            LabTestDefinition.id == lab_test_definition_id,
            LabTestDefinition.clinic_id == clinic.id,
        )
    )
    if definition is None:
        raise ValueError("Select a lab test from this clinic.")
    changed = []
    if order.lab_test_definition_id != definition.id:
        order.lab_test_definition = definition
        changed.append("lab_test_definition")
    if order.status is not status:
        order.status = status
        changed.append("status")
    if changed:
        record_audit_event(
            db,
            actor.id,
            AuditAction.UPDATE,
            "lab_order",
            order.id,
            {"fields": changed, "sample_data": True},
        )
    return order


def delete_sample_staff(db: Session, actor: User, target: User) -> None:
    """Remove one registered sample staff account with an audit-preserving delete."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if target.clinic_id != clinic.id or not _registered(registry, "staff_ids", target.id):
        raise ValueError("That account is not a registered sample account.")
    if target.id == actor.id or target.role is UserRole.CLINIC_ADMIN:
        raise ValueError("The signed-in clinic administrator cannot be deleted.")
    deactivate_user(db, actor, target)


def delete_sample_appointment_type(
    db: Session,
    actor: User,
    appointment_type: AppointmentType,
) -> None:
    """Remove a registered sample appointment type with an audit trail."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if (
        appointment_type.clinic_id != clinic.id
        or not _registered(registry, "appointment_type_ids", appointment_type.id)
    ):
        raise ValueError("That appointment type is not a registered sample record.")
    used = db.scalar(
        select(Appointment).where(Appointment.appointment_type_id == appointment_type.id)
    )
    if used is not None:
        raise ValueError("This appointment type is in use and cannot be deleted.")
    soft_delete_record(
        db,
        appointment_type,
        actor,
        "appointment_type",
        appointment_type.id,
        details={"sample_data": True},
    )


def delete_sample_lab_order(db: Session, actor: User, order: LabOrder) -> None:
    """Remove a registered sample lab order with an audit trail."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if order.clinic_id != clinic.id or not _registered(registry, "lab_order_ids", order.id):
        raise ValueError("That lab order is not a registered sample order.")
    result = db.scalar(select(LabResult).where(LabResult.lab_order_id == order.id))
    if result is not None:
        raise ValueError("Sample lab orders with results must be retained for audit history.")
    soft_delete_record(
        db,
        order,
        actor,
        "lab_order",
        order.id,
        details={"sample_data": True},
    )


def delete_sample_patient(db: Session, actor: User, patient: Patient) -> None:
    """Remove a sample patient and generated lab data with audit-preserving deletes."""

    _require_sample_admin(actor)
    clinic, registry = _clinic_and_registry(db, actor)
    if patient.clinic_id != clinic.id or not _registered(registry, "patient_ids", patient.id):
        raise ValueError("That patient is not a registered sample patient.")
    appointment = db.scalar(
        select(Appointment).where(Appointment.patient_id == patient.id)
    )
    if appointment is not None:
        raise ValueError("This sample patient has an appointment and cannot be deleted yet.")
    order_ids = list(
        db.scalars(
            select(LabOrder.id)
            .where(LabOrder.patient_id == patient.id)
            .execution_options(include_deleted=True)
        )
    )
    if any(not _registered(registry, "lab_order_ids", order_id) for order_id in order_ids):
        raise ValueError("This patient has non-sample lab orders and cannot be deleted.")
    for order_id in order_ids:
        order = db.scalar(
            select(LabOrder)
            .execution_options(include_deleted=True)
            .where(LabOrder.id == order_id)
        )
        if order is not None and order.deleted_at is None:
            delete_sample_lab_order(db, actor, order)
    visit_ids = list(
        db.scalars(
            select(Visit.id)
            .where(Visit.patient_id == patient.id)
            .execution_options(include_deleted=True)
        )
    )
    registered_visits = set(registry["visit_ids"])
    if any(visit_id not in registered_visits for visit_id in visit_ids):
        raise ValueError("This patient has non-sample visits and cannot be deleted.")
    for visit_id in visit_ids:
        visit = db.scalar(
            select(Visit)
            .execution_options(include_deleted=True)
            .where(Visit.id == visit_id)
        )
        if visit is not None and visit.deleted_at is None:
            soft_delete_record(
                db,
                visit,
                actor,
                "visit",
                visit.id,
                details={"sample_data": True},
            )
    soft_delete_record(
        db,
        patient,
        actor,
        "patient",
        patient.id,
        details={"sample_data": True},
    )