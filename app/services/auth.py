"""Session authentication, password hashing, and role dependencies."""

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole

password_hasher = PasswordHash.recommended()


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
    if user is None or not verify_password(password, user.hashed_password):
        return None
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
    request.session["role"] = user.role.value


def logout_user(request: Request) -> None:
    """Clear the current browser session.

    Args:
        request: Incoming request whose session should be invalidated.

    Side effects:
        Removes all values from the signed session cookie.
    """

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

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


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