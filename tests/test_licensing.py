"""Automated licensing enforcement, scheduler, and draft-preservation coverage."""

from datetime import date, datetime, timedelta, timezone
import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppointmentType,
    Clinic,
    License,
    LicenseStatus,
    MedicationDefinition,
    Patient,
    User,
    UserRole,
    Visit,
    VisitType,
)
from app.services.auth import create_user
from app.services.billing import ensure_default_fee_schedule
from app.services.clinical import create_visit
from app.services.labs import ensure_default_lab_test_definitions
from app.services.patients import create_patient
from app.services.prescriptions import create_medication_definition
from app.services.licensing import (
    ensure_license,
    evaluate_license,
    refresh_license_statuses,
    utc_now,
)


def login_as(client: TestClient, user: User) -> None:
    """Authenticate one seeded user through the real login route."""

    response = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def set_license(
    db: Session,
    user: User,
    *,
    expires_at: datetime,
    grace_period_days: int = 7,
    status: LicenseStatus = LicenseStatus.ACTIVE,
) -> License:
    """Configure a test license directly, as the admin screen would."""

    license_record = ensure_license(db, user.clinic_id)
    license_record.expires_at = expires_at
    license_record.grace_period_days = grace_period_days
    license_record.status = status
    db.commit()
    return license_record


