"""Create foundational clinic, user, audit, and soft-delete columns.

This migration establishes tenant configuration, staff authentication data,
generic audit history, and reusable soft-delete storage. It intentionally does
not create clinical tables such as patients, visits, labs, or prescriptions.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundational_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = postgresql.ENUM(
    "physician",
    "nurse_ma",
    "front_desk",
    "billing_clerk",
    "clinic_admin",
    name="user_role",
    create_type=False,
)
audit_action = postgresql.ENUM(
    "create",
    "update",
    "delete",
    "restore",
    name="audit_action",
    create_type=False,
)


def upgrade() -> None:
    """Create the foundational tables and PostgreSQL enum types.

    Side effects:
        Creates clinics, users, and audit_logs tables plus the shared enum
        types. No clinical tables are created by this revision.
    """

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    audit_action.create(bind, checkfirst=True)

    op.create_table(
        "clinics",
        sa.Column("id", Integer, primary_key=True, comment="Internal clinic tenant identifier."),
        sa.Column("name", String(length=255), nullable=False, comment="Display name of the clinic."),
        sa.Column("branding_reference", Text, nullable=True, comment="Optional logo or branding asset reference."),
        sa.Column(
            "billing_module_enabled",
            Boolean,
            nullable=False,
            server_default="false",
            comment="Whether the optional Billing module is enabled.",
        ),
        sa.Column("settings", JSON, nullable=False, server_default="{}",
                  comment="Extensible JSON object for clinic-level feature settings."),
        sa.Column("created_at", DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"),
                  comment="UTC timestamp when the clinic was created."),
        sa.Column("deleted_at", DateTime(timezone=True), nullable=True,
                  comment="UTC timestamp when this clinic was soft-deleted."),
        sa.Column("deleted_by_user_id", Integer, nullable=True,
                  comment="Clinic administrator who soft-deleted this clinic."),
    )
    op.create_index("ix_clinics_deleted_at", "clinics", ["deleted_at"])

    op.create_table(
        "users",
        sa.Column("id", Integer, primary_key=True, comment="Internal staff user identifier."),
        sa.Column("clinic_id", Integer, ForeignKey("clinics.id", ondelete="RESTRICT"),
                  nullable=False, comment="Clinic tenant that owns this staff account."),
        sa.Column("email", String(length=320), nullable=False,
                  comment="Lowercase email address used for login."),
        sa.Column("hashed_password", String(length=255), nullable=False,
                  comment="Argon2 password hash; never plaintext."),
        sa.Column("full_name", String(length=255), nullable=False,
                  comment="Staff member display name."),
        sa.Column("role", user_role, nullable=False,
                  comment="One of the five allowed staff roles."),
        sa.Column("is_active", Boolean, nullable=False, server_default="true",
                  comment="Whether this account may log in."),
        sa.Column("created_at", DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"),
                  comment="UTC timestamp when the user was created."),
        sa.Column("deleted_at", DateTime(timezone=True), nullable=True,
                  comment="UTC timestamp when this user was soft-deleted."),
        sa.Column("deleted_by_user_id", Integer, nullable=True,
                  comment="Clinic administrator who soft-deleted this user."),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_clinic_id", "users", ["clinic_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", Integer, primary_key=True, comment="Internal audit event identifier."),
        sa.Column("actor_user_id", Integer, ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True, comment="Staff user who caused the event."),
        sa.Column("action", audit_action, nullable=False,
                  comment="Lifecycle action: create, update, delete, or restore."),
        sa.Column("entity_type", String(length=100), nullable=False,
                  comment="Generic resource type of the affected record."),
        sa.Column("entity_id", Integer, nullable=False,
                  comment="Identifier of the affected record."),
        sa.Column("timestamp", DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"),
                  comment="UTC timestamp when the event was recorded."),
        sa.Column("details", JSON, nullable=False, server_default="{}",
                  comment="JSON diff or contextual audit details."),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])


def downgrade() -> None:
    """Remove the foundational tables and enum types.

    Side effects:
        Drops audit_logs, users, and clinics. This destructive operation is
        intended only for development rollback, never for production data.
    """

    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_clinic_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_clinics_deleted_at", table_name="clinics")
    op.drop_table("clinics")
    audit_action.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)