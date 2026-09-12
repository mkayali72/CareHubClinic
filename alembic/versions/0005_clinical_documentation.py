"""Create pregnancy, visit, procedure, diagnosis, and phrase documentation tables."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_clinical_documentation"
down_revision: Union[str, None] = "0004_scheduling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

pregnancy_status = postgresql.ENUM(
    "active",
    "delivered",
    "ended",
    name="pregnancy_episode_status",
    create_type=False,
)
visit_type = postgresql.ENUM(
    "prenatal",
    "gyn_annual",
    "postpartum",
    "problem_focused",
    name="visit_type",
    create_type=False,
)
procedure_type = postgresql.ENUM(
    "iud_insertion",
    "iud_removal",
    "colposcopy",
    "endometrial_biopsy",
    name="procedure_type",
    create_type=False,
)


def upgrade() -> None:
    """Create the clinical documentation schema."""

    bind = op.get_bind()
    pregnancy_status.create(bind, checkfirst=True)
    visit_type.create(bind, checkfirst=True)
    procedure_type.create(bind, checkfirst=True)

    op.create_table(
        "pregnancy_episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lmp", sa.Date(), nullable=False),
        sa.Column("edd", sa.Date(), nullable=False),
        sa.Column("corrected_edd", sa.Date(), nullable=True),
        sa.Column(
            "status",
            pregnancy_status,
            nullable=False,
            server_default=sa.text("'active'"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_pregnancy_episodes_clinic_id",
        "pregnancy_episodes",
        ["clinic_id"],
    )
    op.create_index(
        "ix_pregnancy_episodes_patient_id",
        "pregnancy_episodes",
        ["patient_id"],
    )
    op.create_index(
        "ix_pregnancy_episodes_status",
        "pregnancy_episodes",
        ["status"],
    )
    op.create_index(
        "ix_pregnancy_episodes_deleted_at",
        "pregnancy_episodes",
        ["deleted_at"],
    )

    op.create_table(
        "diagnosis_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint(
            "clinic_id",
            "code",
            name="uq_diagnosis_codes_clinic_code",
        ),
    )
    op.create_index("ix_diagnosis_codes_clinic_id", "diagnosis_codes", ["clinic_id"])
    op.create_index("ix_diagnosis_codes_code", "diagnosis_codes", ["code"])

    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pregnancy_episode_id",
            sa.Integer(),
            sa.ForeignKey("pregnancy_episodes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("visit_type", visit_type, nullable=False),
        sa.Column("vitals", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "prenatal_data",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("gyn_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("hpi", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessment", sa.Text(), nullable=False, server_default=""),
        sa.Column("plan", sa.Text(), nullable=False, server_default=""),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    for index_name, columns in (
        ("ix_visits_clinic_id", ["clinic_id"]),
        ("ix_visits_patient_id", ["patient_id"]),
        ("ix_visits_pregnancy_episode_id", ["pregnancy_episode_id"]),
        ("ix_visits_visit_type", ["visit_type"]),
        ("ix_visits_locked_at", ["locked_at"]),
        ("ix_visits_created_at", ["created_at"]),
        ("ix_visits_deleted_at", ["deleted_at"]),
    ):
        op.create_index(index_name, "visits", columns)

    op.create_table(
        "visit_diagnoses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Integer(),
            sa.ForeignKey("visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "diagnosis_code_id",
            sa.Integer(),
            sa.ForeignKey("diagnosis_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "visit_id",
            "diagnosis_code_id",
            name="uq_visit_diagnosis",
        ),
    )
    op.create_index("ix_visit_diagnoses_visit_id", "visit_diagnoses", ["visit_id"])
    op.create_index(
        "ix_visit_diagnoses_diagnosis_code_id",
        "visit_diagnoses",
        ["diagnosis_code_id"],
    )

    op.create_table(
        "visit_amendments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Integer(),
            sa.ForeignKey("visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "amended_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_visit_amendments_visit_id",
        "visit_amendments",
        ["visit_id"],
    )

    op.create_table(
        "procedure_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Integer(),
            sa.ForeignKey("visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("procedure_type", procedure_type, nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "performed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_procedure_records_visit_id", "procedure_records", ["visit_id"])
    op.create_index(
        "ix_procedure_records_deleted_at",
        "procedure_records",
        ["deleted_at"],
    )

    op.create_table(
        "delivery_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pregnancy_episode_id",
            sa.Integer(),
            sa.ForeignKey("pregnancy_episodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("complications", sa.Text(), nullable=False, server_default=""),
        sa.Column("birth_weight_grams", sa.Integer(), nullable=True),
        sa.Column("apgar_one_minute", sa.Integer(), nullable=True),
        sa.Column("apgar_five_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "phrase_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_phrase_templates_clinic_name",
        ),
    )
    op.create_index("ix_phrase_templates_clinic_id", "phrase_templates", ["clinic_id"])

    op.create_table(
        "visit_phrase_uses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Integer(),
            sa.ForeignKey("visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "phrase_template_id",
            sa.Integer(),
            sa.ForeignKey("phrase_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "inserted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(length=32), nullable=False),
        sa.Column("text_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_visit_phrase_uses_visit_id", "visit_phrase_uses", ["visit_id"])

    op.create_table(
        "reminder_dismissals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pregnancy_episode_id",
            sa.Integer(),
            sa.ForeignKey("pregnancy_episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reminder_key", sa.String(length=64), nullable=False),
        sa.Column(
            "dismissed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "pregnancy_episode_id",
            "reminder_key",
            name="uq_reminder_dismissal_episode_key",
        ),
    )
    op.create_index(
        "ix_reminder_dismissals_pregnancy_episode_id",
        "reminder_dismissals",
        ["pregnancy_episode_id"],
    )

    op.bulk_insert(
        sa.table(
            "diagnosis_codes",
            sa.column("code", sa.String()),
            sa.column("description", sa.String()),
            sa.column("active", sa.Boolean()),
        ),
        [
            {
                "code": "Z34.80",
                "description": "Encounter for supervision of other normal pregnancy",
                "active": True,
            },
            {
                "code": "O09.90",
                "description": "Supervision of high-risk pregnancy, unspecified",
                "active": True,
            },
            {
                "code": "O80",
                "description": "Encounter for full-term uncomplicated delivery",
                "active": True,
            },
            {
                "code": "Z01.419",
                "description": "Encounter for gynecological examination",
                "active": True,
            },
            {
                "code": "Z12.4",
                "description": "Encounter for screening for malignant neoplasm of cervix",
                "active": True,
            },
            {
                "code": "N76.0",
                "description": "Acute vaginitis",
                "active": True,
            },
            {
                "code": "R10.2",
                "description": "Pelvic and perineal pain",
                "active": True,
            },
        ],
    )


def downgrade() -> None:
    """Remove clinical documentation tables and enum types."""

    for index_name in (
        "ix_reminder_dismissals_pregnancy_episode_id",
    ):
        op.drop_index(index_name, table_name="reminder_dismissals")
    op.drop_table("reminder_dismissals")
    op.drop_index("ix_visit_phrase_uses_visit_id", table_name="visit_phrase_uses")
    op.drop_table("visit_phrase_uses")
    op.drop_index("ix_phrase_templates_clinic_id", table_name="phrase_templates")
    op.drop_table("phrase_templates")
    op.drop_table("delivery_outcomes")
    op.drop_index("ix_procedure_records_deleted_at", table_name="procedure_records")
    op.drop_index("ix_procedure_records_visit_id", table_name="procedure_records")
    op.drop_table("procedure_records")
    op.drop_index("ix_visit_amendments_visit_id", table_name="visit_amendments")
    op.drop_table("visit_amendments")
    op.drop_index(
        "ix_visit_diagnoses_diagnosis_code_id",
        table_name="visit_diagnoses",
    )
    op.drop_index("ix_visit_diagnoses_visit_id", table_name="visit_diagnoses")
    op.drop_table("visit_diagnoses")
    for index_name in (
        "ix_visits_deleted_at",
        "ix_visits_created_at",
        "ix_visits_locked_at",
        "ix_visits_visit_type",
        "ix_visits_pregnancy_episode_id",
        "ix_visits_patient_id",
        "ix_visits_clinic_id",
    ):
        op.drop_index(index_name, table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_diagnosis_codes_code", table_name="diagnosis_codes")
    op.drop_index("ix_diagnosis_codes_clinic_id", table_name="diagnosis_codes")
    op.drop_table("diagnosis_codes")
    for index_name in (
        "ix_pregnancy_episodes_deleted_at",
        "ix_pregnancy_episodes_status",
        "ix_pregnancy_episodes_patient_id",
        "ix_pregnancy_episodes_clinic_id",
    ):
        op.drop_index(index_name, table_name="pregnancy_episodes")
    op.drop_table("pregnancy_episodes")
    procedure_type.drop(op.get_bind(), checkfirst=True)
    visit_type.drop(op.get_bind(), checkfirst=True)
    pregnancy_status.drop(op.get_bind(), checkfirst=True)