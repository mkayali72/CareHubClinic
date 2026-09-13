"""Route-level acceptance coverage for the two highest-risk clinic workflows."""

from datetime import date, datetime, timedelta
import re

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
    Invoice,
    LabOrder,
    LabOrderSet,
    MedicationDefinition,
    Patient,
    Prescription,
    PregnancyEpisode,
    User,
    UserRole,
    Visit,
)
from app.services.audit import restore_record
from app.services.billing import ensure_default_fee_schedule
from app.services.labs import (
    create_lab_order_set,
    ensure_default_lab_test_definitions,
)
from app.services.prescriptions import ensure_default_medication_definitions


PASSWORD = "Valid-Test-Password1"


def login_as(client: TestClient, user: User) -> None:
    """Authenticate one seeded staff user through the browser login route."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_new_ob_patient_day_through_browser_routes(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify registration through clinical documentation and billing checkout."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    physician = seeded_users[UserRole.PHYSICIAN]
    nurse = seeded_users[UserRole.NURSE_MA]
    front_desk = seeded_users[UserRole.FRONT_DESK]
    billing = seeded_users[UserRole.BILLING_CLERK]
    clinic = db_session.get(Clinic, admin.clinic_id)
    assert clinic is not None
    clinic.billing_module_enabled = True

    appointment_type = AppointmentType(
        clinic_id=clinic.id,
        name="New OB prenatal",
        default_duration_minutes=60,
    )
    follow_up_type = AppointmentType(
        clinic_id=clinic.id,
        name="Prenatal follow-up",
        default_duration_minutes=30,
    )
    db_session.add_all([appointment_type, follow_up_type])

    lab_definitions = ensure_default_lab_test_definitions(db_session, clinic.id)
    create_lab_order_set(
        db_session,
        admin,
        "New OB Panel",
        "Initial prenatal laboratory workup.",
        [definition.id for definition in lab_definitions[:3]],
    )
    medication_definitions = ensure_default_medication_definitions(
        db_session,
        clinic.id,
    )
    fee_schedule = ensure_default_fee_schedule(db_session, clinic.id)
    db_session.commit()

    # Front desk registers the patient.
    login_as(client, front_desk)
    response = client.post(
        "/patients",
        data={
            "name": "Noura Al-Kuwari",
            "date_of_birth": "1992-03-14",
            "contact_phone": "+974 5000 1000",
        },
    )
    assert response.status_code == 200
    patient = db_session.scalar(
        select(Patient).where(Patient.name == "Noura Al-Kuwari")
    )
    assert patient is not None

    # Front desk schedules and checks in the New OB appointment.
    response = client.post(
        "/schedule/appointments",
        data={
            "patient_id": patient.id,
            "doctor_id": physician.id,
            "appointment_type_id": appointment_type.id,
            "scheduled_at": f"{date.today().isoformat()}T09:00",
            "duration_minutes": "",
            "client_request_id": "new-ob-patient-day",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    appointment = db_session.scalar(
        select(Appointment).where(Appointment.patient_id == patient.id)
    )
    assert appointment is not None
    assert appointment.status is AppointmentStatus.SCHEDULED

    response = client.post(
        f"/schedule/appointments/{appointment.id}/advance",
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(appointment)
    assert appointment.status is AppointmentStatus.CHECKED_IN

    # Nurse/M.A. creates the prenatal episode and records intake vitals.
    login_as(client, nurse)
    lmp = date.today() - timedelta(weeks=20)
    response = client.post(
        "/pregnancy-episodes",
        data={"patient_id": patient.id, "lmp": lmp.isoformat()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    episode = db_session.scalar(
        select(PregnancyEpisode).where(PregnancyEpisode.patient_id == patient.id)
    )
    assert episode is not None

    response = client.post(
        "/visits",
        data={
            "patient_id": patient.id,
            "visit_type": "prenatal",
            "visit_date": date.today().isoformat(),
            "pregnancy_episode_id": episode.id,
            "blood_pressure": "118/76",
            "weight_kg": "67.2",
            "height_cm": "164",
            "fundal_height_cm": "20",
            "fetal_heart_tones": "145 bpm",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    visit = db_session.scalar(
        select(Visit).where(Visit.patient_id == patient.id)
    )
    assert visit is not None
    assert visit.vitals["blood_pressure"] == "118/76"
    assert visit.vitals["weight_kg"] == 67.2

    # Physician opens today's queue and the existing visit workflow.
    login_as(client, physician)
    queue = client.get(f"/queue?date={date.today().isoformat()}")
    assert queue.status_code == 200
    assert str(patient.id) in queue.text
    assert f"/visits/{visit.id}" in queue.text
    workspace = client.get(f"/visits/{visit.id}")
    assert workspace.status_code == 200
    assert "118/76" in workspace.text

    response = client.post(
        f"/visits/{visit.id}",
        data={
            "visit_type": "prenatal",
            "visit_date": date.today().isoformat(),
            "pregnancy_episode_id": episode.id,
            "blood_pressure": "118/76",
            "weight_kg": "67.2",
            "height_cm": "164",
            "fundal_height_cm": "20",
            "fetal_heart_tones": "145 bpm",
            "hpi": "First prenatal visit; no bleeding or cramping.",
            "assessment": "正常 early second-trimester pregnancy.",
            "plan": "Continue prenatal vitamins and routine prenatal care.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"/visits/{visit.id}?saved=1" in response.headers["location"]
    db_session.refresh(visit)
    assert "First prenatal visit" in visit.hpi

    # Physician orders the named New OB Panel through the inline panel route.
    order_set = db_session.scalar(
        select(LabOrderSet).where(
            LabOrderSet.clinic_id == clinic.id,
            LabOrderSet.name == "New OB Panel",
        )
    )
    assert order_set is not None
    response = client.post(
        f"/visits/{visit.id}/labs/orders",
        data={"order_set_id": str(order_set.id)},
    )
    assert response.status_code == 200
    assert "Lab orders created" in response.text
    assert len(list(db_session.scalars(
        select(LabOrder).where(LabOrder.visit_id == visit.id)
    ))) == 3

    # Prenatal vitamins are marked pregnancy-safe and therefore do not require
    # an unnecessary warning acknowledgment.
    prenatal = next(
        definition
        for definition in medication_definitions
        if "prenatal" in definition.name.casefold()
    )
    response = client.post(
        f"/visits/{visit.id}/prescriptions",
        data={
            "medication_definition_id": prenatal.id,
            "dosage": "1 tablet",
            "frequency": "daily",
            "duration": "90 days",
        },
    )
    assert response.status_code == 200
    assert "Prescription confirmed" in response.text
    prescription = db_session.scalar(
        select(Prescription).where(Prescription.visit_id == visit.id)
    )
    assert prescription is not None
    assert prescription.pregnancy_warning_acknowledged is False

    # The post-save prompt offers follow-up, and scheduling shows the 4-week cue.
    saved = client.get(f"/visits/{visit.id}?saved=1")
    assert saved.status_code == 200
    assert "Schedule follow-up" in saved.text
    response = client.post(
        f"/visits/{visit.id}/next-action",
        data={"action": "schedule_follow_up"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/schedule?patient_id={patient.id}"
    schedule = client.get(response.headers["location"])
    assert schedule.status_code == 200
    assert "4 weeks" in schedule.text
    assert "20w 0d" in schedule.text

    # Front desk books the suggested follow-up date from the carried patient.
    login_as(client, front_desk)
    front_desk_schedule = client.get(response.headers["location"])
    assert front_desk_schedule.status_code == 200
    assert re.search(
        rf'<option value="{patient.id}"[^>]*selected',
        front_desk_schedule.text,
    )
    follow_up_date = date.today() + timedelta(weeks=4)
    response = client.post(
        "/schedule/appointments",
        data={
            "patient_id": patient.id,
            "doctor_id": physician.id,
            "appointment_type_id": follow_up_type.id,
            "scheduled_at": f"{follow_up_date.isoformat()}T09:00",
            "duration_minutes": "",
            "client_request_id": "new-ob-follow-up",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow_up = db_session.scalar(
        select(Appointment).where(
            Appointment.patient_id == patient.id,
            Appointment.appointment_type_id == follow_up_type.id,
        )
    )
    assert follow_up is not None
    assert follow_up.scheduled_at == datetime.combine(
        follow_up_date,
        datetime.min.time().replace(hour=9),
    )
    assert len(list(db_session.scalars(
        select(Appointment).where(Appointment.patient_id == patient.id)
    ))) == 2

    # Billing checkout is available while clinical note text stays role-protected.
    login_as(client, billing)
    assert client.get(f"/visits/{visit.id}").status_code == 403
    billing_page = client.get(f"/patients/{patient.id}?tab=billing")
    assert billing_page.status_code == 200
    assert "First prenatal visit" not in billing_page.text
    response = client.post(
        f"/visits/{visit.id}/billing/invoices",
        data={"fee_schedule_item_id": [str(fee_schedule[0].id)]},
    )
    assert response.status_code == 200
    invoice = db_session.scalar(
        select(Invoice).where(Invoice.visit_id == visit.id)
    )
    assert invoice is not None


def test_clinic_admin_corrects_duplicate_patient_through_delete_route(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify duplicate correction hides, retains, and audits the patient."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    front_desk = seeded_users[UserRole.FRONT_DESK]
    patient_payload = {
        "name": "Duplicate Patient",
        "date_of_birth": "1988-07-22",
        "contact_phone": "+974 5000 2000",
    }
    login_as(client, front_desk)
    assert client.post("/patients", data=patient_payload).status_code == 200
    assert client.post(
        "/patients",
        data={**patient_payload, "contact_phone": "+974 5000 2001"},
    ).status_code == 200
    duplicates = list(
        db_session.scalars(
            select(Patient).where(Patient.name == "Duplicate Patient")
        )
    )
    assert len(duplicates) == 2
    duplicate = max(duplicates, key=lambda patient: patient.id)

    login_as(client, admin)
    response = client.post(
        f"/patients/{duplicate.id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 303

    for role in UserRole:
        login_as(client, seeded_users[role])
        patient_list = client.get("/patients").text
        assert f"/patients/{duplicate.id}" not in patient_list
        assert patient_list.count("Duplicate Patient") == 1
    db_session.expire_all()
    deleted = db_session.scalar(
        select(Patient)
        .where(Patient.id == duplicate.id)
        .execution_options(include_deleted=True)
    )
    assert deleted is not None
    assert deleted.deleted_at is not None
    event = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "patient",
            AuditLog.entity_id == duplicate.id,
            AuditLog.action == AuditAction.DELETE,
        )
    )
    assert event is not None
    assert event.actor_user_id == admin.id

    # The retained row is recoverable through the existing admin restore seam.
    login_as(client, admin)
    restore_record(
        db_session,
        deleted,
        admin,
        "patient",
        duplicate.id,
    )
    db_session.commit()
    assert "Duplicate Patient" in client.get("/patients").text
