"""Foundational clinic, user, and audit entities.

These models represent tenant configuration, staff access, and immutable
record-level history. Clinical entities such as patients and visits will be
added later and should reuse SoftDeleteMixin where deletion is meaningful.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin


class UserRole(str, Enum):
    """Allowed staff roles for access-control decisions."""

    PHYSICIAN = "physician"
    NURSE_MA = "nurse_ma"
    FRONT_DESK = "front_desk"
    BILLING_CLERK = "billing_clerk"
    CLINIC_ADMIN = "clinic_admin"


class AuditAction(str, Enum):
    """Allowed lifecycle actions recorded in the generic audit log."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


def enum_values(enum_type: type[Enum]) -> list[str]:
    """Return string values for configuring a SQLAlchemy native enum.

    Args:
        enum_type: Python Enum class whose values should be persisted.

    Returns:
        String values in the enum declaration order.
    """

    return [str(member.value) for member in enum_type]


class Clinic(SoftDeleteMixin, Base):
    """Represent one clinic tenant and its clinic-level configuration.

    A Clinic owns staff Users and stores feature flags that apply to the
    tenant. Production deployments will normally isolate each clinic in its
    own database, but keeping this table creates a stable home for settings.

    Fields:
        id: Internal clinic identifier.
        name: Human-readable clinic name.
        branding_reference: Optional path or object-storage reference for logo
            and branding assets.
        billing_module_enabled: Explicit opt-in flag for the optional Billing
            module; it defaults to False.
        settings: Extensible JSON settings for future clinic-level flags.
        created_at: UTC timestamp when the clinic row was created.
    """

    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal identifier for the clinic tenant.",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the clinic.",
    )
    branding_reference: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional logo or branding asset reference.",
    )
    billing_module_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the optional Billing module is enabled for this clinic.",
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Extensible JSON object for clinic-level feature settings.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the clinic tenant was created.",
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )


class User(SoftDeleteMixin, Base):
    """Represent a staff account that can access one clinic deployment.

    A User belongs to a Clinic and has exactly one UserRole. Passwords are
    stored only as Argon2 hashes by the authentication service; this model
    never stores a plaintext password.

    Fields:
        id: Internal staff account identifier.
        clinic_id: Clinic that owns the staff account.
        email: Unique login identifier.
        hashed_password: Argon2 password hash.
        full_name: Name shown on the authenticated landing page and audit log.
        role: One of the five allowed UserRole values.
        is_active: Whether login is currently allowed.
        created_at: UTC timestamp when the account was created.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal identifier for the staff user.",
    )
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Clinic tenant that owns this staff account.",
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True,
        comment="Lowercase email address used to authenticate the staff user.",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Argon2 password hash; never store a plaintext password.",
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Staff member's display name.",
    )
    role: Mapped[UserRole] = mapped_column(
        SqlEnum(
            UserRole,
            name="user_role",
            values_callable=enum_values,
        ),
        nullable=False,
        comment="One of physician, nurse_ma, front_desk, billing_clerk, clinic_admin.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether this staff account may log in.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the staff account was created.",
    )

    clinic: Mapped[Clinic] = relationship(back_populates="users")
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="actor_user",
        foreign_keys="AuditLog.actor_user_id",
    )


class AuditLog(Base):
    """Represent immutable generic history for changes to any application row.

    The entity reference is intentionally generic so future models can record
    lifecycle events without redesigning this table. Audit rows should never
    be soft-deleted or hard-deleted.

    Fields:
        id: Internal audit event identifier.
        actor_user_id: Optional staff user who caused the event.
        action: One of create, update, delete, or restore.
        entity_type: Stable model/resource name, such as ``patient``.
        entity_id: Identifier of the affected record.
        timestamp: UTC timestamp when the event was recorded.
        details: JSON diff or contextual details for the event.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal identifier for the audit event.",
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Staff user who caused the event, if known.",
    )
    action: Mapped[AuditAction] = mapped_column(
        SqlEnum(
            AuditAction,
            name="audit_action",
            values_callable=enum_values,
        ),
        nullable=False,
        comment="Lifecycle action: create, update, delete, or restore.",
    )
    entity_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Generic resource type of the affected record.",
    )
    entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Identifier of the affected record in its entity table.",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the audit event was recorded.",
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="JSON diff or contextual details for the audit event.",
    )

    actor_user: Mapped[User | None] = relationship(
        back_populates="audit_logs",
        foreign_keys=[actor_user_id],
    )