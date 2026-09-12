"""Add clinic-local license records for subscription enforcement."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_licensing"
down_revision: Union[str, None] = "0009_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

license_status = postgresql.ENUM(
    "active",
    "grace",
    "expired",
    "revoked",
    name="license_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    license_status.create(bind, checkfirst=True)
    op.create_table(
        "licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            license_status,
            nullable=False,
            server_default="active",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "grace_period_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "grace_period_days >= 0",
            name="ck_licenses_grace_period_nonnegative",
        ),
        sa.UniqueConstraint("clinic_id", name="uq_licenses_clinic_id"),
    )
    op.create_index("ix_licenses_clinic_id", "licenses", ["clinic_id"])
    op.create_index("ix_licenses_expires_at", "licenses", ["expires_at"])

    # Existing clinics receive a one-year local placeholder license. The next
    # real check-in implementation can replace this backfill and its validity.
    bind.execute(
        sa.text(
            "INSERT INTO licenses "
            "(clinic_id, status, expires_at, grace_period_days) "
            "SELECT id, 'active', CURRENT_TIMESTAMP + INTERVAL '365 days', 7 "
            "FROM clinics"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_licenses_expires_at", table_name="licenses")
    op.drop_index("ix_licenses_clinic_id", table_name="licenses")
    op.drop_table("licenses")
    license_status.drop(op.get_bind(), checkfirst=True)