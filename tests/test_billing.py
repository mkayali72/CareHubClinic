"""Automated coverage for the optional Billing module."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditAction,
    AuditLog,
    Clinic,
    FeeScheduleItem,
    Invoice,
    InvoiceStatus,
    Patient,
    User,
    UserRole,
    Visit,
    VisitType,
)
from app.services.billing import (
    create_invoice,
    ensure_default_fee_schedule,
    get_fee_schedule,
    set_invoice_status,
)
from app.services.patients import create_patient


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a test client as one seeded staff user."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient_and_visit(db: Session, user: User) -> tuple[Patient, Visit]:
    """Create the minimum patient and visit context for an invoice."""

    patient = create_patient(
        db=db,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": "Billing Patient",
            "date_of_birth": date(1990, 2, 3),
            "contact_info": {"phone": "+974 5000 0100"},
            "insurance_info": {"provider": "Test Payer"},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    visit = Visit(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        visit_type=VisitType.PROBLEM_FOCUSED,
        visit_date=date(2026, 9, 12),
        vitals={},
        prenatal_data={},
        gyn_data={},
        hpi="",
        assessment="",
        plan="",
    )
    db.add(visit)
    db.commit()
    return patient, visit


def enable_billing(db: Session, user: User) -> None:
    """Enable the optional module for service-level test setup."""

    clinic = db.scalar(select(Clinic).where(Clinic.id == user.clinic_id))
    assert clinic is not None
    clinic.billing_module_enabled = True
    db.commit()


def test_disabled_billing_returns_not_found_but_feature_settings_remain_accessible(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """A disabled clerk route is a graceful 404, while admin can re-enable it."""

    billing_clerk = seeded_users[UserRole.BILLING_CLERK]
    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]

    login_as(client, billing_clerk)
    response = client.get("/billing")
    assert response.status_code == 404
    assert "Billing is not available" in response.text

    login_as(client, clinic_admin)
    settings_response = client.get("/admin/clinic-features")
    assert settings_response.status_code == 200
    assert "Billing module" in settings_response.text
    toggle_response = client.post(
        "/admin/clinic-features/billing",
        data={"enabled": "true"},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 303
    assert client.get("/billing").status_code == 200


def test_billing_permissions_and_fee_schedule_editor(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Only billing clerks and clinic admins operate Billing; admins edit fees."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    enable_billing(db_session, clinic_admin)

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    assert client.get("/billing").status_code == 403

    login_as(client, clinic_admin)
    admin_page = client.get("/admin/billing")
    assert admin_page.status_code == 200
    response = client.post(
        "/admin/billing/fees",
        data={
            "name": "Postpartum follow-up",
            "description": "Six-week follow-up",
            "unit_price": "90.00",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    item = db_session.scalar(
        select(FeeScheduleItem).where(FeeScheduleItem.name == "Postpartum follow-up")
    )
    assert item is not None
    assert item.unit_price == Decimal("90.00")

    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    assert client.get("/admin/billing").status_code == 403
    assert client.get("/billing").status_code == 200


def test_charges_snapshot_fees_and_paid_state_is_audited(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Invoice lines retain their original price while payment state changes."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    enable_billing(db_session, clinic_admin)
    patient, visit = seed_patient_and_visit(db_session, clinic_admin)
    items = ensure_default_fee_schedule(db_session, clinic_admin.clinic_id)
    db_session.commit()
    fee = items[0]

    billing_clerk = seeded_users[UserRole.BILLING_CLERK]
    invoice = create_invoice(
        db_session,
        billing_clerk,
        visit.id,
        [fee.id],
        "Collected at front desk",
    )
    db_session.commit()
    assert invoice.status is InvoiceStatus.UNPAID
    assert invoice.charges[0].total_amount == fee.unit_price

    fee.unit_price = Decimal("999.00")
    db_session.commit()
    assert invoice.charges[0].total_amount != fee.unit_price
    assert invoice.charges[0].total_amount == Decimal("150.00")

    set_invoice_status(db_session, billing_clerk, invoice.id, InvoiceStatus.PAID)
    db_session.commit()
    assert invoice.status is InvoiceStatus.PAID
    audit = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "invoice",
            AuditLog.entity_id == invoice.id,
            AuditLog.action == AuditAction.UPDATE,
        )
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.details["status_to"] == "paid"

    login_as(client, billing_clerk)
    patient_billing = client.get(f"/patients/{patient.id}?tab=billing")
    assert patient_billing.status_code == 200
    assert "Enter charges" in patient_billing.text
    assert f"Visit #{visit.id}" in patient_billing.text
    print_response = client.get(f"/billing/invoices/{invoice.id}/print")
    assert print_response.status_code == 200
    assert "Test Clinic" in print_response.text
    assert "Invoice #" + str(invoice.id) in print_response.text
    assert "Print / Save as PDF" in print_response.text


def test_disabling_billing_retains_history_and_reenabling_restores_access(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Turning the module off pauses operations without deleting invoices."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    enable_billing(db_session, clinic_admin)
    _, visit = seed_patient_and_visit(db_session, clinic_admin)
    fee = get_fee_schedule(db_session, clinic_admin)[0]
    invoice = create_invoice(db_session, clinic_admin, visit.id, [fee.id])
    db_session.commit()

    login_as(client, clinic_admin)
    disable_response = client.post(
        "/admin/clinic-features/billing",
        data={},
        follow_redirects=False,
    )
    assert disable_response.status_code == 303
    assert client.get("/billing").status_code == 404
    assert client.get(f"/billing/invoices/{invoice.id}/print").status_code == 404
    retained = db_session.scalar(select(Invoice).where(Invoice.id == invoice.id))
    assert retained is not None
    assert retained.deleted_at is None

    client.post(
        "/admin/clinic-features/billing",
        data={"enabled": "true"},
        follow_redirects=False,
    )
    assert client.get("/billing").status_code == 200
    assert f"#{invoice.id}" in client.get("/billing").text