"""Coverage for clinic-admin staff account management."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models import AuditAction, AuditLog, Clinic, User, UserRole
from app.services.auth import create_user, verify_password


def login_as(client: TestClient, user: User, password: str = "Valid-Test-Password1") -> None:
    """Sign in through the real browser login route."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_clinic_admin_can_create_staff_and_staff_can_log_in(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Create an active staff account without ever persisting plaintext."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    login_as(client, admin)
    response = client.post(
        "/admin/staff",
        data={
            "email": "new.physician@example.invalid",
            "full_name": "New Physician",
            "role": UserRole.PHYSICIAN.value,
            "password": "New-Physician-Password1",
            "password_confirmation": "New-Physician-Password1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    created = db_session.scalar(
        select(User).where(User.email == "new.physician@example.invalid")
    )
    assert created is not None
    assert created.is_active is True
    assert created.role is UserRole.PHYSICIAN
    assert created.hashed_password.startswith("$argon2")
    assert verify_password("New-Physician-Password1", created.hashed_password)
    assert "New-Physician-Password1" not in created.hashed_password

    audit = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == created.id,
            AuditLog.action == AuditAction.CREATE,
        )
    )
    assert audit is not None
    assert audit.actor_user_id == admin.id

    client.post("/logout", follow_redirects=False)
    login_as(client, created, "New-Physician-Password1")
    assert client.get("/welcome").status_code == 200


def test_only_clinic_admin_can_manage_staff(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Reject the management page for anonymous and non-admin staff."""

    assert client.get("/admin/staff", follow_redirects=False).status_code == 303
    login_as(client, seeded_users[UserRole.FRONT_DESK])
    assert client.get("/admin/staff").status_code == 403
    response = client.post(
        "/admin/staff",
        data={
            "email": "blocked@example.invalid",
            "full_name": "Blocked",
            "role": UserRole.NURSE_MA.value,
            "password": "Valid-Test-Password1",
            "password_confirmation": "Valid-Test-Password1",
        },
    )
    assert response.status_code == 403


def test_staff_management_is_clinic_scoped(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """A clinic administrator cannot view or change another clinic's account."""

    other_clinic = Clinic(name="Other Clinic")
    db_session.add(other_clinic)
    db_session.flush()
    other_staff = create_user(
        db=db_session,
        clinic_id=other_clinic.id,
        email="other.staff@example.invalid",
        password="Valid-Test-Password1",
        full_name="Other Staff",
        role=UserRole.FRONT_DESK,
    )
    db_session.commit()

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    login_as(client, admin)
    page = client.get("/admin/staff")
    assert page.status_code == 200
    assert "other.staff@example.invalid" not in page.text

    response = client.post(
        f"/admin/staff/{other_staff.id}/deactivate",
        follow_redirects=False,
    )
    assert response.status_code == 404
    db_session.refresh(other_staff)
    assert other_staff.is_active is True
    assert other_staff.deleted_at is None


def test_admin_can_deactivate_reactivate_and_reset_staff_password(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Lifecycle actions soft-delete accounts, audit changes, and invalidate sessions."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    target = seeded_users[UserRole.FRONT_DESK]
    login_as(client, admin)

    deactivate = client.post(
        f"/admin/staff/{target.id}/deactivate",
        follow_redirects=False,
    )
    assert deactivate.status_code == 303
    db_session.refresh(target)
    assert target.is_active is False
    assert target.deleted_at is not None
    assert client.get("/welcome", follow_redirects=False).status_code == 200

    delete_audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == target.id,
            AuditLog.action == AuditAction.DELETE,
        )
    )
    assert delete_audit is not None
    assert delete_audit.actor_user_id == admin.id

    client.post("/logout", follow_redirects=False)
    assert client.post(
        "/login",
        data={"email": target.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    ).status_code == 401

    login_as(client, admin)
    reactivate = client.post(
        f"/admin/staff/{target.id}/reactivate",
        follow_redirects=False,
    )
    assert reactivate.status_code == 303
    db_session.refresh(target)
    assert target.is_active is True
    assert target.deleted_at is None

    reset = client.post(
        f"/admin/staff/{target.id}/reset-password",
        data={
            "password": "Reset-Password-Valid1",
            "password_confirmation": "Reset-Password-Valid1",
        },
        follow_redirects=False,
    )
    assert reset.status_code == 303
    db_session.refresh(target)
    assert verify_password("Reset-Password-Valid1", target.hashed_password)
    assert not verify_password("Valid-Test-Password1", target.hashed_password)

    reset_audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == target.id,
            AuditLog.action == AuditAction.UPDATE,
        )
    )
    assert reset_audit is not None
    assert reset_audit.actor_user_id == admin.id
    assert reset_audit.details == {"password_reset": True}

    client.post("/logout", follow_redirects=False)
    assert client.post(
        "/login",
        data={"email": target.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    ).status_code == 401
    login_as(client, target, "Reset-Password-Valid1")
    assert client.get("/welcome").status_code == 200


def test_staff_password_validation_does_not_create_an_account(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Reject weak or mismatched passwords before writing the user row."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    login_as(client, admin)
    response = client.post(
        "/admin/staff",
        data={
            "email": "weak-password@example.invalid",
            "full_name": "Weak Password",
            "role": UserRole.BILLING_CLERK.value,
            "password": "short",
            "password_confirmation": "different",
        },
    )

    assert response.status_code == 422
    assert "short" not in response.text
    assert db_session.scalar(
        select(User).where(User.email == "weak-password@example.invalid")
    ) is None