"""Create the default administrator during first application initialization."""

from __future__ import annotations

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