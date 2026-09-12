"""Automated query, RBAC, boundary, soft-delete, and export coverage for Reporting."""

from datetime import date, datetime, time
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Appointment,
    AppointmentStatus,
    AppointmentType,
    Clinic,
    DeliveryOutcome,
    Invoice,
    Patient,
    PregnancyEpisode,
    PregnancyEpisodeStatus,
    User,
    UserRole,
    Visit,
    VisitType,
)
from app.services.billing import create_invoice, ensure_default_fee_schedule
from app.services.clinical import create_delivery_outcome, create_pregnancy_episode
from app.services.patients import create_patient
from app.services.reporting import (
    active_pregnancies_by_trimester,
    available_reports,
    daily_schedule_census,
    delivery_outcomes_log,
    export_pdf,
    export_xlsx,
    no_show_rate,
    patients_due_for_screening,
    revenue_summary,
)

REPORT_START = date(2026, 9, 12)
REPORT_END = date(2026, 9, 12)


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a test client as one seeded staff user."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def make_patient(db: Session, user: User, name: str) -> Patient:
    """Create one active patient with the minimum demographic payload."""

    return create_patient(
        db=db,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": name,
            "date_of_birth": date(1990, 2, 3),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )


def make_visit(
    db: Session,
    user: User,
    patient: Patient,
    visit_date: date,
    *,
    gyn_data: dict | None = None,
) -> Visit:
    """Create a structured visit with optional screening due-date fields."""

    visit = Visit(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        visit_type=VisitType.GYN_ANNUAL,
        visit_date=visit_date,
        vitals={},
        prenatal_data={},
        gyn_data=gyn_data or {},
        hpi="",
        assessment="",
        plan="",
    )
    db.add(visit)
    db.flush()
    return visit


def make_appointment(
    db: Session,
    user: User,
    patient: Patient,
    appointment_type: AppointmentType,
    scheduled_at: datetime,
    status: AppointmentStatus,
) -> Appointment:
    """Create an appointment for boundary and status-mix checks."""

    appointment = Appointment(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        doctor_id=user.id,
        scheduled_at=scheduled_at,
        duration_minutes=30,
        appointment_type_id=appointment_type.id,
        status=status,
    )
    db.add(appointment)
    db.flush()
    return appointment


def enable_billing(db: Session, user: User) -> None:
    """Enable Billing for financial-report setup."""

    clinic = db.scalar(select(Clinic).where(Clinic.id == user.clinic_id))
    assert clinic is not None
    clinic.billing_module_enabled = True
    db.commit()


