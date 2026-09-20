"""Coverage for first-run prepopulated records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    User,
    UserRole,
)
from app.services.auth import verify_password
from app.services.sample_data import (
    SAMPLE_PASSWORD,
    ensure_sample_data,
    get_sample_data,
)


def test_first_run_sample_data_is_complete_and_idempotent(
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """Create the requested sample records once and never duplicate them."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    clinic = admin.clinic

    assert ensure_sample_data(db_session, clinic, admin) is True
    db_session.commit()
    assert ensure_sample_data(db_session, clinic, admin) is False

    sample = get_sample_data(db_session, admin)
    assert [member.full_name for member in sample["staff"]] == [
        "Sample_Billing_Clerk",
        "Sample_Dr_1",
        "Sample_Dr_2",
        "Sample_Dr_3",
        "Sample_Front_Office",
        "Sample_Nurse",
    ]
    assert len(sample["appointment_types"]) == 5
    assert [patient.name for patient in sample["patients"]] == [
        "Sample_Patient_1",
        "Sample_Patient_2",
        "Sample_Patient_3",
    ]
    assert len(sample["lab_orders"]) == 3
    assert len(
        list(
            db_session.scalars(
                select(User).where(User.full_name.like("Sample_%"))
            )
        )
    ) == 6

    sample_doctor = db_session.scalar(
        select(User).where(User.username == "sample_dr_1")
    )
    assert sample_doctor is not None
    assert verify_password(SAMPLE_PASSWORD, sample_doctor.hashed_password)


def test_sample_data_management_section_is_not_exposed(client) -> None:
    """Prepopulated records are not separated into a dedicated admin section."""

    assert client.get("/admin/sample-data").status_code == 404