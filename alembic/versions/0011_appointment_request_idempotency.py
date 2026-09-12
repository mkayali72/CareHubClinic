"""Make appointment form retries safe after a lost response."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_request_idempotency"
down_revision: Union[str, None] = "0010_licensing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the clinic-scoped browser request identity to appointments."""

    op.add_column(
        "appointments",
        sa.Column(
            "client_request_id",
            sa.String(length=128),
            nullable=True,
            comment="Browser-generated request identity used to make retries safe.",
        ),
    )
    op.create_unique_constraint(
        "uq_appointments_clinic_client_request_id",
        "appointments",
        ["clinic_id", "client_request_id"],
    )


def downgrade() -> None:
    """Remove appointment request idempotency support."""

    op.drop_constraint(
        "uq_appointments_clinic_client_request_id",
        "appointments",
        type_="unique",
    )
    op.drop_column("appointments", "client_request_id")