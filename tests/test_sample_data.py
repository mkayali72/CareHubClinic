"""Coverage for first-run sample records and clinic-admin management."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppointmentType,
    LabOrder,
    Patient,
    User,
    UserRole,
    Visit,
)
from app.services.auth import verify_password
from app.services.sample_data import (
    SAMPLE_PASSWORD,
    ensure_sample_data,
    get_sample_data,
)


def login_as_admin(client, admin: User) -> None:
    """Authenticate the browser test as the seeded clinic administrator."""

    response = client.post(
        "/login",
        data={"username": admin.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


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


def test_sample_data_page_edits_and_removes_only_registered_sample_rows(
    client,
    db_session: Session,
    seeded_users: dict[UserRole, User],
) -> None:
    """The clinic administrator can manage sample rows from the dedicated page."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    ensure_sample_data(db_session, admin.clinic, admin)
    db_session.commit()
    login_as_admin(client, admin)

    page = client.get("/admin/sample-data")
    assert page.status_code == 200
    assert "Sample_Patient_1" in page.text
    assert "Sample_Front_Office" in page.text
    assert "Sample CBC" in page.text

    sample_doctor = db_session.scalar(
        select(User).where(User.username == "sample_dr_1")
    )
    assert sample_doctor is not None
    response = client.post(
        f"/admin/sample-data/staff/{sample_doctor.id}/edit",
        data={
            "username": "sample_doctor_1",
            "full_name": "Sample Doctor One",
            "role": UserRole.PHYSICIAN.value,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(sample_doctor)
    assert sample_doctor.username == "sample_doctor_1"
    assert sample_doctor.full_name == "Sample Doctor One"

    appointment_type = db_session.scalar(
        select(AppointmentType)
        .where(AppointmentType.clinic_id == admin.clinic_id)
        .order_by(AppointmentType.id)
    )
    assert appointment_type is not None
    response = client.post(
        f"/admin/sample-data/appointment-types/{appointment_type.id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.expire_all()
    deleted_type = db_session.scalar(
        select(AppointmentType)
        .execution_options(include_deleted=True)
        .where(AppointmentType.id == appointment_type.id)
    )
    assert deleted_type is not None and deleted_type.deleted_at is not None

    patient = db_session.scalar(
        select(Patient).where(Patient.name == "Sample_Patient_1")
    )
    assert patient is not None
    response = client.post(
        f"/admin/sample-data/patients/{patient.id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.expire_all()
    deleted_patient = db_session.scalar(
        select(Patient)
        .execution_options(include_deleted=True)
        .where(Patient.id == patient.id)
    )
    assert deleted_patient is not None and deleted_patient.deleted_at is not None
    generated_visit = db_session.scalar(
        select(Visit)
        .execution_options(include_deleted=True)
        .where(Visit.patient_id == patient.id)
    )
    assert generated_visit is not None and generated_visit.deleted_at is not None
    assert not list(
        db_session.scalars(
            select(LabOrder)
            .where(LabOrder.patient_id == patient.id)
        )
    )