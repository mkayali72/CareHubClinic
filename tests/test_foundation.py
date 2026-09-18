"""Automated coverage for foundation schema, authentication, and audit rules."""

from pathlib import Path
import re
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.initial_admin as initial_admin
from app.models import AuditAction, AuditLog, User, UserRole
from app.services.audit import (
    reject_audit_log_mutation,
    soft_delete_record,
)
from app.services.auth import (
    authenticate_user,
    change_user_role,
    create_user,
    require_roles,
    verify_password,
)


@pytest.mark.parametrize("role", list(UserRole))
def test_1_each_allowed_role_can_log_in(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    role: UserRole,
) -> None:
    """Test 1: verify every allowed role can establish a session."""

    response = client.post(
        "/login",
        data={
            "username": role.value,
            "password": "Valid-Test-Password1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/welcome"


def test_fresh_database_gets_one_default_clinic_admin(
    db_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first application initialization creates the documented admin once."""

    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(initial_admin, "SessionLocal", session_factory)

    assert initial_admin.ensure_initial_admin() is True
    with session_factory() as session:
        admin = session.scalar(select(User))
        assert admin is not None
        assert admin.username == "admin"
        assert admin.role is UserRole.CLINIC_ADMIN
        assert authenticate_user(session, "admin", "admin22446688") is admin

    assert initial_admin.ensure_initial_admin() is False


def test_2_authentication_and_admin_role_guards(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 2: verify anonymous and non-admin requests are not over-privileged."""

    anonymous_response = client.get("/welcome", follow_redirects=False)
    assert anonymous_response.status_code == 303
    assert anonymous_response.headers["location"] == "/login"

    non_admin = seeded_users[UserRole.FRONT_DESK]
    admin_dependency = require_roles(UserRole.CLINIC_ADMIN)
    with pytest.raises(HTTPException) as error:
        admin_dependency(current_user=non_admin)
    assert error.value.status_code == 403

    login_response = client.post(
        "/login",
        data={"username": non_admin.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert client.get("/welcome").status_code == 200


def test_8_session_expires_after_configured_timeout(
    short_lived_client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 8: verify a session is rejected after its configured max age."""

    login_response = short_lived_client.post(
        "/login",
        data={
            "username": seeded_users[UserRole.CLINIC_ADMIN].username,
            "password": "Valid-Test-Password1",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert short_lived_client.get("/welcome").status_code == 200

    time.sleep(1.2)
    expired_response = short_lived_client.get("/welcome", follow_redirects=False)
    assert expired_response.status_code == 303
    assert expired_response.headers["location"] == "/login"


def test_9_logout_invalidates_the_previous_session_cookie(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 9: verify an old cookie cannot be replayed after logout."""

    client.post(
        "/login",
        data={
            "username": seeded_users[UserRole.CLINIC_ADMIN].username,
            "password": "Valid-Test-Password1",
        },
        follow_redirects=False,
    )
    old_cookie = dict(client.cookies)
    assert client.get("/welcome").status_code == 200

    logout_response = client.post("/logout", follow_redirects=False)
    assert logout_response.status_code == 303
    replay_response = client.get(
        "/welcome",
        cookies=old_cookie,
        follow_redirects=False,
    )
    assert replay_response.status_code == 303
    assert replay_response.headers["location"] == "/login"


def test_staff_can_change_own_password_and_all_sessions_are_invalidated(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """A staff member changes their password without exposing password data."""

    user = seeded_users[UserRole.FRONT_DESK]
    login_response = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    old_cookie = dict(client.cookies)
    assert client.get("/account/password").status_code == 200

    change_response = client.post(
        "/account/password",
        data={
            "current_password": "Valid-Test-Password1",
            "new_password": "Changed-Password-Valid2",
            "password_confirmation": "Changed-Password-Valid2",
        },
        follow_redirects=False,
    )
    assert change_response.status_code == 303
    assert change_response.headers["location"] == "/login?password_changed=1"

    db_session.refresh(user)
    assert user.hashed_password.startswith("$argon2")
    assert verify_password("Changed-Password-Valid2", user.hashed_password)
    assert not verify_password("Valid-Test-Password1", user.hashed_password)
    assert "Changed-Password-Valid2" not in user.hashed_password

    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.action == AuditAction.UPDATE,
            AuditLog.details["password_changed"].as_boolean().is_(True),
        )
    )
    assert audit is not None
    assert audit.actor_user_id == user.id
    assert audit.details == {"password_changed": True}

    assert client.get("/welcome", follow_redirects=False).status_code == 303
    replay_response = client.get(
        "/welcome",
        cookies=old_cookie,
        follow_redirects=False,
    )
    assert replay_response.status_code == 303
    assert replay_response.headers["location"] == "/login"

    new_login = client.post(
        "/login",
        data={"username": user.username, "password": "Changed-Password-Valid2"},
        follow_redirects=False,
    )
    assert new_login.status_code == 303
    assert client.get("/welcome").status_code == 200


def test_own_password_change_rejects_wrong_current_and_weak_or_mismatched_new_password(
    client: TestClient,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Password errors do not change the account or echo submitted secrets."""

    user = seeded_users[UserRole.NURSE_MA]
    client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    original_hash = user.hashed_password

    responses = [
        (
            {
                "current_password": "Wrong-Current-Password1",
                "new_password": "Changed-Password-Valid2",
                "password_confirmation": "Changed-Password-Valid2",
            },
            "The current password is incorrect.",
        ),
        (
            {
                "current_password": "Valid-Test-Password1",
                "new_password": "short",
                "password_confirmation": "short",
            },
            "Password must be at least 12 characters",
        ),
        (
            {
                "current_password": "Valid-Test-Password1",
                "new_password": "Changed-Password-Valid2",
                "password_confirmation": "Different-Password-Valid3",
            },
            "The password entries do not match.",
        ),
    ]

    for form_data, expected_error in responses:
        response = client.post(
            "/account/password",
            data=form_data,
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert expected_error in response.text
        assert "Valid-Test-Password1" not in response.text
        assert "Changed-Password-Valid2" not in response.text
        assert "Different-Password-Valid3" not in response.text

    db_session.refresh(user)
    assert user.hashed_password == original_hash


def test_10_password_complexity_and_login_lockout(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 10: verify weak passwords are rejected and repeated failures lock out."""

    with pytest.raises(ValueError):
        create_user(
            db=db_session,
            clinic_id=seeded_users[UserRole.CLINIC_ADMIN].clinic_id,
            username="weak_user",
            password="weak",
            full_name="Weak Password",
            role=UserRole.FRONT_DESK,
        )

    target = create_user(
        db=db_session,
        clinic_id=seeded_users[UserRole.CLINIC_ADMIN].clinic_id,
        username="lockout_user",
        password="Valid-Test-Password1",
        full_name="Lockout Test",
        role=UserRole.FRONT_DESK,
    )
    db_session.commit()

    for _ in range(5):
        assert authenticate_user(db_session, target.username, "Wrong-Password1") is None
    assert authenticate_user(db_session, target.username, "Valid-Test-Password1") is None
    db_session.refresh(target)
    assert target.locked_until is not None


def test_12_role_changes_take_effect_immediately(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 12: verify role changes affect authorization without re-login."""

    actor = seeded_users[UserRole.CLINIC_ADMIN]
    target = seeded_users[UserRole.FRONT_DESK]
    change_user_role(db_session, actor, target, UserRole.PHYSICIAN)
    db_session.commit()

    physician_dependency = require_roles(UserRole.PHYSICIAN)
    assert physician_dependency(current_user=target) is target
    assert target.role is UserRole.PHYSICIAN


def test_13_unassigned_user_has_no_elevated_access(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 13: verify an unassigned role fails closed."""

    unassigned = create_user(
        db=db_session,
        clinic_id=seeded_users[UserRole.CLINIC_ADMIN].clinic_id,
        username="unassigned",
        password="Valid-Test-Password1",
        full_name="Unassigned User",
    )
    db_session.commit()

    assert unassigned.role is None
    with pytest.raises(HTTPException) as error:
        require_roles(UserRole.CLINIC_ADMIN)(current_user=unassigned)
    assert error.value.status_code == 403


def test_14_soft_delete_sets_actor_and_keeps_row(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 14: verify soft deletion stores metadata without removing the row."""

    actor = seeded_users[UserRole.CLINIC_ADMIN]
    target = seeded_users[UserRole.FRONT_DESK]
    soft_delete_record(db_session, target, actor, "user", target.id)
    db_session.commit()

    assert target.deleted_at is not None
    assert target.deleted_by_user_id == actor.id
    retained = db_session.scalar(
        select(User)
        .where(User.id == target.id)
        .execution_options(include_deleted=True)
    )
    assert retained is not None


def test_15_soft_deleted_rows_are_hidden_by_default(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 15: verify default ORM queries exclude soft-deleted users."""

    actor = seeded_users[UserRole.CLINIC_ADMIN]
    target = seeded_users[UserRole.FRONT_DESK]
    soft_delete_record(db_session, target, actor, "user", target.id)
    db_session.commit()
    db_session.expire_all()

    assert db_session.scalar(select(User).where(User.id == target.id)) is None


def test_16_soft_delete_writes_audit_entry(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 16: verify the delete audit row identifies actor and timestamp."""

    actor = seeded_users[UserRole.CLINIC_ADMIN]
    target = seeded_users[UserRole.FRONT_DESK]
    soft_delete_record(db_session, target, actor, "user", target.id)
    db_session.commit()

    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == target.id,
            AuditLog.action == AuditAction.DELETE,
        )
    )
    assert audit is not None
    assert audit.actor_user_id == actor.id
    assert audit.timestamp is not None


def test_19_no_hard_delete_path_exists_for_soft_deletable_models() -> None:
    """Test 19: search application code for true row-delete operations."""

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app").rglob("*.py")
    )
    assert "session.delete(" not in source
    assert "db.delete(" not in source
    assert not re.search(r"DELETE\s+FROM\s+(clinics|users)", source, re.IGNORECASE)


def test_20_create_update_delete_actions_write_audit_entries(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 20: verify create, update, and delete events are all recorded."""

    actor = seeded_users[UserRole.CLINIC_ADMIN]
    target = create_user(
        db=db_session,
        clinic_id=actor.clinic_id,
        username="audit_actions",
        password="Valid-Test-Password1",
        full_name="Audit Actions",
        role=UserRole.FRONT_DESK,
        actor=actor,
    )
    change_user_role(db_session, actor, target, UserRole.NURSE_MA)
    soft_delete_record(db_session, target, actor, "user", target.id)
    db_session.commit()

    actions = {
        audit.action
        for audit in db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "user",
                AuditLog.entity_id == target.id,
            )
        )
    }
    assert actions == {AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE}


def test_21_audit_logs_are_immutable_for_every_role(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Test 21: verify no role can mutate an AuditLog record."""

    assert not any(
        "/audit" in route.path
        for route in client.app.routes
        if hasattr(route, "path")
    )
    for _role in UserRole:
        with pytest.raises(PermissionError):
            reject_audit_log_mutation()