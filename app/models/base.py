"""Reusable SQLAlchemy base classes for the clinic data model."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class that supplies SQLAlchemy metadata to all application models."""


class SoftDeleteMixin:
    """Provide reusable soft-delete state for deletable business records.

    Models that inherit this mixin are filtered out of normal ORM SELECT
    statements by the session event in app.database. Callers can explicitly
    include deleted rows with the SQLAlchemy execution option
    ``include_deleted=True``.

    This application NEVER performs true hard deletes on clinical or financial
    data. Only a user with the clinic_admin role may trigger a soft delete;
    that rule is enforced in the service layer and must never be implemented
    only by hiding controls in the UI. Every future clinically relevant model,
    including Patient, Visit, Prescription, and LabOrder, should use this
    mixin.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="UTC timestamp when this record was soft-deleted, or NULL when active.",
    )
    deleted_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="User ID of the clinic administrator who soft-deleted this record.",
    )

    def soft_delete(
        self,
        actor_user_id: int,
        deleted_at: datetime | None = None,
    ) -> None:
        """Mark this record deleted without removing its database row.

        Args:
            actor_user_id: ID of the clinic_admin user authorizing the action.
            deleted_at: Optional UTC timestamp for deterministic tests or
                backfills; current UTC time is used when omitted.

        Side effects:
            Sets deleted_at and deleted_by_user_id on the current ORM instance.
            The caller remains responsible for committing and writing an
            AuditLog record.
        """

        self.deleted_at = deleted_at or datetime.now(timezone.utc)
        self.deleted_by_user_id = actor_user_id

    def restore(self) -> None:
        """Restore a previously soft-deleted record in memory.

        Side effects:
            Clears deleted_at and deleted_by_user_id. The caller remains
            responsible for committing and writing an AuditLog record.
        """

        self.deleted_at = None
        self.deleted_by_user_id = None