def seed_cross_module_context(
    db: Session,
    admin: User,
) -> dict[str, object]:
    """Create the shared patient, visit, lab, medication, and billing context."""

    patient = create_patient(
        db=db,
        clinic_id=admin.clinic_id,
        actor=admin,
        payload={
            "name": "Licensing Matrix Patient",
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    visit = create_visit(
        db,
        admin,
        patient.id,
        VisitType.PROBLEM_FOCUSED,
        None,
        {},
        None,
        None,
        "Licensing test HPI",
        "Licensing test assessment",
        "Licensing test plan",
        [],
    )
    lab_definition = ensure_default_lab_test_definitions(db, admin.clinic_id)[0]
    medication = create_medication_definition(
        db,
        admin,
        "Licensing test medication",
        "Safe test medication",
        "unknown",
        "test",
    )
    clinic = db.scalar(select(Clinic).where(Clinic.id == admin.clinic_id))
    assert clinic is not None
    clinic.billing_module_enabled = True
    fee = ensure_default_fee_schedule(db, admin.clinic_id)[0]
    db.commit()
    return {
        "clinic": clinic,
        "patient": patient,
        "visit": visit,
        "lab_definition": lab_definition,
        "medication": medication,
        "fee": fee,
    }


def test_license_evaluation_honors_expiry_grace_and_revocation_boundaries(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The local evaluator has exact active, grace, expired, and revoked states."""

    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    license_record = License(
        clinic_id=seeded_users[UserRole.CLINIC_ADMIN].clinic_id,
        expires_at=now,
        grace_period_days=2,
        status=LicenseStatus.ACTIVE,
    )
    db_session.add(license_record)
    db_session.flush()
    assert evaluate_license(license_record, now=now).status is LicenseStatus.ACTIVE
    assert (
        evaluate_license(
            license_record,
            now=now + timedelta(seconds=1),
        ).status
        is LicenseStatus.GRACE
    )
    assert (
        evaluate_license(
            license_record,
            now=now + timedelta(days=2),
        ).status
        is LicenseStatus.GRACE
    )
    assert (
        evaluate_license(
            license_record,
            now=now + timedelta(days=2, seconds=1),
        ).status
        is LicenseStatus.EXPIRED
    )
    license_record.status = LicenseStatus.REVOKED
    assert evaluate_license(license_record, now=now).status is LicenseStatus.REVOKED


def test_expired_license_allows_reads_but_blocks_writes_on_stale_session(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """A session authenticated before expiry cannot keep mutating records."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=2),
        grace_period_days=1,
    )
    login_as(client, admin)

    read_response = client.get("/schedule")
    write_response = client.post(
        "/schedule/types",
        data={"name": "Blocked type", "default_duration_minutes": "30"},
    )
    assert read_response.status_code == 200
    assert write_response.status_code == 423
    assert "read-only" in write_response.text.lower()
    assert db_session.scalar(
        select(License).where(License.clinic_id == admin.clinic_id)
    ).status is LicenseStatus.ACTIVE


def test_grace_period_blocks_htmx_write_without_replacing_form_state(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """HTMX writes receive a no-swap response so the submitted form remains."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(hours=1),
        grace_period_days=3,
    )
    login_as(client, admin)
    response = client.post(
        "/schedule/types",
        data={"name": "Blocked HTMX type", "default_duration_minutes": "30"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 423
    assert response.headers["HX-Reswap"] == "none"
    assert "license-write-blocked" in response.headers["HX-Trigger"]
    assert "grace period" in response.text.lower()


def test_clinic_admin_can_renew_from_read_only_state_and_writes_resume(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The renewal screen remains writable so an expired clinic can recover."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=10),
        grace_period_days=2,
    )
    login_as(client, admin)
    renewal = client.post(
        "/admin/license",
        data={
            "expires_at": (utc_now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M"),
            "grace_period_days": "7",
            "status": "active",
        },
        follow_redirects=False,
    )
    assert renewal.status_code == 303
    assert client.post(
        "/schedule/types",
        data={"name": "Renewed type", "default_duration_minutes": "30"},
        follow_redirects=False,
    ).status_code == 303


def test_scheduler_updates_status_and_last_check_in_timestamp(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The in-process check-in persists derived status and check-in time."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    check_time = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    license_record = set_license(
        db_session,
        admin,
        expires_at=check_time - timedelta(days=1),
        grace_period_days=0,
    )
    assert refresh_license_statuses(db_session, now=check_time) == 1
    db_session.refresh(license_record)
    assert license_record.status is LicenseStatus.EXPIRED
    assert license_record.last_check_in_at.replace(tzinfo=timezone.utc) == check_time


def test_read_only_banner_license_bell_and_visit_draft_protection_are_visible(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The shell warns users and the visit workspace includes local draft safety."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    physician = seeded_users[UserRole.PHYSICIAN]
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=10),
        grace_period_days=2,
    )
    patient = Patient(
        clinic_id=admin.clinic_id,
        name="Draft Preservation Patient",
        date_of_birth=datetime(1990, 1, 1).date(),
        contact_info={},
        insurance_info={},
        emergency_contact={},
        allergies=[],
        current_medications=[],
        contraception_method=None,
    )
    db_session.add(patient)
    db_session.commit()
    login_as(client, physician)

    workspace = client.get(f"/visits/patients/{patient.id}")
    assert workspace.status_code == 200
    assert "Workspace temporarily read-only" in workspace.text
    assert "localStorage" in workspace.text
    assert "visit-note-form" in workspace.text

    login_as(client, admin)
    welcome = client.get("/welcome")
    assert welcome.status_code == 200
    assert "/admin/license" in welcome.text


def test_26_valid_license_allows_read_write_access_across_all_modules(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """A valid license preserves representative writes and reads everywhere."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    context = seed_cross_module_context(db_session, admin)
    set_license(db_session, admin, expires_at=utc_now() + timedelta(days=30))
    login_as(client, admin)

    patient_write = client.post(
        "/patients",
        data={"name": "License-valid patient", "date_of_birth": "1991-02-03"},
    )
    assert patient_write.status_code == 200
    created_patient = db_session.scalar(
        select(Patient).where(Patient.name == "License-valid patient")
    )
    assert created_patient is not None

    appointment_type_write = client.post(
        "/schedule/types",
        data={"name": "License-valid appointment", "default_duration_minutes": "30"},
        follow_redirects=False,
    )
    assert appointment_type_write.status_code == 303
    appointment_type = db_session.scalar(
        select(AppointmentType).where(
            AppointmentType.name == "License-valid appointment"
        )
    )
    assert appointment_type is not None

    appointment_write = client.post(
        "/schedule/appointments",
        data={
            "patient_id": created_patient.id,
            "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
            "appointment_type_id": appointment_type.id,
            "scheduled_at": "2026-09-12T10:00",
            "duration_minutes": "30",
        },
        follow_redirects=False,
    )
    assert appointment_write.status_code == 303

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    visit_write = client.post(
        "/visits",
        data={
            "patient_id": context["patient"].id,
            "visit_type": VisitType.PROBLEM_FOCUSED.value,
            "hpi": "New valid-license note",
            "assessment": "Stable",
            "plan": "Follow up",
        },
        follow_redirects=False,
    )
    assert visit_write.status_code == 303
    visit = db_session.scalar(
        select(Visit)
        .where(Visit.patient_id == context["patient"].id)
        .order_by(Visit.id.desc())
    )
    assert visit is not None

    lab_write = client.post(
        f"/visits/{visit.id}/labs/orders",
        data={"definition_ids": str(context["lab_definition"].id)},
    )
    assert lab_write.status_code == 200
    prescription_write = client.post(
        f"/visits/{visit.id}/prescriptions",
        data={
            "medication_definition_id": str(context["medication"].id),
            "dosage": "1 tablet",
            "frequency": "daily",
            "duration": "30 days",
        },
    )
    assert prescription_write.status_code == 200
    login_as(client, admin)
    billing_write = client.post(
        f"/visits/{visit.id}/billing/invoices",
        data={"fee_schedule_item_id": str(context["fee"].id), "notes": "Valid"},
    )
    assert billing_write.status_code == 200

    for path in (
        "/patients",
        "/schedule",
        f"/visits/{visit.id}",
        f"/visits/{visit.id}/labs/order-panel",
        f"/visits/{visit.id}/prescriptions/order-panel",
        "/billing",
    ):
        assert client.get(path).status_code == 200, path


def test_27_grace_period_keeps_reads_available_and_blocks_writes_across_modules(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Grace state downgrades patients, scheduling, clinical, labs, prescriptions, and billing."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    context = seed_cross_module_context(db_session, admin)
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(hours=1),
        grace_period_days=3,
    )
    login_as(client, admin)

    read_paths = (
        "/patients",
        "/schedule",
        f"/visits/{context['visit'].id}",
        f"/visits/{context['visit'].id}/labs/order-panel",
        f"/visits/{context['visit'].id}/prescriptions/order-panel",
        "/billing",
    )
    for path in read_paths:
        assert client.get(path).status_code == 200, path

    write_requests = (
        (
            "/patients",
            {"name": "Blocked patient", "date_of_birth": "1991-02-03"},
        ),
        (
            "/schedule/types",
            {"name": "Blocked appointment", "default_duration_minutes": "30"},
        ),
        (
            "/visits",
            {
                "patient_id": context["patient"].id,
                "visit_type": VisitType.PROBLEM_FOCUSED.value,
            },
        ),
        (
            f"/visits/{context['visit'].id}/labs/orders",
            {"definition_ids": str(context["lab_definition"].id)},
        ),
        (
            f"/visits/{context['visit'].id}/prescriptions",
            {"medication_definition_id": str(context["medication"].id)},
        ),
        (
            f"/visits/{context['visit'].id}/billing/invoices",
            {"fee_schedule_item_id": str(context["fee"].id)},
        ),
    )
    for path, data in write_requests:
        response = client.post(path, data=data)
        assert response.status_code == 423, (path, response.text)


def test_28_license_boundary_rejects_past_grace_and_allows_active_side_write(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The exact grace boundary is expired; the active side still permits writes."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    now = utc_now()
    license_record = set_license(
        db_session,
        admin,
        expires_at=now + timedelta(seconds=10),
        grace_period_days=2,
    )
    assert evaluate_license(
        license_record,
        now=license_record.expires_at + timedelta(days=2),
    ).status is LicenseStatus.GRACE
    assert evaluate_license(
        license_record,
        now=license_record.expires_at + timedelta(days=2, seconds=1),
    ).status is LicenseStatus.EXPIRED
    login_as(client, admin)

    active_side = client.post(
        "/schedule/types",
        data={"name": "Boundary active write", "default_duration_minutes": "30"},
        follow_redirects=False,
    )
    assert active_side.status_code == 303

    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=2, seconds=10),
        grace_period_days=2,
    )
    past_grace = client.post(
        "/schedule/types",
        data={"name": "Boundary expired write", "default_duration_minutes": "30"},
    )
    assert past_grace.status_code == 423

    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=2) + timedelta(seconds=10),
        grace_period_days=2,
    )
    inside_grace = client.post(
        "/schedule/types",
        data={"name": "Boundary grace write", "default_duration_minutes": "30"},
    )
    assert inside_grace.status_code == 423


