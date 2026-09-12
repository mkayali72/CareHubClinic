"""Foundational clinic, patient, user, and audit entities.

These models represent tenant configuration, patient demographics, staff
access, and immutable record-level history. Future clinical records should
reuse SoftDeleteMixin where deletion is meaningful.
"""

from datetime import date
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
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


class AppointmentStatus(str, Enum):
    """Allowed appointment lifecycle values in display and transition order."""

    SCHEDULED = "scheduled"
    CHECKED_IN = "checked_in"
    IN_ROOM = "in_room"
    WITH_DOCTOR = "with_doctor"
    DONE = "done"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class PregnancyEpisodeStatus(str, Enum):
    """Allowed lifecycle values for a pregnancy episode."""

    ACTIVE = "active"
    DELIVERED = "delivered"
    ENDED = "ended"


class VisitType(str, Enum):
    """Supported clinical visit templates."""

    PRENATAL = "prenatal"
    GYN_ANNUAL = "gyn_annual"
    POSTPARTUM = "postpartum"
    PROBLEM_FOCUSED = "problem_focused"


class ProcedureType(str, Enum):
    """Supported structured procedure documentation types."""

    IUD_INSERTION = "iud_insertion"
    IUD_REMOVAL = "iud_removal"
    COLPOSCOPY = "colposcopy"
    ENDOMETRIAL_BIOPSY = "endometrial_biopsy"


class LabOrderStatus(str, Enum):
    """Allowed lifecycle values for a laboratory order."""

    ORDERED = "ordered"
    RESULTED = "resulted"
    REVIEWED = "reviewed"


