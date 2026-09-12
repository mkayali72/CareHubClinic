"""Automated licensing enforcement, scheduler, and draft-preservation coverage."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Clinic, License, LicenseStatus, Patient, User, UserRole
from app.services.auth import login_user
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
        data={"email": user.email, "password": "Valid-Test-Password1"},
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