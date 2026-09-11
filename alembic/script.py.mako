"""Alembic revision template.

This file is intentionally kept close to Alembic's default template so future
schema revisions remain easy for another developer or coding assistant to read.
"""

"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr depends_on}


def upgrade() -> None:
    """Apply this migration revision."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert this migration revision."""
    ${downgrades if downgrades else "pass"}