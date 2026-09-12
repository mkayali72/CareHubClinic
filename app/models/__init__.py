"""SQLAlchemy models for clinic tenancy, patient demographics, access, and auditing.

Importing the models from this package gives Alembic one stable metadata entry
point.
"""

from app.models.base import Base, SoftDeleteMixin
from app.models.core import (
    Appointment,
    AppointmentStatus,
    AppointmentType,
    AuditAction,
    AuditLog,
    Clinic,
    Patient,
    User,
    UserRole,
)

__all__ = [
    "AuditAction",
    "AuditLog",
    "Appointment",
    "AppointmentStatus",
    "AppointmentType",
    "Base",
    "Clinic",
    "Patient",
    "SoftDeleteMixin",
    "User",
    "UserRole",
]