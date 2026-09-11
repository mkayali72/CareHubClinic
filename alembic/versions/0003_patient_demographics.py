"""Create the soft-deletable Patient demographics table."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_patient_demographics"
down_revision: Union[str, None] = "0002_auth_security_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the clinic-scoped Patient demographics table."""

    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), primary_key=True, comment="Internal identifier for the patient."),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Clinic tenant that owns this patient record.",
        ),
        sa.Column("name", sa.String(length=255), nullable=False, comment="Patient display name."),
        sa.Column("date_of_birth", sa.Date(), nullable=False, comment="Patient date of birth."),
        sa.Column(
            "contact_info",
            sa.JSON(),
            nullable=False,
            comment="Structured phone, email, and address details.",
        ),
        sa.Column(
            "insurance_info",
            sa.JSON(),
            nullable=False,
            comment="Structured payer, member ID, and group number details.",
        ),
        sa.Column(
            "emergency_contact",
            sa.JSON(),
            nullable=False,
            comment="Structured emergency contact details.",
        ),
        sa.Column(
            "allergies",
            sa.JSON(),
            nullable=False,
            comment="Structured allergy objects; never free-text notes.",
        ),
        sa.Column(
            "current_medications",
            sa.JSON(),
            nullable=False,
            comment="Structured medication objects.",
        ),
        sa.Column(
            "contraception_method",
            sa.String(length=255),
            nullable=True,
            comment="Current standing contraception method, if documented.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="UTC timestamp when the patient record was created.",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="UTC timestamp when the patient record was last changed.",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when this patient was soft-deleted.",
        ),
        sa.Column(
            "deleted_by_user_id",
            sa.Integer(),
            nullable=True,
            comment="Clinic administrator who soft-deleted this patient.",
        ),
    )
    op.create_index("ix_patients_clinic_id", "patients", ["clinic_id"])
    op.create_index("ix_patients_name", "patients", ["name"])
    op.create_index("ix_patients_deleted_at", "patients", ["deleted_at"])


def downgrade() -> None:
    """Drop the Patient demographics table during an explicit schema rollback."""

    op.drop_index("ix_patients_deleted_at", table_name="patients")
    op.drop_index("ix_patients_name", table_name="patients")
    op.drop_index("ix_patients_clinic_id", table_name="patients")
    op.drop_table("patients")