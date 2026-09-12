"""Create clinic appointment types and scheduling appointments."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_scheduling"
down_revision: Union[str, None] = "0003_patient_demographics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

appointment_status = postgresql.ENUM(
    "scheduled",
    "checked_in",
    "in_room",
    "with_doctor",
    "done",
    "cancelled",
    "no_show",
    name="appointment_status",
    create_type=False,
)


def upgrade() -> None:
    """Create appointment type and appointment tables."""

    bind = op.get_bind()
    appointment_status.create(bind, checkfirst=True)

    op.create_table(
        "appointment_types",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            comment="Internal appointment type identifier.",
        ),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Clinic tenant that owns this appointment type.",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="Display name of the appointment type.",
        ),
        sa.Column(
            "default_duration_minutes",
            sa.Integer(),
            nullable=False,
            comment="Default appointment duration in minutes.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="UTC timestamp when the appointment type was created.",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="UTC timestamp when the appointment type was last edited.",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_appointment_types_clinic_name",
        ),
    )
    op.create_index(
        "ix_appointment_types_clinic_id",
        "appointment_types",
        ["clinic_id"],
    )
    op.create_index(
        "ix_appointment_types_deleted_at",
        "appointment_types",
        ["deleted_at"],
    )

    op.create_table(
        "appointments",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            comment="Internal appointment identifier.",
        ),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Clinic tenant that owns this appointment.",
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Patient receiving the appointment.",
        ),
        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Physician assigned to the appointment.",
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=False),
            nullable=False,
            comment="Clinic-local scheduled date and time.",
        ),
        sa.Column(
            "duration_minutes",
            sa.Integer(),
            nullable=False,
            comment="Appointment duration in minutes.",
        ),
        sa.Column(
            "appointment_type_id",
            sa.Integer(),
            sa.ForeignKey("appointment_types.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Clinic-configurable appointment type.",
        ),
        sa.Column(
            "status",
            appointment_status,
            nullable=False,
            server_default=sa.text("'scheduled'"),
            comment="Ordered appointment lifecycle status.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="UTC timestamp when the appointment was created.",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="UTC timestamp when the appointment was last changed.",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "duration_minutes > 0",
            name="ck_appointments_duration_positive",
        ),
    )
    for index_name, columns in (
        ("ix_appointments_clinic_id", ["clinic_id"]),
        ("ix_appointments_patient_id", ["patient_id"]),
        ("ix_appointments_doctor_id", ["doctor_id"]),
        ("ix_appointments_scheduled_at", ["scheduled_at"]),
        ("ix_appointments_appointment_type_id", ["appointment_type_id"]),
        ("ix_appointments_status", ["status"]),
        ("ix_appointments_deleted_at", ["deleted_at"]),
    ):
        op.create_index(index_name, "appointments", columns)


def downgrade() -> None:
    """Remove scheduling tables and the appointment status enum."""

    for index_name in (
        "ix_appointments_deleted_at",
        "ix_appointments_status",
        "ix_appointments_appointment_type_id",
        "ix_appointments_scheduled_at",
        "ix_appointments_doctor_id",
        "ix_appointments_patient_id",
        "ix_appointments_clinic_id",
    ):
        op.drop_index(index_name, table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_appointment_types_deleted_at", table_name="appointment_types")
    op.drop_index("ix_appointment_types_clinic_id", table_name="appointment_types")
    op.drop_table("appointment_types")
    appointment_status.drop(op.get_bind(), checkfirst=True)