def test_29_renewal_resumes_write_access_without_restart(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Renewal changes the server decision immediately for an existing session."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=10),
        grace_period_days=2,
    )
    login_as(client, admin)
    blocked = client.post(
        "/schedule/types",
        data={"name": "Before renewal", "default_duration_minutes": "30"},
    )
    assert blocked.status_code == 423

    renewal = client.post(
        "/admin/license",
        data={
            "expires_at": (utc_now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M"),
            "grace_period_days": "7",
            "status": "active",
        },
        follow_redirects=False,
    )
    assert renewal.status_code == 303
    resumed = client.post(
        "/schedule/types",
        data={"name": "After renewal", "default_duration_minutes": "30"},
        follow_redirects=False,
    )
    assert resumed.status_code == 303


def test_30_unsaved_visit_note_preservation_is_present_when_license_transitions(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The workspace ships the local draft mechanism and no-swap blocked response."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    context = seed_cross_module_context(db_session, admin)
    set_license(db_session, admin, expires_at=utc_now() + timedelta(days=30))
    login_as(client, admin)
    workspace = client.get(f"/visits/patients/{context['patient'].id}")
    assert workspace.status_code == 200
    assert 'data-draft-key="patient-' in workspace.text
    assert "localStorage.setItem" in workspace.text
    assert "localStorage.getItem" in workspace.text
    assert "FormData(form)" in workspace.text

    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=10),
        grace_period_days=2,
    )
    blocked = client.post(
        "/visits",
        data={
            "patient_id": context["patient"].id,
            "visit_type": VisitType.PROBLEM_FOCUSED.value,
            "hpi": "Unsaved content that must survive",
            "assessment": "Draft assessment",
            "plan": "Draft plan",
        },
        headers={"HX-Request": "true"},
    )
    assert blocked.status_code == 423
    assert blocked.headers["HX-Reswap"] == "none"
    assert db_session.scalar(
        select(Visit).where(Visit.hpi == "Unsaved content that must survive")
    ) is None


