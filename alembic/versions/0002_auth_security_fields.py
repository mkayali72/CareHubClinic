"""Add session invalidation, password lockout, and safe role assignment fields."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_auth_security_fields"
down_revision: Union[str, None] = "0001_foundational_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add authentication security fields and allow unassigned roles.

    Side effects:
        Adds session-version and login-lockout state to users. A NULL role
        represents an account awaiting assignment and receives no elevation.
    """

    op.alter_column("users", "role", existing_type=sa.Enum(name="user_role"), nullable=True)
    op.add_column(
        "users",
        sa.Column(
            "session_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Counter used to invalidate previously issued sessions.",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Consecutive failed login attempts for lockout enforcement.",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp until which login is locked.",
        ),
    )


def downgrade() -> None:
    """Remove authentication security fields and restore required roles."""

    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "session_version")
    op.alter_column("users", "role", existing_type=sa.Enum(name="user_role"), nullable=False)