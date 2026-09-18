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
        data={"username": user.username, "password": "Valid-Test-Password1"},
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


def enabled_invoice_context(
    db: Session,
    clinic_admin: User,
) -> tuple[Patient, Visit, FeeScheduleItem, Invoice]:
    """Create one enabled clinic invoice for focused Prompt 9.T checks."""

    enable_billing(db, clinic_admin)
    patient, visit = seed_patient_and_visit(db, clinic_admin)
    fee = ensure_default_fee_schedule(db, clinic_admin.clinic_id)[0]
    db.commit()
    invoice = create_invoice(db, clinic_admin, visit.id, [fee.id])
    db.commit()
    return patient, visit, fee, invoice


def test_45_disabled_billing_blocks_all_operational_routes_and_hides_ui(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Disabled Billing is blocked at every route boundary and in the UI."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient, visit = seed_patient_and_visit(db_session, clinic_admin)
    login_as(client, clinic_admin)

    requests = (
        ("get", "/billing", {}),
        ("get", f"/visits/{visit.id}/billing/charge-panel", {}),
        (
            "post",
            f"/visits/{visit.id}/billing/invoices",
            {"fee_schedule_item_id": "999", "notes": ""},
        ),
        ("post", "/billing/invoices/999/status", {"status": "paid"}),
        ("get", "/billing/invoices/999/print", {}),
        ("get", "/admin/billing", {}),
        (
            "post",
            "/admin/billing/fees",
            {"name": "Blocked fee", "description": "", "unit_price": "10.00"},
        ),
        (
            "post",
            "/admin/billing/fees/999",
            {
                "name": "Blocked fee",
                "description": "",
                "unit_price": "10.00",
                "active": "true",
            },
        ),
    )
    for method, path, data in requests:
        response = (
            client.get(path)
            if method == "get"
            else client.post(path, data=data)
        )
        assert response.status_code == 404, (method, path, response.text)
        assert "Billing is not available" in response.text

    patient_list = client.get("/patients")
    patient_chart = client.get(f"/patients/{patient.id}")
    assert patient_list.status_code == 200
    assert patient_chart.status_code == 200
    assert 'href="/billing"' not in patient_list.text
    assert ">Billing<" not in patient_list.text
    assert ">Billing<" not in patient_chart.text


def test_46_disabled_billing_excludes_financial_reports_from_available_surfaces(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """No Reporting surface or financial report names are exposed when off.

    The current application has not introduced a Reporting section yet. This
    guards the existing contract so a future report list cannot accidentally
    expose revenue/financial options while Billing is disabled.
    """

    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])
    for path in ("/reports", "/reporting"):
        response = client.get(path)
        assert response.status_code in (200, 404)
        assert "Revenue" not in response.text
        assert "Financial" not in response.text
    reports = client.get("/reports")
    assert reports.status_code == 200
    assert "Revenue summary" not in reports.text
    assert "Financial" not in reports.text


def test_47_enabling_billing_is_immediate_and_preserves_patient_visit_data(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """The feature toggle takes effect without restart or data loss."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient, visit = seed_patient_and_visit(db_session, clinic_admin)
    login_as(client, clinic_admin)
    toggle_response = client.post(
        "/admin/clinic-features/billing",
        data={"enabled": "true"},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 303
    assert client.get("/billing").status_code == 200
    assert ">Billing<" in client.get(f"/patients/{patient.id}").text

    retained_patient = db_session.scalar(select(Patient).where(Patient.id == patient.id))
    retained_visit = db_session.scalar(select(Visit).where(Visit.id == visit.id))
    assert retained_patient is not None
    assert retained_patient.name == "Billing Patient"
    assert retained_visit is not None
    assert retained_visit.patient_id == patient.id


def test_49_billing_clerk_gets_graceful_disabled_response(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """A disabled billing clerk screen is a useful 404, not a blank error."""

    _, visit = seed_patient_and_visit(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
    )
    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    for path in (
        "/billing",
        f"/visits/{visit.id}/billing/charge-panel",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert "Billing is not available" in response.text

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


def test_88_enabled_charge_uses_the_clinic_fee_schedule_amount(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 88: a visit charge uses the selected fee schedule amount."""

    _, visit, fee, invoice = enabled_invoice_context(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
    )
    assert invoice.visit_id == visit.id
    assert invoice.charges[0].fee_schedule_item_id == fee.id
    assert invoice.charges[0].total_amount == fee.unit_price
    assert invoice.total_amount == fee.unit_price


def test_89_paid_invoice_updates_and_appears_as_paid(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 89: paid state persists and appears in the Billing ledger."""

    _, _, _, invoice = enabled_invoice_context(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
    )
    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    response = client.post(
        f"/billing/invoices/{invoice.id}/status",
        data={"status": "paid"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.PAID
    dashboard = client.get("/billing")
    assert dashboard.status_code == 200
    assert f"#{invoice.id}" in dashboard.text
    assert "paid" in dashboard.text.lower()


def test_90_printed_invoice_contains_branding_and_itemization(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 90: printed output contains clinic branding and line details."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    _, _, fee, invoice = enabled_invoice_context(db_session, clinic_admin)
    clinic = db_session.scalar(select(Clinic).where(Clinic.id == clinic_admin.clinic_id))
    assert clinic is not None
    clinic.branding_reference = "/static/test-clinic-logo.svg"
    db_session.commit()

    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    response = client.get(f"/billing/invoices/{invoice.id}/print")
    assert response.status_code == 200
    assert "Test Clinic" in response.text
    assert "/static/test-clinic-logo.svg" in response.text
    assert f"Invoice #{invoice.id}" in response.text
    assert fee.name in response.text
    assert fee.description in response.text
    assert "$150.00" in response.text
    assert "Unpaid" in response.text


def test_91_fee_schedule_edits_are_not_retroactive(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 91: editing a fee leaves an existing invoice amount unchanged."""

    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    _, _, fee, invoice = enabled_invoice_context(db_session, clinic_admin)
    original_amount = invoice.total_amount
    login_as(client, clinic_admin)
    response = client.post(
        f"/admin/billing/fees/{fee.id}",
        data={
            "name": fee.name,
            "description": "Updated future description",
            "unit_price": "999.00",
            "active": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(fee)
    db_session.refresh(invoice)
    assert fee.unit_price == Decimal("999.00")
    assert invoice.total_amount == original_amount
    assert invoice.charges[0].total_amount == original_amount


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


def test_48_disabling_billing_retains_history_and_reenabling_restores_access(
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