def test_31_admin_license_status_days_remaining_matches_database_after_renewal(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The status view reflects persisted expiration before and after renewal."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(db_session, admin, expires_at=utc_now() + timedelta(days=12))
    login_as(client, admin)
    initial = client.get("/admin/license")
    assert initial.status_code == 200
    record = db_session.scalar(select(License).where(License.clinic_id == admin.clinic_id))
    assert record is not None
    initial_snapshot = evaluate_license(record)
    initial_match = re.search(
        r"Days remaining</dt>\s*<dd[^>]*>\s*(\d+)",
        initial.text,
        re.DOTALL,
    )
    assert initial_match is not None
    assert int(initial_match.group(1)) == initial_snapshot.days_remaining

    renewal = client.post(
        "/admin/license",
        data={
            "expires_at": (utc_now() + timedelta(days=45)).strftime("%Y-%m-%dT%H:%M"),
            "grace_period_days": "7",
            "status": "active",
        },
        follow_redirects=False,
    )
    assert renewal.status_code == 303
    after = client.get("/admin/license")
    record = db_session.scalar(select(License).where(License.clinic_id == admin.clinic_id))
    assert record is not None
    after_snapshot = evaluate_license(record)
    after_match = re.search(
        r"Days remaining</dt>\s*<dd[^>]*>\s*(\d+)",
        after.text,
        re.DOTALL,
    )
    assert after_match is not None
    assert int(after_match.group(1)) == after_snapshot.days_remaining
    assert record.expires_at.strftime("%Y-%m-%d") in after.text


def test_32_stale_client_claiming_active_license_cannot_write(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """A client-side active claim cannot override the expired server record."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(db_session, admin, expires_at=utc_now() + timedelta(days=30))
    login_as(client, admin)
    set_license(
        db_session,
        admin,
        expires_at=utc_now() - timedelta(days=10),
        grace_period_days=2,
    )
    response = client.post(
        "/schedule/types",
        data={"name": "Stale client write", "default_duration_minutes": "30"},
        headers={"X-License-State": "active", "X-Client-License-Status": "active"},
    )
    assert response.status_code == 423
    assert "read-only" in response.text.lower()


def test_33_new_physician_is_allowed_because_no_seat_count_rule_is_implemented(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The implemented behavior has no licensed physician-count restriction."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    set_license(db_session, admin, expires_at=utc_now() + timedelta(days=30))
    physician = create_user(
        db_session,
        admin.clinic_id,
        "additional_phys",
        "Valid-Test-Password1",
        "Additional Physician",
        UserRole.PHYSICIAN,
        actor=admin,
    )
    db_session.commit()
    assert physician.role is UserRole.PHYSICIAN
    assert db_session.scalar(
        select(License).where(License.clinic_id == admin.clinic_id)
    ).status is LicenseStatus.ACTIVE