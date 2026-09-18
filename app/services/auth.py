"""Session authentication, password hashing, and role dependencies."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditAction, User, UserRole
from app.services.audit import (
    ensure_clinic_admin,
    record_audit_event,
    restore_record,
    soft_delete_record,
)
from app.config import settings

password_hasher = PasswordHash.recommended()
MIN_PASSWORD_LENGTH = 12
STAFF_ROLES = (
    UserRole.PHYSICIAN,
    UserRole.NURSE_MA,
    UserRole.FRONT_DESK,
    UserRole.BILLING_CLERK,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with the recommended Argon2 configuration.

    Args:
        password: Plaintext password received during account creation.

    Returns:
        An Argon2 password hash suitable for storage.
    """

    return password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an existing Argon2 hash.

    Args:
        password: Plaintext password submitted during login.
        hashed_password: Stored Argon2 hash.

    Returns:
        True when the password matches; otherwise False.
    """

    return password_hasher.verify(password, hashed_password)


def validate_password(password: str) -> None:
    """Reject passwords that do not meet the foundation complexity policy.

    Args:
        password: Plaintext password being assigned to a user.

    Raises:
        ValueError: If the password is shorter than 12 characters or lacks at
            least one uppercase letter, lowercase letter, and digit.
    """

    if (
        len(password) < MIN_PASSWORD_LENGTH
        or not any(character.isupper() for character in password)
        or not any(character.islower() for character in password)
        or not any(character.isdigit() for character in password)
    ):
        raise ValueError(
            "Password must be at least 12 characters and include uppercase, "
            "lowercase, and numeric characters."
        )


def create_user(
    db: Session,
    clinic_id: int,
    username: str,
    password: str,
    full_name: str,
    role: UserRole | None = None,
    actor: User | None = None,
) -> User:
    """Create a staff account with safe defaults and a create audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        clinic_id: Clinic that owns the new account.
        username: Login username, normalized to lowercase.
        password: New plaintext password, validated then hashed.
        full_name: Display name for the account.
        role: Optional role; None means no elevated access until assigned.
        actor: Optional staff user creating the account.

    Returns:
        The pending User instance. The caller controls transaction commit.

    Raises:
        ValueError: If password complexity validation fails.
    """

    validate_password(password)
    normalized_username = username.strip().lower()
    normalized_name = full_name.strip()
    if not normalized_username:
        raise ValueError("A username is required.")
    if len(normalized_username) > 16:
        raise ValueError("Username must be 16 characters or fewer.")
    if not normalized_name:
        raise ValueError("Full name is required.")
    if len(normalized_name) > 255:
        raise ValueError("Full name is too long.")
    user = User(
        clinic_id=clinic_id,
        username=normalized_username,
        hashed_password=hash_password(password),
        full_name=normalized_name,
        role=role,
    )
    db.add(user)
    db.flush()
    record_audit_event(
        db=db,
        actor_user_id=actor.id if actor else None,
        action=AuditAction.CREATE,
        entity_type="user",
        entity_id=user.id,
        details={"role": role.value if role else None},
    )
    return user


def ensure_staff_management_actor(actor: User, clinic_id: int) -> None:
    """Require a clinic administrator acting inside their own clinic."""

    ensure_clinic_admin(actor)
    if actor.clinic_id != clinic_id:
        raise PermissionError("A clinic administrator may only manage their own clinic.")


def create_staff_account(
    db: Session,
    actor: User,
    username: str,
    password: str,
    full_name: str,
    role: UserRole,
) -> User:
    """Create an active non-administrator staff account for the actor's clinic."""

    ensure_staff_management_actor(actor, actor.clinic_id)
    if role not in STAFF_ROLES:
        raise ValueError("Only physician, nurse/MA, front desk, and billing clerk accounts may be created.")
    return create_user(
        db=db,
        clinic_id=actor.clinic_id,
        username=username,
        password=password,
        full_name=full_name,
        role=role,
        actor=actor,
    )


def _ensure_managed_user(actor: User, target: User) -> None:
    """Require an administrator to manage a user in the same clinic."""

    ensure_staff_management_actor(actor, target.clinic_id)
    if actor.clinic_id != target.clinic_id:
        raise PermissionError("A clinic administrator may only manage their own clinic.")
    if actor.id == target.id:
        raise ValueError("You cannot deactivate or reset your own account from this screen.")


def deactivate_user(db: Session, actor: User, target: User) -> User:
    """Deactivate and soft-delete a staff account, invalidating its sessions."""

    _ensure_managed_user(actor, target)
    if target.deleted_at is None:
        target.is_active = False
        target.session_version += 1
        soft_delete_record(
            db,
            target,
            actor,
            "user",
            target.id,
            details={"status": "deactivated"},
        )
    return target


def reactivate_user(db: Session, actor: User, target: User) -> User:
    """Restore a soft-deleted staff account and permit it to log in again."""

    _ensure_managed_user(actor, target)
    if target.deleted_at is not None:
        restore_record(
            db,
            target,
            actor,
            "user",
            target.id,
            details={"status": "reactivated"},
        )
    target.is_active = True
    target.session_version += 1
    return target


def reset_user_password(
    db: Session,
    actor: User,
    target: User,
    password: str,
) -> User:
    """Set a new password without reading or returning the previous password."""

    _ensure_managed_user(actor, target)
    validate_password(password)
    target.hashed_password = hash_password(password)
    target.failed_login_attempts = 0
    target.locked_until = None
    target.session_version += 1
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="user",
        entity_id=target.id,
        details={"password_reset": True},
    )
    return target