def test_schedule_and_no_show_use_inclusive_boundaries_and_exclude_deleted_rows(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """End-of-day appointments count; cancelled/deleted records do not skew rate."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient = make_patient(db_session, admin, "Schedule Patient")
    appointment_type = AppointmentType(
        clinic_id=admin.clinic_id,
        name="Report visit",
        default_duration_minutes=30,
    )
    db_session.add(appointment_type)
    db_session.flush()
    make_appointment(
        db_session,
        admin,
        patient,
        appointment_type,
        datetime.combine(REPORT_END, time(23, 59)),
        AppointmentStatus.NO_SHOW,
    )
    make_appointment(
        db_session,
        admin,
        patient,
        appointment_type,
        datetime.combine(REPORT_START, time(9, 0)),
        AppointmentStatus.CANCELLED,
    )
    deleted = make_appointment(
        db_session,
        admin,
        patient,
        appointment_type,
        datetime.combine(REPORT_START, time(10, 0)),
        AppointmentStatus.DONE,
    )
    deleted.soft_delete(admin.id)
    db_session.commit()

    schedule = daily_schedule_census(
        db_session,
        admin,
        REPORT_START,
        REPORT_END,
    )
    no_show = no_show_rate(db_session, admin, REPORT_START, REPORT_END)
    assert schedule["total_appointments"] == 2
    assert schedule["days"][0]["status_counts"]["no_show"] == 1
    assert schedule["days"][0]["status_counts"]["cancelled"] == 1
    assert no_show["total_appointments"] == 2
    assert no_show["cancelled_count"] == 1
    assert no_show["eligible_count"] == 1
    assert no_show["no_show_count"] == 1
    assert no_show["rate_percent"] == Decimal("100.00")


def test_reports_are_role_filtered_and_revenue_requires_enabled_billing(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Financial reports are restricted, while clinical reports stay private."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    assert {report["slug"] for report in available_reports(db_session, admin)} == {
        "schedule",
        "no-show-rate",
        "screening",
        "pregnancies",
        "deliveries",
    }
    login_as(client, seeded_users[UserRole.PHYSICIAN])
    assert client.get("/reports/revenue").status_code == 403
    assert client.get("/reports/screening").status_code == 200
    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    assert client.get("/reports/screening").status_code == 403
    assert client.get("/reports/revenue").status_code == 404

    clinic = db_session.scalar(select(Clinic).where(Clinic.id == admin.clinic_id))
    assert clinic is not None
    clinic.billing_module_enabled = True
    db_session.commit()
    assert client.get("/reports/revenue").status_code == 200
    xlsx = client.get(
        "/reports/revenue/export/xlsx?start_date=2026-09-12&end_date=2026-09-12"
    )
    pdf = client.get(
        "/reports/revenue/export/pdf?start_date=2026-09-12&end_date=2026-09-12"
    )
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"


def test_screening_pregnancy_and_delivery_reports_are_hand_countable(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Clinical reports use the documented date and trimester rules."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = make_patient(db_session, physician, "Clinical Report Patient")
    make_visit(
        db_session,
        physician,
        patient,
        REPORT_END,
        gyn_data={
            "pap_due_date": "2026-09-12",
            "hpv_due_date": "2026-12-01",
        },
    )
    episode = create_pregnancy_episode(
        db_session,
        physician,
        patient.id,
        lmp=date(2026, 6, 1),
        edd=date(2027, 3, 8),
    )
    db_session.flush()
    create_delivery_outcome(
        db_session,
        episode,
        physician,
        date(2026, 9, 12),
        "vaginal",
        "None",
        3200,
        8,
        9,
    )
    create_pregnancy_episode(
        db_session,
        physician,
        patient.id,
        lmp=date(2026, 6, 1),
        edd=date(2027, 3, 8),
    )
    db_session.commit()

    screening = patients_due_for_screening(
        db_session,
        physician,
        REPORT_START,
        REPORT_END,
    )
    pregnancies = active_pregnancies_by_trimester(
        db_session,
        physician,
        REPORT_START,
        REPORT_END,
    )
    deliveries = delivery_outcomes_log(
        db_session,
        physician,
        REPORT_START,
        REPORT_END,
    )
    assert screening["patient_count"] == 1
    assert screening["rows"][0]["overdue"] == "Pap"
    assert pregnancies["total"] == 1
    assert pregnancies["counts"]["second"] == 1
    assert pregnancies["rows"][0]["gestational_age"] == "14w 5d"
    assert deliveries["count"] == 1
    assert deliveries["rows"][0]["mode"] == "vaginal"


def test_revenue_is_inclusive_and_excludes_soft_deleted_financial_records(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Revenue totals use invoice snapshots and omit a deleted invoice."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    enable_billing(db_session, admin)
    patient = make_patient(db_session, admin, "Revenue Patient")
    visit = make_visit(db_session, admin, patient, REPORT_END)
    fee = ensure_default_fee_schedule(db_session, admin.clinic_id)[0]
    db_session.commit()
    invoice = create_invoice(db_session, admin, visit.id, [fee.id])
    invoice.created_at = datetime.combine(REPORT_END, time(23, 59))
    db_session.commit()

    report = revenue_summary(db_session, admin, REPORT_START, REPORT_END)
    assert report["invoice_count"] == 1
    assert report["gross_total"] == Decimal("150.00")
    invoice.soft_delete(admin.id)
    db_session.commit()
    assert revenue_summary(
        db_session,
        admin,
        REPORT_START,
        REPORT_END,
    )["invoice_count"] == 0


def test_pdf_and_excel_exports_are_real_downloads(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Export helpers produce parseable XLSX and a valid PDF signature."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient = make_patient(db_session, admin, "Export Patient")
    make_visit(
        db_session,
        admin,
        patient,
        REPORT_END,
        gyn_data={"pap_due_date": "2026-09-01"},
    )
    db_session.commit()
    report = patients_due_for_screening(
        db_session,
        admin,
        REPORT_START,
        REPORT_END,
    )
    workbook_response = export_xlsx(report)
    workbook = load_workbook(filename=__import__("io").BytesIO(workbook_response.body))
    assert workbook.active["A1"].value == "Patients due for screening"
    assert workbook.active["A4"].value == "Patient ID"
    pdf_response = export_pdf(report)
    assert pdf_response.body.startswith(b"%PDF-")
    assert pdf_response.headers["content-disposition"].endswith('"screening.pdf"')