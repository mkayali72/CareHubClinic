"""Create optional clinic Billing fee schedules, invoices, and charges."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_billing"
down_revision: Union[str, None] = "0008_prescriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

invoice_status = postgresql.ENUM(
    "unpaid",
    "paid",
    name="invoice_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    invoice_status.create(bind, checkfirst=True)

    op.create_table(
        "fee_schedule_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("unit_price >= 0", name="ck_fee_schedule_items_unit_price_nonnegative"),
        sa.UniqueConstraint("clinic_id", "name", name="uq_fee_schedule_items_clinic_name"),
    )
    for name, columns in (
        ("ix_fee_schedule_items_clinic_id", ["clinic_id"]),
        ("ix_fee_schedule_items_active", ["active"]),
        ("ix_fee_schedule_items_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "fee_schedule_items", columns)

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_id", sa.Integer(), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", invoice_status, nullable=False, server_default="unpaid"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
    )
    for name, columns in (
        ("ix_invoices_clinic_id", ["clinic_id"]),
        ("ix_invoices_visit_id", ["visit_id"]),
        ("ix_invoices_patient_id", ["patient_id"]),
        ("ix_invoices_created_by_user_id", ["created_by_user_id"]),
        ("ix_invoices_created_at", ["created_at"]),
        ("ix_invoices_status", ["status"]),
        ("ix_invoices_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "invoices", columns)

    op.create_table(
        "charges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_id", sa.Integer(), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fee_schedule_item_id", sa.Integer(), sa.ForeignKey("fee_schedule_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("description_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_charges_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_charges_unit_price_nonnegative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_charges_total_amount_nonnegative"),
    )
    for name, columns in (
        ("ix_charges_clinic_id", ["clinic_id"]),
        ("ix_charges_invoice_id", ["invoice_id"]),
        ("ix_charges_visit_id", ["visit_id"]),
        ("ix_charges_patient_id", ["patient_id"]),
        ("ix_charges_fee_schedule_item_id", ["fee_schedule_item_id"]),
        ("ix_charges_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "charges", columns)

    defaults = (
        ("New patient consultation", "Initial consultation and intake", "150.00"),
        ("Prenatal follow-up", "Routine prenatal follow-up visit", "125.00"),
        ("Gynecology annual exam", "Annual gynecology examination", "175.00"),
        ("Ultrasound review", "Review of external or clinic ultrasound", "75.00"),
        ("Procedure counseling", "Pre-procedure counseling and planning", "100.00"),
    )
    clinic_ids = bind.execute(sa.text("SELECT id FROM clinics")).scalars().all()
    for clinic_id in clinic_ids:
        for name, description, amount in defaults:
            bind.execute(
                sa.text(
                    "INSERT INTO fee_schedule_items "
                    "(clinic_id, name, description, unit_price, active) "
                    "VALUES (:clinic_id, :name, :description, :unit_price, true)"
                ),
                {
                    "clinic_id": clinic_id,
                    "name": name,
                    "description": description,
                    "unit_price": amount,
                },
            )


def downgrade() -> None:
    for name in (
        "ix_charges_deleted_at",
        "ix_charges_fee_schedule_item_id",
        "ix_charges_patient_id",
        "ix_charges_visit_id",
        "ix_charges_invoice_id",
        "ix_charges_clinic_id",
    ):
        op.drop_index(name, table_name="charges")
    op.drop_table("charges")
    for name in (
        "ix_invoices_deleted_at",
        "ix_invoices_status",
        "ix_invoices_created_at",
        "ix_invoices_created_by_user_id",
        "ix_invoices_patient_id",
        "ix_invoices_visit_id",
        "ix_invoices_clinic_id",
    ):
        op.drop_index(name, table_name="invoices")
    op.drop_table("invoices")
    for name in (
        "ix_fee_schedule_items_deleted_at",
        "ix_fee_schedule_items_active",
        "ix_fee_schedule_items_clinic_id",
    ):
        op.drop_index(name, table_name="fee_schedule_items")
    op.drop_table("fee_schedule_items")
    invoice_status.drop(op.get_bind(), checkfirst=True)