def change_own_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> User:
    """Change a user's password after verifying their current password.

    The current password is never stored or returned. Incrementing the
    session-version counter invalidates every previously issued session,
    including the session making this request; callers should clear that
    browser session after committing.

    Args:
        db: Request-scoped SQLAlchemy session.
        user: Authenticated staff account changing its own password.
        current_password: Plaintext password supplied for verification.
        new_password: Plaintext replacement password.

    Returns:
        The updated pending User instance.

    Raises:
        ValueError: If the current password is incorrect or the new password
            fails the application complexity policy.
    """

    if not verify_password(current_password, user.hashed_password):
        raise ValueError("The current password is incorrect.")
    validate_password(new_password)
    user.hashed_password = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.session_version += 1
    record_audit_event(
        db=db,
        actor_user_id=user.id,
        action=AuditAction.UPDATE,
        entity_type="user",
        entity_id=user.id,
        details={"password_changed": True},
    )
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Find an active user and verify the supplied credentials.

    Args:
        db: Request-scoped SQLAlchemy session.
        username: Login username, normalized to lowercase before querying.
        password: Plaintext password submitted by the user.

    Returns:
        The active matching User, or None for an unknown, inactive, or invalid
        account. The distinction is intentionally not exposed to callers.
    """

    normalized_username = username.strip().lower()
    user = db.scalar(
        select(User).where(
            User.username == normalized_username,
            User.is_active.is_(True),
        )
    )
    if user is None:
        return None

    now = datetime.now(timezone.utc)
    if user.locked_until is not None:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            return None
        user.locked_until = None
        user.failed_login_attempts = 0

    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
        db.commit()
        return None

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return user


def login_user(request: Request, user: User) -> None:
    """Store the minimum authenticated identity in the signed session cookie.

    Args:
        request: Incoming request whose session will be updated.
        user: Authenticated staff account.

    Side effects:
        Replaces the session contents with the user ID and role value.
    """

    request.session.clear()
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    request.session["role"] = user.role.value if user.role else None
    request.session["last_activity_at"] = time.time()


def logout_user(request: Request, db: Session) -> None:
    """Clear the current browser session.

    Args:
        request: Incoming request whose session should be invalidated.
        db: Request-scoped SQLAlchemy session used to revoke the session.

    Side effects:
        Removes all values from the signed session cookie.
    """

    user_id: Any = request.session.get("user_id")
    if isinstance(user_id, int):
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(session_version=User.session_version + 1)
        )
        db.commit()
    request.session.clear()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the current active user from the signed session.

    Args:
        request: Incoming request containing the signed session cookie.
        db: Request-scoped SQLAlchemy session.

    Returns:
        The active non-deleted User, or None when the session is absent or stale.

    Side effects:
        Clears stale sessions when the referenced account is missing, inactive,
        or soft-deleted.
    """

    user_id: Any = request.session.get("user_id")
    if not isinstance(user_id, int):
        return None

    last_activity_at = request.session.get("last_activity_at")
    if (
        not isinstance(last_activity_at, (int, float))
        or time.time() - last_activity_at > settings.session_inactivity_seconds
    ):
        request.session.clear()
        return None

    user = db.scalar(select(User).where(User.id == user_id))
    session_version: Any = request.session.get("session_version")
    if (
        user is None
        or not user.is_active
        or not isinstance(session_version, int)
        or session_version != user.session_version
    ):
        request.session.clear()
        return None
    request.session["last_activity_at"] = time.time()
    return user


def change_user_role(
    db: Session,
    actor: User,
    target: User,
    role: UserRole | None,
) -> User:
    """Change a user's role and write an update audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        actor: User authorizing the change; must be clinic_admin.
        target: Account whose role should change.
        role: New role, or None while access remains unassigned.

    Returns:
        The updated pending User instance.

    Raises:
        PermissionError: If actor is not clinic_admin.
    """

    if actor.role is not UserRole.CLINIC_ADMIN:
        raise PermissionError("Only clinic_admin may change user roles.")
    previous_role = target.role.value if target.role else None
    target.role = role
    record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.UPDATE,
        entity_type="user",
        entity_id=target.id,
        details={"field": "role", "from": previous_role, "to": role.value if role else None},
    )
    return target


def require_authenticated_user(
    current_user: User | None = Depends(get_current_user),
) -> User:
    """Require a valid session for an authenticated route.

    Args:
        current_user: User resolved by get_current_user.

    Returns:
        The authenticated User.

    Raises:
        HTTPException: A redirect response to /login when no valid session
            exists.
    """

    if current_user is None:
        raise HTTPException(status_code=303, detail="Authentication required", headers={"Location": "/login"})
    return current_user


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Build a dependency that requires authentication and one of given roles.

    Args:
        allowed_roles: Roles allowed to pass the generated dependency.

    Returns:
        A FastAPI dependency function that returns the authenticated User.

    Raises:
        HTTPException: A 403 response when the user lacks an allowed role.
    """

    def role_dependency(
        current_user: User = Depends(require_authenticated_user),
    ) -> User:
        """Validate the authenticated user's role for one route dependency.

        Args:
            current_user: Authenticated user supplied by the parent dependency.

        Returns:
            The authenticated User when its role is allowed.

        Raises:
            HTTPException: A 403 response when the role is not allowed.
        """

        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return role_dependency