class PregnancySafetyFlag(str, Enum):
    """Formulary pregnancy-safety classification values."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class InvoiceStatus(str, Enum):
    """Allowed payment states for an invoice."""

    UNPAID = "unpaid"
    PAID = "paid"


class LicenseStatus(str, Enum):
    """Derived and administrative states for a clinic license."""

    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    REVOKED = "revoked"


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


lab_order_set_tests = Table(
    "lab_order_set_tests",
    Base.metadata,
    Column(
        "order_set_id",
        ForeignKey("lab_order_sets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "lab_test_definition_id",
        ForeignKey("lab_test_definitions.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


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
    patients: Mapped[list["Patient"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    appointment_types: Mapped[list["AppointmentType"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    pregnancy_episodes: Mapped[list["PregnancyEpisode"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    visits: Mapped[list["Visit"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    diagnosis_codes: Mapped[list["DiagnosisCode"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    phrase_templates: Mapped[list["PhraseTemplate"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    lab_test_definitions: Mapped[list["LabTestDefinition"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    lab_order_sets: Mapped[list["LabOrderSet"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    lab_orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    medication_definitions: Mapped[list["MedicationDefinition"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    fee_schedule_items: Mapped[list["FeeScheduleItem"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="clinic",
        cascade="save-update, merge",
    )
    license: Mapped["License | None"] = relationship(
        back_populates="clinic",
        uselist=False,
        cascade="save-update, merge",
    )


class License(Base):
    """Store the local placeholder license for one clinic.

    The application currently evaluates this row locally. The check-in service
    is deliberately isolated so a future license-server response can replace
    the local status calculation without changing request enforcement.
    """

    __tablename__ = "licenses"
    __table_args__ = (
        CheckConstraint(
            "grace_period_days >= 0",
            name="ck_licenses_grace_period_nonnegative",
        ),
        UniqueConstraint("clinic_id", name="uq_licenses_clinic_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal license identifier.",
    )
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Clinic tenant that owns this license.",
    )
    status: Mapped[LicenseStatus] = mapped_column(
        SqlEnum(
            LicenseStatus,
            name="license_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        server_default=LicenseStatus.ACTIVE.value,
        comment="Locally derived or administratively revoked license state.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="UTC expiration timestamp used by local enforcement.",
    )
    last_check_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC time of the latest local or future remote check-in.",
    )
    grace_period_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="7",
        comment="Days after expiration during which the clinic is read-only.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="license")


class Patient(SoftDeleteMixin, Base):
    """Represent patient demographic and medication-related information.

    Fields:
        id: Internal patient identifier.
        clinic_id: Clinic tenant that owns the patient record.
        name: Patient's display name.
        date_of_birth: Patient's date of birth.
        contact_info: Structured contact details such as phone, email, and
            address.
        insurance_info: Structured insurance details such as provider, member
            ID, and group number.
        emergency_contact: Structured emergency contact details.
        allergies: Structured list of allergy objects, never free text.
        current_medications: Structured list of medication objects.
        contraception_method: Current standing contraception method, when
            documented.
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp when the record was last changed.
    """

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal identifier for the patient.",
    )
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Clinic tenant that owns this patient record.",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Patient display name.",
    )
    date_of_birth: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Patient date of birth.",
    )
    contact_info: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured phone, email, and address details.",
    )
    insurance_info: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured payer, member ID, and group number details.",
    )
    emergency_contact: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured emergency contact details.",
    )
    allergies: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Structured allergy objects; never store free-text notes here.",
    )
    current_medications: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Structured medication objects with name, dose, and frequency.",
    )
    contraception_method: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Current standing contraception method, if documented.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the patient record was created.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp when the patient record was last changed.",
    )

    clinic: Mapped[Clinic] = relationship(back_populates="patients")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    pregnancy_episodes: Mapped[list["PregnancyEpisode"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    visits: Mapped[list["Visit"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    lab_orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="patient",
        cascade="save-update, merge",
    )


class AppointmentType(SoftDeleteMixin, Base):
    """Represent a clinic-configurable appointment type lookup value.

    Fields:
        id: Internal appointment type identifier.
        clinic_id: Clinic tenant that owns the type.
        name: Human-readable appointment type name.
        default_duration_minutes: Default duration used when appointments are
            created without an explicit override.
        created_at: UTC timestamp when the type was created.
        updated_at: UTC timestamp when the type was last edited.
    """

    __tablename__ = "appointment_types"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_appointment_types_clinic_name",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal appointment type identifier.",
    )
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Clinic tenant that owns this appointment type.",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name of the appointment type.",
    )
    default_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Default appointment duration in minutes.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the appointment type was created.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp when the appointment type was last edited.",
    )

    clinic: Mapped[Clinic] = relationship(back_populates="appointment_types")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="appointment_type",
        cascade="save-update, merge",
    )


class User(SoftDeleteMixin, Base):
    """Represent a staff account that can access one clinic deployment.

    A User belongs to a Clinic and has one assigned UserRole or no role while
    awaiting assignment. Passwords are stored only as Argon2 hashes by the
    authentication service; this model never stores a plaintext password.

    Fields:
        id: Internal staff account identifier.
        clinic_id: Clinic that owns the staff account.
        email: Unique login identifier.
        hashed_password: Argon2 password hash.
        full_name: Name shown on the authenticated landing page and audit log.
        role: One of the five allowed UserRole values, or None while an account
            is awaiting role assignment. An unassigned user receives no
            elevated access.
        is_active: Whether login is currently allowed.
        created_at: UTC timestamp when the account was created.
        session_version: Counter used to invalidate previously issued sessions.
        failed_login_attempts: Consecutive failed login count.
        locked_until: UTC timestamp until which login attempts are rejected.
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
    role: Mapped[UserRole | None] = mapped_column(
        SqlEnum(
            UserRole,
            name="user_role",
            values_callable=enum_values,
        ),
        nullable=True,
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
    session_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Counter used to invalidate previously issued signed sessions.",
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed login attempts for lockout enforcement.",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp until which login is locked, or NULL when unlocked.",
    )

    clinic: Mapped[Clinic] = relationship(back_populates="users")
    doctor_appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="doctor",
        foreign_keys="Appointment.doctor_id",
        cascade="save-update, merge",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="actor_user",
        foreign_keys="AuditLog.actor_user_id",
    )
    ordered_lab_orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="ordered_by_user",
        foreign_keys="LabOrder.ordered_by_user_id",
        cascade="save-update, merge",
    )
    entered_lab_results: Mapped[list["LabResult"]] = relationship(
        back_populates="entered_by_user",
        foreign_keys="LabResult.entered_by_user_id",
        cascade="save-update, merge",
    )
    reviewed_lab_results: Mapped[list["LabResult"]] = relationship(
        back_populates="reviewed_by_user",
        foreign_keys="LabResult.reviewed_by_user_id",
        cascade="save-update, merge",
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="prescribed_by_user",
        foreign_keys="Prescription.prescribed_by_user_id",
        cascade="save-update, merge",
    )
    created_invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="created_by_user",
        foreign_keys="Invoice.created_by_user_id",
        cascade="save-update, merge",
    )


