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
from app.services.audit import record_audit_event
from app.config import settings

password_hasher = PasswordHash.recommended()
MIN_PASSWORD_LENGTH = 12


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
    email: str,
    password: str,
    full_name: str,
    role: UserRole | None = None,
    actor: User | None = None,
) -> User:
    """Create a staff account with safe defaults and a create audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        clinic_id: Clinic that owns the new account.
        email: Login email, normalized to lowercase.
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
    user = User(
        clinic_id=clinic_id,
        email=email.strip().lower(),
        hashed_password=hash_password(password),
        full_name=full_name,
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


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Find an active user and verify the supplied credentials.

    Args:
        db: Request-scoped SQLAlchemy session.
        email: Login email, normalized to lowercase before querying.
        password: Plaintext password submitted by the user.

    Returns:
        The active matching User, or None for an unknown, inactive, or invalid
        account. The distinction is intentionally not exposed to callers.
    """

    normalized_email = email.strip().lower()
    user = db.scalar(
        select(User).where(
            User.email == normalized_email,
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