"""Add explicit clinical dates to visits."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_visit_dates"
down_revision: Union[str, None] = "0005_clinical_documentation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column(
            "visit_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
    )
    op.create_index("ix_visits_visit_date", "visits", ["visit_date"])


def downgrade() -> None:
    op.drop_index("ix_visits_visit_date", table_name="visits")
    op.drop_column("visits", "visit_date")