class Appointment(SoftDeleteMixin, Base):
    """Represent one clinic appointment on the scheduling calendar.

    Fields:
        id: Internal appointment identifier.
        clinic_id: Clinic tenant that owns the appointment.
        patient_id: Existing patient receiving the appointment.
        doctor_id: Physician assigned to the appointment.
        scheduled_at: Clinic-local scheduled date and time.
        duration_minutes: Appointment duration in minutes.
        appointment_type_id: Clinic-configurable type lookup reference.
        status: Ordered lifecycle status from scheduled through done.
        created_at: UTC timestamp when the appointment was created.
        updated_at: UTC timestamp when the appointment was last changed.
    """

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes > 0",
            name="ck_appointments_duration_positive",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        comment="Internal appointment identifier.",
    )
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Clinic tenant that owns this appointment.",
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Patient receiving the appointment.",
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Physician assigned to the appointment.",
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        index=True,
        comment="Clinic-local scheduled date and time.",
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Appointment duration in minutes.",
    )
    appointment_type_id: Mapped[int] = mapped_column(
        ForeignKey("appointment_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Clinic-configurable appointment type.",
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        SqlEnum(
            AppointmentStatus,
            name="appointment_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=AppointmentStatus.SCHEDULED,
        server_default=AppointmentStatus.SCHEDULED.value,
        index=True,
        comment="Ordered appointment lifecycle status.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the appointment was created.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp when the appointment was last changed.",
    )

    clinic: Mapped[Clinic] = relationship(back_populates="appointments")
    patient: Mapped[Patient] = relationship(back_populates="appointments")
    doctor: Mapped[User] = relationship(
        back_populates="doctor_appointments",
        foreign_keys=[doctor_id],
    )
    appointment_type: Mapped[AppointmentType] = relationship(
        back_populates="appointments",
    )


class PregnancyEpisode(SoftDeleteMixin, Base):
    """Group prenatal visits and dating information for one patient.

    Fields:
        id: Internal pregnancy episode identifier.
        clinic_id: Clinic tenant owning the episode.
        patient_id: Patient associated with the pregnancy.
        lmp: Last menstrual period used for initial dating.
        edd: Original estimated due date, calculated from LMP when omitted.
        corrected_edd: Optional ultrasound-corrected estimated due date.
        status: Active, delivered, or ended lifecycle value.
    """

    __tablename__ = "pregnancy_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lmp: Mapped[date] = mapped_column(Date, nullable=False)
    edd: Mapped[date] = mapped_column(Date, nullable=False)
    corrected_edd: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PregnancyEpisodeStatus] = mapped_column(
        SqlEnum(
            PregnancyEpisodeStatus,
            name="pregnancy_episode_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=PregnancyEpisodeStatus.ACTIVE,
        server_default=PregnancyEpisodeStatus.ACTIVE.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="pregnancy_episodes")
    patient: Mapped[Patient] = relationship(back_populates="pregnancy_episodes")
    visits: Mapped[list["Visit"]] = relationship(
        back_populates="pregnancy_episode",
        cascade="save-update, merge",
    )
    delivery_outcome: Mapped["DeliveryOutcome | None"] = relationship(
        back_populates="pregnancy_episode",
        uselist=False,
        cascade="save-update, merge",
    )
    reminder_dismissals: Mapped[list["ReminderDismissal"]] = relationship(
        back_populates="pregnancy_episode",
        cascade="save-update, merge",
    )


class DiagnosisCode(Base):
    """Represent a selectable ICD-10 diagnosis code."""

    __tablename__ = "diagnosis_codes"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "code",
            name="uq_diagnosis_codes_clinic_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    clinic: Mapped[Clinic | None] = relationship(back_populates="diagnosis_codes")
    visit_links: Mapped[list["VisitDiagnosis"]] = relationship(
        back_populates="diagnosis_code",
        cascade="save-update, merge",
    )


class Visit(SoftDeleteMixin, Base):
    """Represent one structured clinical visit note.

    Structured JSON sections are intentionally separated by clinical template:
    vitals are shared by every visit type, prenatal_data is used only for
    prenatal notes, and gyn_data stores menstrual and cervical-screening data.
    Diagnosis codes are represented by VisitDiagnosis rows, never free text.
    """

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    pregnancy_episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("pregnancy_episodes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    visit_type: Mapped[VisitType] = mapped_column(
        SqlEnum(
            VisitType,
            name="visit_type",
            values_callable=enum_values,
        ),
        nullable=False,
        index=True,
    )
    visit_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=func.current_date(),
        index=True,
    )
    vitals: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    prenatal_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    gyn_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    hpi: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assessment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="visits")
    patient: Mapped[Patient] = relationship(back_populates="visits")
    pregnancy_episode: Mapped[PregnancyEpisode | None] = relationship(
        back_populates="visits",
    )
    amendments: Mapped[list["VisitAmendment"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    diagnosis_links: Mapped[list["VisitDiagnosis"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    procedures: Mapped[list["ProcedureRecord"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    phrase_uses: Mapped[list["VisitPhraseUse"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    lab_orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="visit",
        cascade="save-update, merge",
    )


class LabTestDefinition(Base):
    """Represent one clinic-editable laboratory test in the ordering catalog."""

    __tablename__ = "lab_test_definitions"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_lab_test_definitions_clinic_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="lab_test_definitions")
    order_sets: Mapped[list["LabOrderSet"]] = relationship(
        secondary=lab_order_set_tests,
        back_populates="test_definitions",
    )
    orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="lab_test_definition",
        cascade="save-update, merge",
    )


class LabOrderSet(Base):
    """Represent a named bundle of lab test definitions."""

    __tablename__ = "lab_order_sets"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_lab_order_sets_clinic_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="lab_order_sets")
    test_definitions: Mapped[list[LabTestDefinition]] = relationship(
        secondary=lab_order_set_tests,
        back_populates="order_sets",
    )
    orders: Mapped[list["LabOrder"]] = relationship(
        back_populates="order_set",
        cascade="save-update, merge",
    )


class LabOrder(SoftDeleteMixin, Base):
    """Represent one ordered test attached to a clinical visit and patient."""

    __tablename__ = "lab_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lab_test_definition_id: Mapped[int] = mapped_column(
        ForeignKey("lab_test_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_order_sets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status: Mapped[LabOrderStatus] = mapped_column(
        SqlEnum(
            LabOrderStatus,
            name="lab_order_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=LabOrderStatus.ORDERED,
        server_default=LabOrderStatus.ORDERED.value,
        index=True,
    )
    ordered_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="lab_orders")
    visit: Mapped[Visit] = relationship(back_populates="lab_orders")
    patient: Mapped[Patient] = relationship(back_populates="lab_orders")
    lab_test_definition: Mapped[LabTestDefinition] = relationship(
        back_populates="orders",
    )
    order_set: Mapped[LabOrderSet | None] = relationship(back_populates="orders")
    ordered_by_user: Mapped["User"] = relationship(
        foreign_keys=[ordered_by_user_id],
    )
    result: Mapped["LabResult | None"] = relationship(
        back_populates="lab_order",
        uselist=False,
        cascade="save-update, merge",
    )


class LabResult(Base):
    """Store one manual or file lab result and optional physician sign-off."""

    __tablename__ = "lab_results"
    __table_args__ = (
        CheckConstraint(
            "(manual_value IS NOT NULL AND length(trim(manual_value)) > 0) "
            "OR file_path IS NOT NULL",
            name="ck_lab_results_has_value_or_file",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_order_id: Mapped[int] = mapped_column(
        ForeignKey("lab_orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    manual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entered_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    lab_order: Mapped[LabOrder] = relationship(back_populates="result")
    entered_by_user: Mapped["User"] = relationship(
        foreign_keys=[entered_by_user_id],
    )
    reviewed_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[reviewed_by_user_id],
    )


class MedicationDefinition(Base):
    """Represent one clinic-editable medication formulary entry.

    ``pregnancy_safety_flag`` is intentionally tri-state. ``false`` means the
    clinic marks the medication unsafe during an active pregnancy, ``true``
    means the clinic marks it acceptable for this broad formulary check, and
    ``unknown`` means the classification is not established in this catalog.
    The prescription service warns for both ``false`` and ``unknown`` rather
    than treating an unknown value as safe.
    """

    __tablename__ = "medication_definitions"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_medication_definitions_clinic_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pregnancy_safety_flag: Mapped[PregnancySafetyFlag] = mapped_column(
        SqlEnum(
            PregnancySafetyFlag,
            name="pregnancy_safety_flag",
            values_callable=enum_values,
        ),
        nullable=False,
        default=PregnancySafetyFlag.UNKNOWN,
        server_default=PregnancySafetyFlag.UNKNOWN.value,
        index=True,
    )
    allergy_category: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
        server_default="",
        comment="Normalized conflict category such as penicillin, sulfa, or nsaid.",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="medication_definitions")
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="medication_definition",
        cascade="save-update, merge",
    )


class Prescription(SoftDeleteMixin, Base):
    """Represent a physician prescription attached to a visit and patient.

    Warning acknowledgments are stored on the prescription as an audit-friendly
    record that the prescriber saw and explicitly accepted the applicable
    formulary warnings before confirming the order.
    """

    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    medication_definition_id: Mapped[int] = mapped_column(
        ForeignKey("medication_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prescribed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dosage: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(255), nullable=False)
    duration: Mapped[str] = mapped_column(String(255), nullable=False)
    pregnancy_warning_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    allergy_warning_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    prescribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="prescriptions")
    visit: Mapped[Visit] = relationship(back_populates="prescriptions")
    patient: Mapped[Patient] = relationship(back_populates="prescriptions")
    medication_definition: Mapped[MedicationDefinition] = relationship(
        back_populates="prescriptions",
    )
    prescribed_by_user: Mapped["User"] = relationship(
        back_populates="prescriptions",
        foreign_keys=[prescribed_by_user_id],
    )


class FeeScheduleItem(SoftDeleteMixin, Base):
    """Represent one clinic-editable billable service and its current price.

    Invoice charges snapshot the name and amount at creation time, so changing
    this catalog does not rewrite financial history.
    """

    __tablename__ = "fee_schedule_items"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_fee_schedule_items_clinic_name",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_fee_schedule_items_unit_price_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="fee_schedule_items")
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="fee_schedule_item",
        cascade="save-update, merge",
    )


class Invoice(SoftDeleteMixin, Base):
    """Represent a bill for one visit and patient.

    Invoices remain in the database when Billing is disabled. The clinic flag
    controls access to active Billing operations; it is never a data-retention
    switch.
    """

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        SqlEnum(
            InvoiceStatus,
            name="invoice_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=InvoiceStatus.UNPAID,
        server_default=InvoiceStatus.UNPAID.value,
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="invoices")
    visit: Mapped[Visit] = relationship(back_populates="invoices")
    patient: Mapped[Patient] = relationship(back_populates="invoices")
    created_by_user: Mapped["User"] = relationship(
        back_populates="created_invoices",
        foreign_keys=[created_by_user_id],
    )
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="invoice",
        cascade="save-update, merge",
    )

    @property
    def total_amount(self) -> Decimal:
        """Return the sum of active line-item snapshots for this invoice."""

        return sum(
            (charge.total_amount for charge in self.charges),
            Decimal("0.00"),
        )


class Charge(SoftDeleteMixin, Base):
    """Represent one invoice line item with a fee-price snapshot.

    ``unit_price`` and ``description_snapshot`` are copied from the fee
    schedule at creation time. Historical charges therefore remain stable when
    clinic administrators edit the current fee schedule.
    """

    __tablename__ = "charges"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_charges_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_charges_unit_price_nonnegative",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_charges_total_amount_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fee_schedule_item_id: Mapped[int] = mapped_column(
        ForeignKey("fee_schedule_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    description_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="charges")
    invoice: Mapped[Invoice] = relationship(back_populates="charges")
    visit: Mapped[Visit] = relationship(back_populates="charges")
    patient: Mapped[Patient] = relationship(back_populates="charges")
    fee_schedule_item: Mapped[FeeScheduleItem] = relationship(
        back_populates="charges",
    )


class VisitDiagnosis(Base):
    """Associate a Visit with one structured ICD-10 diagnosis code."""

    __tablename__ = "visit_diagnoses"
    __table_args__ = (
        UniqueConstraint(
            "visit_id",
            "diagnosis_code_id",
            name="uq_visit_diagnosis",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    diagnosis_code_id: Mapped[int] = mapped_column(
        ForeignKey("diagnosis_codes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    visit: Mapped[Visit] = relationship(back_populates="diagnosis_links")
    diagnosis_code: Mapped[DiagnosisCode] = relationship(
        back_populates="visit_links",
    )


class VisitAmendment(Base):
    """Record a post-lock amendment without mutating the locked note."""

    __tablename__ = "visit_amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amended_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    visit: Mapped[Visit] = relationship(back_populates="amendments")
    amended_by_user: Mapped["User"] = relationship(
        foreign_keys=[amended_by_user_id],
    )


class ProcedureRecord(SoftDeleteMixin, Base):
    """Represent structured IUD, colposcopy, or biopsy documentation."""

    __tablename__ = "procedure_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    procedure_type: Mapped[ProcedureType] = mapped_column(
        SqlEnum(
            ProcedureType,
            name="procedure_type",
            values_callable=enum_values,
        ),
        nullable=False,
    )
    performed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    performed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    visit: Mapped[Visit] = relationship(back_populates="procedures")
    performed_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[performed_by_user_id],
    )


class DeliveryOutcome(Base):
    """Represent delivery details attached to a pregnancy episode."""

    __tablename__ = "delivery_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pregnancy_episode_id: Mapped[int] = mapped_column(
        ForeignKey("pregnancy_episodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    complications: Mapped[str] = mapped_column(Text, nullable=False, default="")
    birth_weight_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    apgar_one_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    apgar_five_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pregnancy_episode: Mapped[PregnancyEpisode] = relationship(
        back_populates="delivery_outcome",
    )


class PhraseTemplate(Base):
    """Represent a clinic phrase snippet with creator-owned edit history."""

    __tablename__ = "phrase_templates"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "name",
            name="uq_phrase_templates_clinic_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clinic: Mapped[Clinic] = relationship(back_populates="phrase_templates")
    created_by_user: Mapped["User"] = relationship(
        foreign_keys=[created_by_user_id],
    )
    phrase_uses: Mapped[list["VisitPhraseUse"]] = relationship(
        back_populates="phrase_template",
        cascade="save-update, merge",
    )


class VisitPhraseUse(Base):
    """Store the exact phrase text inserted into a visit note."""

    __tablename__ = "visit_phrase_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phrase_template_id: Mapped[int] = mapped_column(
        ForeignKey("phrase_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    inserted_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    visit: Mapped[Visit] = relationship(back_populates="phrase_uses")
    phrase_template: Mapped[PhraseTemplate] = relationship(
        back_populates="phrase_uses",
    )
    inserted_by_user: Mapped["User"] = relationship(
        foreign_keys=[inserted_by_user_id],
    )


class ReminderDismissal(Base):
    """Record that a screening prompt was hidden without marking it complete."""

    __tablename__ = "reminder_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "pregnancy_episode_id",
            "reminder_key",
            name="uq_reminder_dismissal_episode_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pregnancy_episode_id: Mapped[int] = mapped_column(
        ForeignKey("pregnancy_episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reminder_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dismissed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pregnancy_episode: Mapped[PregnancyEpisode] = relationship(
        back_populates="reminder_dismissals",
    )
    dismissed_by_user: Mapped["User"] = relationship(
        foreign_keys=[dismissed_by_user_id],
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