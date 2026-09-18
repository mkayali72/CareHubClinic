"""Replace staff email login identifiers with short usernames."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_usernames"
down_revision: Union[str, None] = "0011_request_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _legacy_username(email: str) -> str:
    """Convert an existing email login into a safe short username."""

    username = email.split("@", 1)[0].strip().lower()
    if not username or len(username) > 16:
        raise RuntimeError(
            "Cannot migrate user email to a username of 16 characters or fewer: "
            f"{email!r}. Rename this account before upgrading."
        )
    return username


def upgrade() -> None:
    """Add and populate the clinic-scoped short username identifier."""

    bind = op.get_bind()
    op.add_column(
        "users",
        sa.Column(
            "username",
            sa.String(length=16),
            nullable=True,
            comment="Normalized short username used to authenticate the staff user.",
        ),
    )

    rows = bind.execute(
        sa.text("SELECT id, email FROM users ORDER BY id")
    ).mappings()
    seen: set[str] = set()
    for row in rows:
        username = _legacy_username(row["email"])
        if username in seen:
            raise RuntimeError(
                "Cannot migrate users because legacy email local-parts are not "
                f"unique: {username!r}."
            )
        seen.add(username)
        bind.execute(
            sa.text("UPDATE users SET username = :username WHERE id = :user_id"),
            {"username": username, "user_id": row["id"]},
        )

    op.alter_column("users", "username", nullable=False)
    op.create_unique_constraint(
        "uq_users_username",
        "users",
        ["username"],
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.drop_index("ix_users_email", table_name="users")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")


def downgrade() -> None:
    """Restore an internal email-shaped identifier for older application code."""

    bind = op.get_bind()
    op.add_column(
        "users",
        sa.Column(
            "email",
            sa.String(length=320),
            nullable=True,
            comment="Legacy email-shaped login identifier.",
        ),
    )
    rows = bind.execute(
        sa.text("SELECT id, username FROM users ORDER BY id")
    ).mappings()
    for row in rows:
        bind.execute(
            sa.text("UPDATE users SET email = :email WHERE id = :user_id"),
            {
                "email": f"{row['username']}@local.invalid",
                "user_id": row["id"],
            },
        )

    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_email", "users", ["email"])
    op.drop_index("ix_users_username", table_name="users")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")