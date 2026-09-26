"""Prevent active appointments for one physician from overlapping."""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0013_doctor_overlap"
down_revision: Union[str, None] = "0012_usernames"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a database-enforced exclusion constraint for physician schedules."""

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM appointments AS earlier
            JOIN appointments AS later
              ON later.doctor_id = earlier.doctor_id
             AND later.id > earlier.id
            WHERE earlier.deleted_at IS NULL
              AND later.deleted_at IS NULL
              AND earlier.status NOT IN ('done', 'cancelled', 'no_show')
              AND later.status NOT IN ('done', 'cancelled', 'no_show')
              AND tsrange(
                    earlier.scheduled_at,
                    earlier.scheduled_at
                      + earlier.duration_minutes * INTERVAL '1 minute',
                    '[)'
                  )
                  &&
                  tsrange(
                    later.scheduled_at,
                    later.scheduled_at
                      + later.duration_minutes * INTERVAL '1 minute',
                    '[)'
                  )
          ) THEN
            RAISE EXCEPTION
              'Existing active physician appointment overlaps must be resolved before this migration can be applied.';
          END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT ex_appointments_doctor_overlap
        EXCLUDE USING gist (
          doctor_id WITH =,
          tsrange(
            scheduled_at,
            scheduled_at + duration_minutes * INTERVAL '1 minute',
            '[)'
          ) WITH &&
        )
        WHERE (
          deleted_at IS NULL
          AND status NOT IN ('done', 'cancelled', 'no_show')
        )
        """
    )


def downgrade() -> None:
    """Remove the physician appointment overlap constraint."""

    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "ex_appointments_doctor_overlap",
            "appointments",
            type_="exclude",
        )