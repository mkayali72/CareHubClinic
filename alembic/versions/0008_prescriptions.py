"""Create clinic medication formulary and prescription tables."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_prescriptions"
down_revision: Union[str, None] = "0007_lab_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

pregnancy_safety_flag = postgresql.ENUM(
    "true",
    "false",
    "unknown",
    name="pregnancy_safety_flag",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    pregnancy_safety_flag.create(bind, checkfirst=True)

    op.create_table(
        "medication_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("pregnancy_safety_flag", pregnancy_safety_flag, nullable=False, server_default="unknown"),
        sa.Column("allergy_category", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("clinic_id", "name", name="uq_medication_definitions_clinic_name"),
    )
    op.create_index("ix_medication_definitions_clinic_id", "medication_definitions", ["clinic_id"])
    op.create_index("ix_medication_definitions_pregnancy_safety_flag", "medication_definitions", ["pregnancy_safety_flag"])
    op.create_index("ix_medication_definitions_active", "medication_definitions", ["active"])

    op.create_table(
        "prescriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "visit_id",
            sa.Integer(),
            sa.ForeignKey("visits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "medication_definition_id",
            sa.Integer(),
            sa.ForeignKey("medication_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "prescribed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dosage", sa.String(length=255), nullable=False),
        sa.Column("frequency", sa.String(length=255), nullable=False),
        sa.Column("duration", sa.String(length=255), nullable=False),
        sa.Column("pregnancy_warning_acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allergy_warning_acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("prescribed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    for name, columns in (
        ("ix_prescriptions_clinic_id", ["clinic_id"]),
        ("ix_prescriptions_visit_id", ["visit_id"]),
        ("ix_prescriptions_patient_id", ["patient_id"]),
        ("ix_prescriptions_medication_definition_id", ["medication_definition_id"]),
        ("ix_prescriptions_prescribed_by_user_id", ["prescribed_by_user_id"]),
        ("ix_prescriptions_prescribed_at", ["prescribed_at"]),
        ("ix_prescriptions_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "prescriptions", columns)

    defaults = (
        ("Prenatal vitamin", "Daily prenatal multivitamin", "true", "vitamin"),
        ("Folic acid", "Folate supplementation", "true", "vitamin"),
        ("Ferrous sulfate", "Oral iron supplementation", "true", "iron"),
        ("Acetaminophen", "Non-opioid analgesic and antipyretic", "true", "analgesic"),
        ("Ibuprofen", "NSAID analgesic; review pregnancy timing carefully", "false", "nsaid"),
        ("Low-dose aspirin", "Low-dose aspirin when clinically indicated", "unknown", "nsaid"),
        ("Amoxicillin", "Penicillin-class antibiotic", "true", "penicillin"),
        ("Cephalexin", "Cephalosporin antibiotic", "true", "cephalosporin"),
        ("Nitrofurantoin", "Urinary antibiotic; review gestational timing", "unknown", "antibiotic"),
        ("Metronidazole", "Antimicrobial", "true", "antibiotic"),
        ("Fluconazole", "Azole antifungal", "false", "antifungal"),
        ("Ondansetron", "Antiemetic", "unknown", "antiemetic"),
        ("Labetalol", "Antihypertensive", "true", "antihypertensive"),
        ("Nifedipine", "Calcium-channel blocker", "true", "antihypertensive"),
        ("Levothyroxine", "Thyroid hormone replacement", "true", "thyroid"),
    )
    clinic_ids = bind.execute(sa.text("SELECT id FROM clinics")).scalars().all()
    for clinic_id in clinic_ids:
        for name, description, safety, category in defaults:
            bind.execute(
                sa.text(
                    "INSERT INTO medication_definitions "
                    "(clinic_id, name, description, pregnancy_safety_flag, allergy_category, active) "
                    "VALUES (:clinic_id, :name, :description, :safety, :category, true)"
                ),
                {
                    "clinic_id": clinic_id,
                    "name": name,
                    "description": description,
                    "safety": safety,
                    "category": category,
                },
            )


def downgrade() -> None:
    for name in (
        "ix_prescriptions_deleted_at",
        "ix_prescriptions_prescribed_at",
        "ix_prescriptions_prescribed_by_user_id",
        "ix_prescriptions_medication_definition_id",
        "ix_prescriptions_patient_id",
        "ix_prescriptions_visit_id",
        "ix_prescriptions_clinic_id",
    ):
        op.drop_index(name, table_name="prescriptions")
    op.drop_table("prescriptions")
    op.drop_index("ix_medication_definitions_active", table_name="medication_definitions")
    op.drop_index("ix_medication_definitions_pregnancy_safety_flag", table_name="medication_definitions")
    op.drop_index("ix_medication_definitions_clinic_id", table_name="medication_definitions")
    op.drop_table("medication_definitions")
    pregnancy_safety_flag.drop(op.get_bind(), checkfirst=True)