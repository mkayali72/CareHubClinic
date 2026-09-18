"""Create the default administrator during first application initialization."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AuditAction, Clinic, User, UserRole
from app.services.auth import hash_password
from app.services.audit import record_audit_event
from app.services.licensing import ensure_license


def ensure_initial_admin() -> bool:
    """Create the default clinic and administrator when no users exist.

    Returns:
        True when a new administrator was created, otherwise False.

    Raises:
        ValueError: If the configured initial username is invalid.
    """

    username = settings.initial_admin_username.strip().lower()
    if not username or len(username) > 16:
        raise ValueError("INITIAL_ADMIN_USERNAME must be 1–16 characters.")

    with SessionLocal() as db:
        existing_user = db.scalar(
            select(User)
            .execution_options(include_deleted=True)
            .limit(1)
        )
        if existing_user is not None:
            return False

        clinic = db.scalar(select(Clinic).order_by(Clinic.id))
        if clinic is None:
            clinic = Clinic(name="OB/GYN Clinic")
            db.add(clinic)
            db.flush()
        ensure_license(db, clinic.id)

        user = User(
            clinic_id=clinic.id,
            username=username,
            hashed_password=hash_password(settings.initial_admin_password),
            full_name="Clinic Administrator",
            role=UserRole.CLINIC_ADMIN,
        )
        db.add(user)
        db.flush()
        record_audit_event(
            db=db,
            actor_user_id=None,
            action=AuditAction.CREATE,
            entity_type="user",
            entity_id=user.id,
            details={"role": UserRole.CLINIC_ADMIN.value, "initial_admin": True},
        )
        db.commit()
        return True


def reset_initial_admin_password() -> bool:
    """Reset the configured initial administrator to its configured password.

    This is an explicit local recovery operation for deployments where the
    database volume survived but the administrator password is unknown. It
    never creates or overwrites a different account.

    Returns:
        True when the configured administrator was found and reset.

    Raises:
        ValueError: If the configured username is not a clinic administrator.
    """

    username = settings.initial_admin_username.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(
            select(User)
            .execution_options(include_deleted=True)
            .where(User.username == username)
        )
        if user is None:
            return False
        if user.role is not UserRole.CLINIC_ADMIN:
            raise ValueError(
                f"Configured initial account {username!r} is not a clinic administrator."
            )
        user.hashed_password = hash_password(settings.initial_admin_password)
        user.is_active = True
        user.failed_login_attempts = 0
        user.locked_until = None
        user.session_version += 1
        if user.deleted_at is not None:
            user.restore()
        record_audit_event(
            db=db,
            actor_user_id=None,
            action=AuditAction.UPDATE,
            entity_type="user",
            entity_id=user.id,
            details={"initial_admin_password_reset": True},
        )
        db.commit()
        return True


def main() -> int:
    """Run the explicit initial-administrator recovery command."""

    parser = argparse.ArgumentParser(
        description="Recover the configured clinic administrator account.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset the configured initial administrator to INITIAL_ADMIN_PASSWORD.",
    )
    args = parser.parse_args()
    if not args.reset_password:
        parser.error("Pass --reset-password to perform the recovery operation.")

    if not reset_initial_admin_password():
        parser.error(
            "The configured initial administrator was not found. "
            "A fresh application start will create it when the database has no users."
        )
    print(
        "Reset the configured initial administrator password. "
        "Sign in using INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())