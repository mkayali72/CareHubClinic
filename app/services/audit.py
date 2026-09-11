"""Reusable audit and soft-delete service operations."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditAction, AuditLog, User, UserRole
from app.models.base import SoftDeleteMixin


def record_audit_event(
    db: Session,
    actor_user_id: int | None,
    action: AuditAction,
    entity_type: str,
    entity_id: int,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add one immutable lifecycle event to the audit log.

    Args:
        db: Request-scoped SQLAlchemy session.
        actor_user_id: ID of the staff user responsible, if known.
        action: Lifecycle action being recorded.
        entity_type: Stable resource name for the affected row.
        entity_id: Identifier of the affected row.
        details: Optional JSON-safe diff or contextual metadata.

    Returns:
        The pending AuditLog instance. The caller controls transaction commit.
    """

    audit_log = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    db.add(audit_log)
    return audit_log


def reject_audit_log_mutation() -> None:
    """Reject all attempts to edit or delete immutable audit history.

    Raises:
        PermissionError: Always, because audit records are append-only.
    """

    raise PermissionError("AuditLog records are immutable and append-only.")


def ensure_clinic_admin(actor: User) -> None:
    """Enforce the service-layer authorization rule for destructive actions.

    Args:
        actor: Staff user attempting the action.

    Raises:
        PermissionError: If the actor is not a clinic administrator.
    """

    if actor.role is not UserRole.CLINIC_ADMIN:
        raise PermissionError("Only clinic_admin may soft-delete or restore records.")


def soft_delete_record(
    db: Session,
    record: SoftDeleteMixin,
    actor: User,
    entity_type: str,
    entity_id: int,
    details: dict[str, Any] | None = None,
    deleted_at: datetime | None = None,
) -> AuditLog:
    """Soft-delete a record and create its generic audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        record: Mapped record that inherits SoftDeleteMixin.
        actor: User authorizing the action; must be clinic_admin.
        entity_type: Stable resource name stored in the audit row.
        entity_id: Identifier of the record being deleted.
        details: Optional JSON-safe context or diff.
        deleted_at: Optional timestamp for deterministic tests or backfills.

    Returns:
        The pending AuditLog row. The caller controls the transaction commit.

    Raises:
        PermissionError: If actor is not clinic_admin.
    """

    ensure_clinic_admin(actor)
    record.soft_delete(actor.id, deleted_at=deleted_at)
    return record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.DELETE,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )


def restore_record(
    db: Session,
    record: SoftDeleteMixin,
    actor: User,
    entity_type: str,
    entity_id: int,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Restore a soft-deleted record and create its audit event.

    Args:
        db: Request-scoped SQLAlchemy session.
        record: Mapped record that inherits SoftDeleteMixin.
        actor: User authorizing the action; must be clinic_admin.
        entity_type: Stable resource name stored in the audit row.
        entity_id: Identifier of the restored record.
        details: Optional JSON-safe context or diff.

    Returns:
        The pending AuditLog row. The caller controls the transaction commit.

    Raises:
        PermissionError: If actor is not clinic_admin.
    """

    ensure_clinic_admin(actor)
    record.restore()
    return record_audit_event(
        db=db,
        actor_user_id=actor.id,
        action=AuditAction.RESTORE,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )