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
    Charge,
    Clinic,
    Invoice,
    InvoiceStatus,
    LabOrder,
    LabOrderSet,
    LabOrderStatus,
    MedicationDefinition,
    Patient,
    Prescription,
    PregnancyEpisode,
    User,
    UserRole,
    Visit,
    VisitType,
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
        data={"username": user.username, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_106_new_ob_patient_day_end_to_end(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 106: verify the complete New OB patient-day workflow."""

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
    assert appointment.patient_id == patient.id
    assert appointment.doctor_id == physician.id
    assert appointment.appointment_type_id == appointment_type.id
    assert appointment.clinic_id == clinic.id
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
    assert episode.patient_id == patient.id
    assert episode.clinic_id == clinic.id
    assert episode.lmp == lmp
    assert episode.status.value == "active"

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
    assert visit.clinic_id == clinic.id
    assert visit.patient_id == patient.id
    assert visit.pregnancy_episode_id == episode.id
    assert visit.visit_type is VisitType.PRENATAL
    assert visit.visit_date == date.today()
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
    lab_orders = list(
        db_session.scalars(select(LabOrder).where(LabOrder.visit_id == visit.id))
    )
    assert len(lab_orders) == 3
    assert all(order.clinic_id == clinic.id for order in lab_orders)
    assert all(order.patient_id == patient.id for order in lab_orders)
    assert all(order.status is LabOrderStatus.ORDERED for order in lab_orders)
    assert all(order.order_set_id == order_set.id for order in lab_orders)
    assert all(order.ordered_by_user_id == physician.id for order in lab_orders)

    # An unsafe medication is blocked until the physician explicitly
    # acknowledges its pregnancy warning.
    unsafe = next(
        definition
        for definition in medication_definitions
        if definition.name == "Ibuprofen"
    )
    response = client.post(
        f"/visits/{visit.id}/prescriptions",
        data={
            "medication_definition_id": unsafe.id,
            "dosage": "200 mg",
            "frequency": "once",
            "duration": "1 day",
        },
    )
    assert response.status_code == 422
    assert "pregnancy" in response.text.casefold()
    assert db_session.scalar(
        select(Prescription).where(
            Prescription.visit_id == visit.id,
            Prescription.medication_definition_id == unsafe.id,
        )
    ) is None

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
    assert prescription.clinic_id == clinic.id
    assert prescription.patient_id == patient.id
    assert prescription.visit_id == visit.id
    assert prescription.prescribed_by_user_id == physician.id
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
    assert follow_up.clinic_id == clinic.id
    assert follow_up.patient_id == patient.id
    assert follow_up.doctor_id == physician.id
    assert follow_up.appointment_type_id == follow_up_type.id
    assert follow_up.status is AppointmentStatus.SCHEDULED
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
    assert invoice.clinic_id == clinic.id
    assert invoice.patient_id == patient.id
    assert invoice.visit_id == visit.id
    assert invoice.status is InvoiceStatus.UNPAID
    assert len(invoice.charges) == 1
    charge = invoice.charges[0]
    assert isinstance(charge, Charge)
    assert charge.clinic_id == clinic.id
    assert charge.patient_id == patient.id
    assert charge.visit_id == visit.id
    assert charge.invoice_id == invoice.id
    assert charge.fee_schedule_item_id == fee_schedule[0].id
    assert charge.total_amount == fee_schedule[0].unit_price

    response = client.post(
        f"/billing/invoices/{invoice.id}/status",
        data={"status": "paid"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.PAID


def test_111_clinic_admin_corrects_duplicate_patient_end_to_end(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 111: verify duplicate correction preserves linked records."""

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
    appointment_type = AppointmentType(
        clinic_id=admin.clinic_id,
        name="Duplicate correction appointment",
        default_duration_minutes=30,
    )
    linked_appointment = Appointment(
        clinic_id=admin.clinic_id,
        patient_id=duplicate.id,
        doctor_id=admin.id,
        scheduled_at=datetime.combine(date.today(), datetime.min.time()),
        duration_minutes=30,
        appointment_type=appointment_type,
        status=AppointmentStatus.SCHEDULED,
    )
    linked_visit = Visit(
        clinic_id=admin.clinic_id,
        patient_id=duplicate.id,
        visit_type=VisitType.PROBLEM_FOCUSED,
        visit_date=date.today(),
        vitals={},
        prenatal_data={},
        gyn_data={},
        hpi="",
        assessment="",
        plan="",
    )
    db_session.add_all([appointment_type, linked_appointment, linked_visit])
    db_session.commit()

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
    retained_appointment = db_session.get(Appointment, linked_appointment.id)
    retained_visit = db_session.get(Visit, linked_visit.id)
    assert retained_appointment is not None
    assert retained_appointment.patient_id == duplicate.id
    assert retained_appointment.clinic_id == admin.clinic_id
    assert retained_visit is not None
    assert retained_visit.patient_id == duplicate.id
    assert retained_visit.clinic_id == admin.clinic_id

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
