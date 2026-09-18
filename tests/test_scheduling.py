"""Automated coverage for the Scheduling module."""

from datetime import date, datetime
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
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
from app.services.auth import create_user
from app.services.patients import create_patient


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a test client as one seeded staff user."""

    response = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_type(db_session: Session, user: User, name: str = "Prenatal visit") -> AppointmentType:
    """Create one appointment type for a clinic."""

    appointment_type = AppointmentType(
        clinic_id=user.clinic_id,
        name=name,
        default_duration_minutes=30,
    )
    db_session.add(appointment_type)
    db_session.commit()
    return appointment_type


def seed_patient(db_session: Session, user: User, name: str = "Scheduling Patient") -> Patient:
    """Create one patient for scheduling tests."""

    patient = create_patient(
        db=db_session,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": name,
            "date_of_birth": date(1990, 1, 2),
            "contact_info": {"phone": "+974 5000 0000"},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    return patient


def seed_appointment(
    db_session: Session,
    actor: User,
    patient: Patient,
    appointment_type: AppointmentType,
    *,
    scheduled_at: datetime | None = None,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
) -> Appointment:
    """Create one appointment assigned to the seeded physician."""

    appointment = Appointment(
        clinic_id=actor.clinic_id,
        patient_id=patient.id,
        doctor_id=actor.id,
        appointment_type_id=appointment_type.id,
        scheduled_at=scheduled_at or datetime.combine(date.today(), datetime.min.time()),
        duration_minutes=appointment_type.default_duration_minutes,
        status=status,
    )
    db_session.add(appointment)
    db_session.commit()
    return appointment


def test_appointment_status_values_preserve_required_order() -> None:
    """Verify the persisted status enum has the exact requested ordering."""

    assert [status.value for status in AppointmentStatus] == [
        "scheduled",
        "checked_in",
        "in_room",
        "with_doctor",
        "done",
        "cancelled",
        "no_show",
    ]


def test_scheduling_is_available_to_clinical_front_desk_roles_not_billing(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify schedule and queue permissions by staff role."""

    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment = seed_appointment(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        appointment_type,
    )

    for role in (
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.FRONT_DESK,
        UserRole.CLINIC_ADMIN,
    ):
        login_as(client, seeded_users[role])
        assert client.get("/schedule?date=" + date.today().isoformat()).status_code == 200
        assert client.get("/queue").status_code == 200
        assert client.get(f"/api/appointments?date={date.today().isoformat()}").status_code == 200
        assert client.get(f"/api/appointments?date={date.today().isoformat()}").json()["appointments"][0]["id"] == appointment.id

    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    assert client.get("/schedule").status_code == 403
    assert client.get("/queue").status_code == 403
    assert client.get("/api/appointments").status_code == 403


