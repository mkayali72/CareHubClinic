"""Automated coverage for the Visit Documentation module."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditAction,
    AuditLog,
    DiagnosisCode,
    Patient,
    PhraseTemplate,
    PregnancyEpisodeStatus,
    ProcedureType,
    User,
    UserRole,
    Visit,
    VisitAmendment,
    VisitType,
)
from app.services.clinical import (
    VISIT_LOCK_WINDOW,
    calculate_edd,
    create_amendment,
    create_delivery_outcome,
    create_phrase_template,
    create_pregnancy_episode,
    create_procedure_record,
    create_visit,
    dismiss_screening_reminder,
    get_diagnosis_codes,
    gestational_age,
    insert_phrase_into_visit,
    is_visit_locked,
    pregnancy_trend,
    screening_reminders,
    update_visit,
)
from app.services.patients import create_patient


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a test client as one seeded staff user."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient(db_session: Session, user: User) -> Patient:
    """Create one patient in the actor's clinic."""

    patient = create_patient(
        db=db_session,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": "Clinical Patient",
            "date_of_birth": date(1990, 2, 3),
            "contact_info": {"phone": "+974 5000 0100"},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    return patient


def seed_codes(db_session: Session) -> list[DiagnosisCode]:
    """Create global ICD-10 choices for SQLite service tests."""

    codes = [
        DiagnosisCode(code="O09.90", description="High-risk pregnancy"),
        DiagnosisCode(code="Z34.80", description="Normal pregnancy supervision"),
        DiagnosisCode(code="Z01.419", description="Gynecological examination"),
    ]
    db_session.add_all(codes)
    db_session.commit()
    return codes


def make_visit(
    db_session: Session,
    actor: User,
    patient: Patient,
    episode_id: int | None,
    code_ids: list[int],
    visit_type: VisitType = VisitType.PRENATAL,
) -> Visit:
    """Create a minimally complete visit through the service."""

    if episode_id is None and visit_type is VisitType.PRENATAL:
        visit_type = VisitType.PROBLEM_FOCUSED
    return create_visit(
        db_session,
        actor,
        patient.id,
        visit_type,
        episode_id,
        {"blood_pressure": "120/80", "weight_kg": "68.5", "height_cm": "165"},
        {
            "fundal_height_cm": "24",
            "fetal_heart_tones": "145 bpm",
            "fetal_position": "cephalic",
            "ultrasound_efw_grams": "620",
        },
        {"menstrual_history": "Regular"},
        "Patient reports good fetal movement.",
        "Stable prenatal course.",
        "Continue routine follow-up.",
        code_ids,
    )


def test_clinical_workspace_is_restricted_to_clinical_roles(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify clinical roles can enter the workspace and other roles cannot."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    for role in (
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.CLINIC_ADMIN,
    ):
        login_as(client, seeded_users[role])
        response = client.get(f"/visits/patients/{patient.id}")
        assert response.status_code == 200
        assert "Clinical documentation" in response.text

    for role in (UserRole.FRONT_DESK, UserRole.BILLING_CLERK):
        login_as(client, seeded_users[role])
        assert client.get(f"/visits/patients/{patient.id}").status_code == 403


def test_pregnancy_dating_calculates_edd_and_corrected_edd(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify LMP dating, corrected EDD, and gestational-age display."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    lmp = date.today() - timedelta(weeks=20, days=2)
    episode = create_pregnancy_episode(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        lmp,
        corrected_edd=lmp + timedelta(days=278),
    )
    assert episode.edd == calculate_edd(lmp)
    assert episode.corrected_edd == lmp + timedelta(days=278)
    age = gestational_age(episode, lmp + timedelta(days=143))
    assert age["weeks"] == 20
    assert age["days"] == 3
    assert age["display"] == "20w 3d"


def test_visit_templates_store_prenatal_and_gyn_structured_sections(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify type-specific fields are normalized into separate JSON sections."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    codes = seed_codes(db_session)
    episode = create_pregnancy_episode(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        date.today() - timedelta(days=100),
    )
    prenatal = make_visit(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        episode.id,
        [codes[0].id],
    )
    gyn = create_visit(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        VisitType.GYN_ANNUAL,
        None,
        {"blood_pressure": "118/76"},
        None,
        {"menstrual_history": "Regular", "pap_due_date": date(2027, 3, 1)},
        "Annual wellness visit.",
        "Routine exam.",
        "Return in one year.",
        [codes[2].id],
    )
    db_session.commit()
    assert prenatal.prenatal_data["fundal_height_cm"] == 24.0
    assert prenatal.gyn_data == {}
    assert gyn.gyn_data["pap_due_date"] == "2027-03-01"
    assert gyn.prenatal_data == {}


def test_icd10_lookup_rejects_unavailable_codes_and_audits_selection(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify diagnosis selection uses active lookup rows, not free text."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    codes = seed_codes(db_session)
    visit = make_visit(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        None,
        [codes[0].id],
    )
    db_session.commit()
    assert [link.diagnosis_code_id for link in visit.diagnosis_links] == [codes[0].id]
    assert get_diagnosis_codes(db_session, seeded_users[UserRole.PHYSICIAN].clinic_id)
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "visit",
            AuditLog.entity_id == visit.id,
            AuditLog.action == AuditAction.CREATE,
        )
    ) is not None
    with pytest.raises(ValueError, match="diagnosis"):
        make_visit(
            db_session,
            seeded_users[UserRole.PHYSICIAN],
            patient,
            None,
            [999999],
        )


def test_procedure_and_delivery_outcome_update_clinical_lifecycle(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify structured procedures and delivery outcomes persist together."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    episode = create_pregnancy_episode(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        date.today() - timedelta(days=100),
    )
    visit = make_visit(db_session, seeded_users[UserRole.PHYSICIAN], patient, episode.id, [])
    procedure = create_procedure_record(
        db_session,
        visit,
        seeded_users[UserRole.PHYSICIAN],
        ProcedureType.COLPOSCOPY,
        {"notes": "Transformation zone visualized."},
    )
    outcome = create_delivery_outcome(
        db_session,
        episode,
        seeded_users[UserRole.PHYSICIAN],
        date.today(),
        "vaginal",
        "None",
        3200,
        8,
        9,
    )
    db_session.commit()
    assert procedure.visit_id == visit.id
    assert outcome.pregnancy_episode_id == episode.id
    assert episode.status is PregnancyEpisodeStatus.DELIVERED


def test_locked_visit_rejects_edit_and_accepts_amendment(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify the named lock window and amendment-only behavior."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    codes = seed_codes(db_session)
    visit = make_visit(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient,
        None,
        [codes[0].id],
    )
    db_session.commit()
    visit.created_at = datetime.now(timezone.utc) - VISIT_LOCK_WINDOW - timedelta(minutes=1)
    db_session.flush()
    assert is_visit_locked(visit)
    with pytest.raises(PermissionError, match="amendments"):
        update_visit(
            db_session,
            visit,
            seeded_users[UserRole.PHYSICIAN],
            VisitType.PRENATAL,
            None,
            {},
            {},
            {},
            "Changed HPI",
            "Changed assessment",
            "Changed plan",
            [codes[0].id],
        )
    amendment = create_amendment(
        db_session,
        visit,
        seeded_users[UserRole.PHYSICIAN],
        "Clarification: fetal heart tones were documented after the visit.",
    )
    db_session.commit()
    assert amendment.visit_id == visit.id
    assert db_session.scalar(
        select(VisitAmendment).where(VisitAmendment.id == amendment.id)
    ) is not None


def test_phrase_use_keeps_text_snapshot_after_template_edit(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify phrase insertion copies text instead of reading it dynamically."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    visit = make_visit(db_session, seeded_users[UserRole.PHYSICIAN], patient, None, [])
    template = create_phrase_template(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        "Routine follow-up",
        "Return in four weeks.",
    )
    insert_phrase_into_visit(
        db_session,
        visit,
        template,
        seeded_users[UserRole.PHYSICIAN],
        "plan",
    )
    template.body = "Return in six weeks."
    db_session.commit()
    assert "Return in four weeks." in visit.plan
    assert "Return in six weeks." not in visit.plan
    assert visit.phrase_uses[0].text_snapshot == "Return in four weeks."


def test_screening_reminders_calculate_and_dismiss_without_completion_claim(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify due prompts appear by gestational age and dismissal hides them."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    lmp = date.today() - timedelta(weeks=25)
    episode = create_pregnancy_episode(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        lmp,
    )
    reminders = screening_reminders(db_session, episode, date.today())
    assert {reminder["key"] for reminder in reminders} == {"glucose_tolerance"}
    dismiss_screening_reminder(
        db_session,
        episode,
        seeded_users[UserRole.PHYSICIAN],
        "glucose_tolerance",
    )
    db_session.commit()
    assert screening_reminders(db_session, episode, date.today()) == []
    assert episode.status is PregnancyEpisodeStatus.ACTIVE


def test_visit_route_save_exposes_next_action_prompt(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify the browser workflow saves a note and offers next actions."""

    patient = seed_patient(db_session, seeded_users[UserRole.PHYSICIAN])
    codes = seed_codes(db_session)
    episode = create_pregnancy_episode(
        db_session,
        seeded_users[UserRole.PHYSICIAN],
        patient.id,
        date.today() - timedelta(days=80),
    )
    db_session.commit()
    login_as(client, seeded_users[UserRole.PHYSICIAN])
    response = client.post(
        "/visits",
        data={
            "patient_id": patient.id,
            "visit_type": "prenatal",
            "pregnancy_episode_id": episode.id,
            "blood_pressure": "120/80",
            "weight_kg": "70",
            "fundal_height_cm": "12",
            "fetal_heart_tones": "150 bpm",
            "hpi": "Doing well.",
            "assessment": "Stable.",
            "plan": "Continue.",
            "diagnosis_code_ids": [codes[0].id],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    visit = db_session.scalar(select(Visit).where(Visit.patient_id == patient.id))
    assert visit is not None
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "What would you like to do next?" in page.text