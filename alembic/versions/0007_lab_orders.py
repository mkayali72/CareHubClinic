"""Create lab catalog, order, result, and private-file metadata tables."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_lab_orders"
down_revision: Union[str, None] = "0006_visit_dates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

lab_order_status = postgresql.ENUM(
    "ordered",
    "resulted",
    "reviewed",
    name="lab_order_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    lab_order_status.create(bind, checkfirst=True)

    op.create_table(
        "lab_test_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("clinic_id", "name", name="uq_lab_test_definitions_clinic_name"),
    )
    op.create_index("ix_lab_test_definitions_clinic_id", "lab_test_definitions", ["clinic_id"])
    op.create_index("ix_lab_test_definitions_active", "lab_test_definitions", ["active"])

    op.create_table(
        "lab_order_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("clinic_id", "name", name="uq_lab_order_sets_clinic_name"),
    )
    op.create_index("ix_lab_order_sets_clinic_id", "lab_order_sets", ["clinic_id"])
    op.create_index("ix_lab_order_sets_active", "lab_order_sets", ["active"])

    op.create_table(
        "lab_order_set_tests",
        sa.Column(
            "order_set_id",
            sa.Integer(),
            sa.ForeignKey("lab_order_sets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "lab_test_definition_id",
            sa.Integer(),
            sa.ForeignKey("lab_test_definitions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )

    op.create_table(
        "lab_orders",
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
            "lab_test_definition_id",
            sa.Integer(),
            sa.ForeignKey("lab_test_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_set_id",
            sa.Integer(),
            sa.ForeignKey("lab_order_sets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", lab_order_status, nullable=False, server_default="ordered"),
        sa.Column(
            "ordered_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    for name, columns in (
        ("ix_lab_orders_clinic_id", ["clinic_id"]),
        ("ix_lab_orders_visit_id", ["visit_id"]),
        ("ix_lab_orders_patient_id", ["patient_id"]),
        ("ix_lab_orders_lab_test_definition_id", ["lab_test_definition_id"]),
        ("ix_lab_orders_order_set_id", ["order_set_id"]),
        ("ix_lab_orders_status", ["status"]),
        ("ix_lab_orders_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "lab_orders", columns)

    op.create_table(
        "lab_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lab_order_id",
            sa.Integer(),
            sa.ForeignKey("lab_orders.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("manual_value", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column(
            "entered_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(manual_value IS NOT NULL AND length(trim(manual_value)) > 0) OR file_path IS NOT NULL",
            name="ck_lab_results_has_value_or_file",
        ),
    )
    op.create_index("ix_lab_results_lab_order_id", "lab_results", ["lab_order_id"])

    defaults = (
        ("CBC", "Complete blood count"),
        ("Urinalysis", "Urinalysis with microscopy when indicated"),
        ("Glucose screen", "Pregnancy glucose screening"),
        ("Rh/blood type", "ABO and Rh blood typing"),
        ("STI panel", "Clinic-defined sexually transmitted infection panel"),
        ("Pap/HPV", "Cervical cytology and HPV testing"),
        ("TSH", "Thyroid-stimulating hormone"),
    )
    clinic_ids = bind.execute(sa.text("SELECT id FROM clinics")).scalars().all()
    for clinic_id in clinic_ids:
        for name, description in defaults:
            bind.execute(
                sa.text(
                    "INSERT INTO lab_test_definitions "
                    "(clinic_id, name, description, active) "
                    "VALUES (:clinic_id, :name, :description, true)"
                ),
                {
                    "clinic_id": clinic_id,
                    "name": name,
                    "description": description,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_lab_results_lab_order_id", table_name="lab_results")
    op.drop_table("lab_results")
    for name in (
        "ix_lab_orders_deleted_at",
        "ix_lab_orders_status",
        "ix_lab_orders_order_set_id",
        "ix_lab_orders_lab_test_definition_id",
        "ix_lab_orders_patient_id",
        "ix_lab_orders_visit_id",
        "ix_lab_orders_clinic_id",
    ):
        op.drop_index(name, table_name="lab_orders")
    op.drop_table("lab_orders")
    op.drop_table("lab_order_set_tests")
    op.drop_index("ix_lab_order_sets_active", table_name="lab_order_sets")
    op.drop_index("ix_lab_order_sets_clinic_id", table_name="lab_order_sets")
    op.drop_table("lab_order_sets")
    op.drop_index("ix_lab_test_definitions_active", table_name="lab_test_definitions")
    op.drop_index("ix_lab_test_definitions_clinic_id", table_name="lab_test_definitions")
    op.drop_table("lab_test_definitions")
    lab_order_status.drop(op.get_bind(), checkfirst=True)