def test_schedule_and_queue_support_day_week_month_views_and_click_to_book_slots(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify period views render and only writers receive calendar slot controls."""

    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    seed_appointment(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        appointment_type,
        scheduled_at=datetime.combine(date.today(), datetime.min.time()).replace(
            hour=10,
            minute=30,
        ),
    )
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    day_schedule = client.get(f"/schedule?date={date.today().isoformat()}&view=day")
    assert day_schedule.status_code == 200
    assert 'data-schedule-slot' in day_schedule.text
    assert 'data-doctor-id="' in day_schedule.text
    assert f'data-scheduled-at="{date.today().isoformat()}T10:30"' in day_schedule.text

    for view in ("week", "month"):
        schedule_response = client.get(
            f"/schedule?date={date.today().isoformat()}&view={view}"
        )
        queue_response = client.get(
            f"/queue?date={date.today().isoformat()}&view={view}"
        )
        assert schedule_response.status_code == 200
        assert queue_response.status_code == 200
        assert patient.name in schedule_response.text
        assert patient.name in queue_response.text

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    physician_schedule = client.get(
        f"/schedule?date={date.today().isoformat()}&view=day"
    )
    assert physician_schedule.status_code == 200
    assert "data-schedule-slot" not in physician_schedule.text


def test_front_desk_can_create_existing_patient_appointment_with_type_default(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify front_desk can book an existing patient using the type default."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    response = client.post(
        "/schedule/appointments",
        data={
            "patient_id": patient.id,
            "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
            "appointment_type_id": appointment_type.id,
            "scheduled_at": f"{date.today().isoformat()}T09:30",
            "duration_minutes": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    appointment = db_session.scalar(
        select(Appointment).where(Appointment.patient_id == patient.id)
    )
    assert appointment is not None
    assert appointment.duration_minutes == 30
    assert appointment.status is AppointmentStatus.SCHEDULED
    assert appointment.doctor_id == seeded_users[UserRole.PHYSICIAN].id
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "appointment",
            AuditLog.entity_id == appointment.id,
            AuditLog.action == AuditAction.CREATE,
        )
    ) is not None


def test_each_appointment_type_can_create_edit_and_cancel_an_appointment(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify appointment lifecycle actions work for every clinic type."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment_types = [
        seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Prenatal"),
        seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Postpartum"),
        seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Ultrasound"),
    ]
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    for index, appointment_type in enumerate(appointment_types):
        original_time = f"{date.today().isoformat()}T{9 + index:02d}:00"
        edited_time = f"{date.today().isoformat()}T{13 + index:02d}:30"
        create_response = client.post(
            "/schedule/appointments",
            data={
                "patient_id": patient.id,
                "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
                "appointment_type_id": appointment_type.id,
                "scheduled_at": original_time,
            },
            follow_redirects=False,
        )
        assert create_response.status_code == 303
        appointment = db_session.scalar(
            select(Appointment).where(
                Appointment.appointment_type_id == appointment_type.id
            )
        )
        assert appointment is not None
        assert appointment.status is AppointmentStatus.SCHEDULED
        assert appointment.duration_minutes == appointment_type.default_duration_minutes

        edit_response = client.post(
            f"/schedule/appointments/{appointment.id}/edit",
            data={
                "patient_id": patient.id,
                "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
                "appointment_type_id": appointment_type.id,
                "scheduled_at": edited_time,
                "duration_minutes": "45",
            },
            follow_redirects=False,
        )
        assert edit_response.status_code == 303
        db_session.refresh(appointment)
        assert appointment.scheduled_at == datetime.fromisoformat(edited_time)
        assert appointment.duration_minutes == 45
        assert appointment.appointment_type_id == appointment_type.id

        cancel_response = client.post(
            f"/schedule/appointments/{appointment.id}/cancel",
            follow_redirects=False,
        )
        assert cancel_response.status_code == 303
        db_session.refresh(appointment)
        assert appointment.status is AppointmentStatus.CANCELLED
        assert appointment.patient_id == patient.id
        assert appointment.appointment_type_id == appointment_type.id


def test_overlapping_same_doctor_appointments_are_allowed_by_current_policy(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Assert the current behavior: overlaps are allowed, not blocked.

    The scheduling schema currently has no room field and no overlap constraint,
    so this test intentionally locks in the existing allow behavior until a
    room-allocation decision is made.
    """

    patient_one = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Overlap One")
    patient_two = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Overlap Two")
    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.FRONT_DESK])
    shared_doctor = seeded_users[UserRole.PHYSICIAN].id

    first = client.post(
        "/schedule/appointments",
        data={
            "patient_id": patient_one.id,
            "doctor_id": shared_doctor,
            "appointment_type_id": appointment_type.id,
            "scheduled_at": f"{date.today().isoformat()}T09:00",
            "duration_minutes": "60",
        },
        follow_redirects=False,
    )
    second = client.post(
        "/schedule/appointments",
        data={
            "patient_id": patient_two.id,
            "doctor_id": shared_doctor,
            "appointment_type_id": appointment_type.id,
            "scheduled_at": f"{date.today().isoformat()}T09:30",
            "duration_minutes": "30",
        },
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 303
    overlapping = list(
        db_session.scalars(
            select(Appointment).where(Appointment.doctor_id == shared_doctor)
        )
    )
    assert len(overlapping) == 2
    assert {appointment.scheduled_at.hour for appointment in overlapping} == {9}


def test_only_front_desk_or_admin_can_create_appointment_routes(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify direct appointment creation is protected beyond UI controls."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    payload = {
        "patient_id": patient.id,
        "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
        "appointment_type_id": appointment_type.id,
        "scheduled_at": f"{date.today().isoformat()}T10:00",
    }

    for role in (UserRole.PHYSICIAN, UserRole.NURSE_MA):
        login_as(client, seeded_users[role])
        assert client.post("/schedule/appointments", data=payload).status_code == 403


def test_walk_in_creates_patient_and_checked_in_appointment_atomically(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify one walk-in submission creates both records in today's queue."""

    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    response = client.post(
        "/schedule/walk-ins",
        data={
            "name": "Walk-in Patient",
            "date_of_birth": "1987-06-15",
            "phone": "+974 5555 0200",
            "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
            "appointment_type_id": appointment_type.id,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    patient = db_session.scalar(select(Patient).where(Patient.name == "Walk-in Patient"))
    assert patient is not None
    appointment = db_session.scalar(
        select(Appointment).where(Appointment.patient_id == patient.id)
    )
    assert appointment is not None
    assert appointment.status is AppointmentStatus.CHECKED_IN
    assert appointment.scheduled_at.date() == date.today()
    assert patient.contact_info["phone"] == "+974 5555 0200"


def test_queue_status_action_advances_only_one_step_and_audits(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify scheduled through done transitions and terminal protection."""

    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment = seed_appointment(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        appointment_type,
    )
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    expected_statuses = [
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.IN_ROOM,
        AppointmentStatus.WITH_DOCTOR,
        AppointmentStatus.DONE,
    ]
    for expected_status in expected_statuses:
        response = client.post(
            f"/schedule/appointments/{appointment.id}/advance",
            follow_redirects=False,
        )
        assert response.status_code == 303
        db_session.refresh(appointment)
        assert appointment.status is expected_status

    terminal_response = client.post(
        f"/schedule/appointments/{appointment.id}/advance",
        follow_redirects=False,
    )
    assert terminal_response.status_code == 422
    assert db_session.query(AuditLog).filter(
        AuditLog.entity_type == "appointment",
        AuditLog.entity_id == appointment.id,
        AuditLog.action == AuditAction.UPDATE,
    ).count() == 4


def test_queue_status_sequence_is_visible_to_a_second_authenticated_viewer(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify each persisted transition is visible when another role re-queries."""

    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    appointment = seed_appointment(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        appointment_type,
        scheduled_at=datetime.combine(date.today(), datetime.min.time()).replace(
            hour=10,
            minute=0,
        ),
    )
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    with TestClient(client.app) as observer:
        login_as(observer, seeded_users[UserRole.NURSE_MA])
        for expected_status in (
            AppointmentStatus.CHECKED_IN,
            AppointmentStatus.IN_ROOM,
            AppointmentStatus.WITH_DOCTOR,
            AppointmentStatus.DONE,
        ):
            response = client.post(
                f"/schedule/appointments/{appointment.id}/advance",
                follow_redirects=False,
            )
            assert response.status_code == 303
            db_session.refresh(appointment)
            assert appointment.status is expected_status

            queue_response = observer.get(
                f"/queue?date={date.today().isoformat()}"
            )
            assert queue_response.status_code == 200
            assert expected_status.value.replace("_", " ").title() in queue_response.text


def test_clinic_admin_can_create_and_edit_appointment_types(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify lookup values are clinic-scoped and editable by clinic_admin."""

    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])
    created = client.post(
        "/schedule/types",
        data={"name": "Ultrasound", "default_duration_minutes": "45"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    appointment_type = db_session.scalar(
        select(AppointmentType).where(AppointmentType.name == "Ultrasound")
    )
    assert appointment_type is not None

    edited = client.post(
        f"/schedule/types/{appointment_type.id}",
        data={"name": "Detailed ultrasound", "default_duration_minutes": "60"},
        follow_redirects=False,
    )
    assert edited.status_code == 303
    db_session.refresh(appointment_type)
    assert appointment_type.name == "Detailed ultrasound"
    assert appointment_type.default_duration_minutes == 60

    login_as(client, seeded_users[UserRole.FRONT_DESK])
    assert client.post(
        "/schedule/types",
        data={"name": "Unauthorized", "default_duration_minutes": "30"},
    ).status_code == 403


def test_cross_clinic_appointment_references_are_rejected(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify patient, physician, and type references cannot cross clinics."""

    current_admin = seeded_users[UserRole.CLINIC_ADMIN]
    current_patient = seed_patient(db_session, current_admin, "Current Clinic Patient")
    current_type = seed_type(db_session, current_admin, "Current Clinic Type")
    other_clinic = Clinic(name="Other Clinic")
    db_session.add(other_clinic)
    db_session.flush()
    other_physician = create_user(
        db=db_session,
        clinic_id=other_clinic.id,
        username="other_clinic",
        password="Valid-Test-Password1",
        full_name="Other Clinic Physician",
        role=UserRole.PHYSICIAN,
    )
    other_patient = create_patient(
        db=db_session,
        clinic_id=other_clinic.id,
        actor=other_physician,
        payload={
            "name": "Other Clinic Patient",
            "date_of_birth": date(1989, 3, 4),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    other_type = AppointmentType(
        clinic_id=other_clinic.id,
        name="Other Clinic Type",
        default_duration_minutes=30,
    )
    db_session.add(other_type)
    db_session.commit()

    login_as(client, seeded_users[UserRole.FRONT_DESK])
    base_payload = {
        "patient_id": current_patient.id,
        "doctor_id": seeded_users[UserRole.PHYSICIAN].id,
        "appointment_type_id": current_type.id,
        "scheduled_at": f"{date.today().isoformat()}T11:00",
    }
    for foreign_field, foreign_value in (
        ("patient_id", other_patient.id),
        ("doctor_id", other_physician.id),
        ("appointment_type_id", other_type.id),
    ):
        payload = {**base_payload, foreign_field: foreign_value}
        assert client.post("/schedule/appointments", data=payload).status_code == 422
    assert db_session.query(Appointment).count() == 0


def test_physician_welcome_shows_only_their_todays_queue(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify physician landing page is centered on the physician's queue."""

    second_physician = create_user(
        db=db_session,
        clinic_id=seeded_users[UserRole.PHYSICIAN].clinic_id,
        username="second_physician",
        password="Valid-Test-Password1",
        full_name="Second Physician",
        role=UserRole.PHYSICIAN,
    )
    db_session.commit()
    appointment_type = seed_type(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    own_patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Own Queue Patient")
    other_patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Other Queue Patient")
    seed_appointment(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        own_patient,
        appointment_type,
    )
    seed_appointment(
        db_session,
        second_physician,
        other_patient,
        appointment_type,
    )

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    response = client.get("/welcome")

    assert response.status_code == 200
    assert "Own Queue Patient" in response.text
    assert "Other Queue Patient" not in response.text