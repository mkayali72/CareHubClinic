"""Optional Billing module rules, feature gating, and financial workflows.

The Billing feature flag is a server-side authorization boundary, not a
presentation preference. Every operational service in this module calls
``ensure_billing_enabled`` before reading or mutating billing data. Routes add
the same check so a disabled clinic receives a deliberate not-found response
even when someone bypasses the UI and calls the URL directly.

The clinic feature-settings service is intentionally separate: an administrator
must still be able to reach the settings screen and re-enable a disabled
module. That route is a feature-management route, not an operational Billing
route, and never deletes or filters historical invoices.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    AuditAction,
    Charge,
    Clinic,
    FeeScheduleItem,
    Invoice,
    InvoiceStatus,
    Patient,
    User,
    UserRole,
    Visit,
)
from app.services.audit import (
    ensure_clinic_admin,
    record_audit_event,
    soft_delete_record,
)

BILLING_ROLES = (UserRole.BILLING_CLERK, UserRole.CLINIC_ADMIN)
DEFAULT_FEE_SCHEDULE: tuple[tuple[str, str, str], ...] = (
    ("New patient consultation", "Initial consultation and intake", "150.00"),
    ("Prenatal follow-up", "Routine prenatal follow-up visit", "125.00"),
    ("Gynecology annual exam", "Annual gynecology examination", "175.00"),
    ("Ultrasound review", "Review of external or clinic ultrasound", "75.00"),
    ("Procedure counseling", "Pre-procedure counseling and planning", "100.00"),
)


class BillingModuleDisabled(ValueError):
    """Raised when an operational Billing action targets a disabled clinic."""


def billing_role_allowed(actor: User) -> bool:
    """Return whether the actor may operate the optional Billing module."""

    return actor.role in BILLING_ROLES


def ensure_billing_enabled(db: Session, clinic_id: int) -> Clinic:
    """Require a clinic's optional Billing module to be enabled.

    This is deliberately shared by every service query and mutation. Keeping
    the check in the service layer prevents a future route, background task,
    or direct API handler from exposing Billing merely because a UI condition
    was omitted.

    Raises:
        BillingModuleDisabled: When the clinic exists but opted out.
        ValueError: When the clinic does not exist.
    """

    clinic = db.scalar(select(Clinic).where(Clinic.id == clinic_id))
    if clinic is None:
        raise ValueError("Clinic not found.")
    if not clinic.billing_module_enabled:
        raise BillingModuleDisabled(
            "Billing is not available for this clinic while the optional module is disabled."
        )
    return clinic


def set_billing_enabled(
    db: Session,
    actor: User,
    enabled: bool,
) -> Clinic:
    """Toggle Billing without deleting, hiding, or rewriting its history.

    This is the only Billing-adjacent mutation allowed while the module is
    disabled. It is a clinic feature-management action and therefore does not
    call ``ensure_billing_enabled``.
    """

    ensure_clinic_admin(actor)
    clinic = db.scalar(select(Clinic).where(Clinic.id == actor.clinic_id))
    if clinic is None:
        raise ValueError("Clinic not found.")
    previous = clinic.billing_module_enabled
    clinic.billing_module_enabled = enabled
    record_audit_event(
        db,
        actor.id,
        AuditAction.UPDATE,
        "clinic",
        clinic.id,
        details={
            "feature": "billing_module_enabled",
            "from": previous,
            "to": enabled,
            "history_retained": True,
        },
    )
    return clinic


def ensure_default_fee_schedule(
    db: Session,
    clinic_id: int,
) -> list[FeeScheduleItem]:
    """Seed a starter price list once for a clinic."""

    existing = list(
        db.scalars(
            select(FeeScheduleItem).where(FeeScheduleItem.clinic_id == clinic_id)
        )
    )
    if existing:
        return existing
    items = [
        FeeScheduleItem(
            clinic_id=clinic_id,
            name=name,
            description=description,
            unit_price=Decimal(amount),
            active=True,
        )
        for name, description, amount in DEFAULT_FEE_SCHEDULE
    ]
    db.add_all(items)
    db.flush()
    return items


def get_fee_schedule(
    db: Session,
    actor: User,
    *,
    active_only: bool = False,
) -> list[FeeScheduleItem]:
    """Return the current clinic price list after the module gate."""

    ensure_billing_enabled(db, actor.clinic_id)
    ensure_default_fee_schedule(db, actor.clinic_id)
    conditions = [FeeScheduleItem.clinic_id == actor.clinic_id]
    if active_only:
        conditions.append(FeeScheduleItem.active.is_(True))
    return list(
        db.scalars(
            select(FeeScheduleItem)
            .where(*conditions)
            .order_by(FeeScheduleItem.name.asc())
        )
    )


def _validate_price(value: Decimal | str) -> Decimal:
    try:
        price = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Fee schedule price must be a valid amount.") from error
    if price < 0:
        raise ValueError("Fee schedule price cannot be negative.")
    return price


def create_fee_schedule_item(
    db: Session,
    actor: User,
    name: str,
    description: str,
    unit_price: Decimal | str,
) -> FeeScheduleItem:
    """Create one clinic-admin-controlled billable service."""

    ensure_clinic_admin(actor)
    ensure_billing_enabled(db, actor.clinic_id)
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Fee schedule item name is required.")
    item = FeeScheduleItem(
        clinic_id=actor.clinic_id,
        name=clean_name,
        description=description.strip(),
        unit_price=_validate_price(unit_price),
        active=True,
    )
    db.add(item)
    db.flush()
    record_audit_event(
        db,
        actor.id,
        AuditAction.CREATE,
        "fee_schedule_item",
        item.id,
        details={"name": item.name, "unit_price": str(item.unit_price)},
    )
    return item


def update_fee_schedule_item(
    db: Session,
    actor: User,
    item: FeeScheduleItem,
    name: str,
    description: str,
    unit_price: Decimal | str,
    active: bool,
) -> FeeScheduleItem:
    """Edit a fee item without rewriting existing charge snapshots."""

    ensure_clinic_admin(actor)
    ensure_billing_enabled(db, actor.clinic_id)
    if item.clinic_id != actor.clinic_id:
        raise PermissionError("The fee schedule item does not belong to this clinic.")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Fee schedule item name is required.")
    before = {
        "name": item.name,
        "description": item.description,
        "unit_price": str(item.unit_price),
        "active": item.active,
    }
    item.name = clean_name
    item.description = description.strip()
    item.unit_price = _validate_price(unit_price)
    item.active = active
    record_audit_event(
        db,
        actor.id,
        AuditAction.UPDATE,
        "fee_schedule_item",
        item.id,
        details={
            "before": before,
            "after": {
                "name": item.name,
                "description": item.description,
                "unit_price": str(item.unit_price),
                "active": item.active,
            },
        },
    )
    return item


def _visit_for_billing(db: Session, actor: User, visit_id: int) -> Visit:
    visit = db.scalar(
        select(Visit)
        .options(joinedload(Visit.patient))
        .where(Visit.id == visit_id, Visit.clinic_id == actor.clinic_id)
    )
    if visit is None:
        raise ValueError("Visit not found in this clinic.")
    return visit


def create_invoice(
    db: Session,
    actor: User,
    visit_id: int,
    fee_schedule_item_ids: Iterable[int],
    notes: str = "",
) -> Invoice:
    """Create an unpaid invoice with one charge for each selected fee item."""

    ensure_billing_enabled(db, actor.clinic_id)
    if not billing_role_allowed(actor):
        raise PermissionError("Only billing clerks and clinic administrators may enter charges.")
    visit = _visit_for_billing(db, actor, visit_id)
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in fee_schedule_item_ids))
    if not requested_ids:
        raise ValueError("Select at least one fee schedule item.")
    items = list(
        db.scalars(
            select(FeeScheduleItem).where(
                FeeScheduleItem.clinic_id == actor.clinic_id,
                FeeScheduleItem.id.in_(requested_ids),
                FeeScheduleItem.active.is_(True),
            )
        )
    )
    by_id = {item.id: item for item in items}
    if len(by_id) != len(requested_ids):
        raise ValueError("One or more selected fee schedule items are unavailable.")
    invoice = Invoice(
        clinic_id=actor.clinic_id,
        visit_id=visit.id,
        patient_id=visit.patient_id,
        status=InvoiceStatus.UNPAID,
        notes=notes.strip(),
        created_by_user_id=actor.id,
    )
    db.add(invoice)
    db.flush()
    for item_id in requested_ids:
        item = by_id[item_id]
        amount = _validate_price(item.unit_price)
        db.add(
            Charge(
                clinic_id=actor.clinic_id,
                invoice_id=invoice.id,
                visit_id=visit.id,
                patient_id=visit.patient_id,
                fee_schedule_item_id=item.id,
                description_snapshot=(
                    item.name
                    if not item.description
                    else f"{item.name} — {item.description}"
                ),
                unit_price=amount,
                quantity=1,
                total_amount=amount,
            )
        )
    record_audit_event(
        db,
        actor.id,
        AuditAction.CREATE,
        "invoice",
        invoice.id,
        details={
            "visit_id": visit.id,
            "patient_id": visit.patient_id,
            "fee_schedule_item_ids": requested_ids,
            "status": InvoiceStatus.UNPAID.value,
        },
    )
    db.flush()
    return invoice


def _invoice_options() -> tuple[Any, ...]:
    return (
        joinedload(Invoice.visit),
        joinedload(Invoice.patient),
        joinedload(Invoice.created_by_user),
        selectinload(Invoice.charges).joinedload(Charge.fee_schedule_item),
    )


def get_invoice_for_user(
    db: Session,
    actor: User,
    invoice_id: int,
) -> Invoice:
    """Return one clinic-scoped invoice after the feature gate."""

    ensure_billing_enabled(db, actor.clinic_id)
    invoice = db.scalar(
        select(Invoice)
        .options(*_invoice_options())
        .where(
            Invoice.id == invoice_id,
            Invoice.clinic_id == actor.clinic_id,
        )
    )
    if invoice is None:
        raise ValueError("Invoice not found in this clinic.")
    return invoice


def get_invoices(
    db: Session,
    actor: User,
    *,
    patient_id: int | None = None,
) -> list[Invoice]:
    """Return active clinic invoices, optionally narrowed to a patient."""

    ensure_billing_enabled(db, actor.clinic_id)
    conditions = [Invoice.clinic_id == actor.clinic_id]
    if patient_id is not None:
        conditions.append(Invoice.patient_id == patient_id)
    return list(
        db.scalars(
            select(Invoice)
            .options(*_invoice_options())
            .where(*conditions)
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    )


def set_invoice_status(
    db: Session,
    actor: User,
    invoice_id: int,
    status: InvoiceStatus | str,
) -> Invoice:
    """Mark an invoice paid or unpaid and audit the transition."""

    ensure_billing_enabled(db, actor.clinic_id)
    if not billing_role_allowed(actor):
        raise PermissionError("Only billing clerks and clinic administrators may update invoices.")
    invoice = get_invoice_for_user(db, actor, invoice_id)
    try:
        new_status = (
            status
            if isinstance(status, InvoiceStatus)
            else InvoiceStatus(str(status).lower())
        )
    except ValueError as error:
        raise ValueError("Invoice status must be paid or unpaid.") from error
    previous = invoice.status
    invoice.status = new_status
    record_audit_event(
        db,
        actor.id,
        AuditAction.UPDATE,
        "invoice",
        invoice.id,
        details={"status_from": previous.value, "status_to": new_status.value},
    )
    return invoice


def get_patient_invoices(
    db: Session,
    actor: User,
    patient_id: int,
) -> list[Invoice]:
    """Return active invoices for a patient after the Billing gate."""

    return get_invoices(db, actor, patient_id=patient_id)


def soft_delete_invoice(db: Session, actor: User, invoice: Invoice) -> None:
    """Soft-delete an invoice without removing financial history."""

    ensure_billing_enabled(db, actor.clinic_id)
    ensure_clinic_admin(actor)
    if invoice.clinic_id != actor.clinic_id:
        raise PermissionError("The invoice does not belong to this clinic.")
    soft_delete_record(db, invoice, actor, "invoice", invoice.id)