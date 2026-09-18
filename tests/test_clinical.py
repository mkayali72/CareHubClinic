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
    DeliveryOutcome,
    Patient,
    PhraseTemplate,
    PregnancyEpisodeStatus,
    ProcedureType,
    ReminderDismissal,
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
    get_patient_visits,
    gestational_age,
    insert_phrase_into_visit,
    is_visit_locked,
    pregnancy_trend,
    screening_reminders,
    update_visit,
    update_phrase_template,
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
    visit_date: date | None = None,
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
            "fetal_heart_tones": "145",
            "fetal_position": "cephalic",
            "ultrasound_efw_grams": "620",
        },
        {"menstrual_history": "Regular"},
        "Patient reports good fetal movement.",
        "Stable prenatal course.",
        "Continue routine follow-up.",
        code_ids,
        visit_date=visit_date,
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
    assert age["days"] == 5
    assert age["display"] == "20w 5d"


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
            "fetal_heart_tones": "150",
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


@pytest.mark.parametrize("visit_type", list(VisitType))
def test_all_visit_types_save_only_their_structured_field_set(
    seeded_users: dict[UserRole, User],
    db_session: Session,
    visit_type: VisitType,
) -> None:
    """Test 63: each visit template stores shared and type-specific fields."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    episode = create_pregnancy_episode(
        db_session,
        physician,
        patient.id,
        date.today() - timedelta(days=80),
    )
    visit = create_visit(
        db_session,
        physician,
        patient.id,
        visit_type,
        episode.id if visit_type is VisitType.PRENATAL else None,
        {"blood_pressure": "121/81", "weight_kg": "69", "height_cm": "165"},
        {"fundal_height_cm": "18", "ultrasound_afi_cm": "12"},
        {"menstrual_history": "Regular", "pap_due_date": date(2027, 4, 1)},
        "HPI",
        "Assessment",
        "Plan",
        [],
    )
    db_session.commit()
    reloaded = db_session.get(Visit, visit.id)
    assert reloaded is not None
    assert reloaded.vitals["blood_pressure"] == "121/81"
    if visit_type is VisitType.PRENATAL:
        assert reloaded.prenatal_data["fundal_height_cm"] == 18.0
        assert reloaded.gyn_data == {}
    elif visit_type is VisitType.GYN_ANNUAL:
        assert reloaded.gyn_data["pap_due_date"] == "2027-04-01"
        assert reloaded.prenatal_data == {}
    else:
        assert reloaded.prenatal_data == {}
        assert reloaded.gyn_data == {}


def test_gestational_age_uses_original_and_corrected_dating_at_multiple_points(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 64: early, near-term, and post-original-EDD corrected dating."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    lmp = date.today() - timedelta(days=10)
    episode = create_pregnancy_episode(db_session, physician, patient.id, lmp)
    assert gestational_age(episode, lmp + timedelta(days=10))["display"] == "1w 3d"
    assert gestational_age(episode, lmp + timedelta(days=273))["display"] == "39w 0d"
    episode.corrected_edd = lmp + timedelta(days=287)
    assert gestational_age(episode, lmp + timedelta(days=283))["display"] == "39w 3d"


def test_prenatal_ultrasound_fields_save_and_reload(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 65: EFW, AFI, placenta, presentation, and biometry persist."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(days=150)
    )
    visit = create_visit(
        db_session,
        physician,
        patient.id,
        VisitType.PRENATAL,
        episode.id,
        {},
        {
            "ultrasound_efw_grams": "1750",
            "ultrasound_afi_cm": "13.5",
            "ultrasound_placenta_location": "Posterior",
            "ultrasound_presentation": "Cephalic",
            "ultrasound_biometry": "BPD 72 mm; HC 268 mm",
        },
        None,
        "",
        "",
        "",
        [],
    )
    db_session.commit()
    reloaded = db_session.get(Visit, visit.id)
    assert reloaded is not None
    assert reloaded.prenatal_data["ultrasound"] == {
        "efw_grams": 1750.0,
        "afi_cm": 13.5,
        "placenta_location": "Posterior",
        "presentation": "Cephalic",
        "biometry": "BPD 72 mm; HC 268 mm",
    }


def test_pregnancy_trend_orders_by_visit_date_not_entry_order(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 66: trend points include all visits in clinical-date order."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(days=200)
    )
    newer = make_visit(
        db_session,
        physician,
        patient,
        episode.id,
        [],
        visit_date=date.today() - timedelta(days=20),
    )
    newer.vitals["weight_kg"] = 80.0
    older = make_visit(
        db_session,
        physician,
        patient,
        episode.id,
        [],
        visit_date=date.today() - timedelta(days=60),
    )
    older.vitals["weight_kg"] = 70.0
    db_session.commit()
    points = pregnancy_trend(db_session, episode)
    assert [point["date"] for point in points] == [
        (date.today() - timedelta(days=60)).isoformat(),
        (date.today() - timedelta(days=20)).isoformat(),
    ]
    assert [point["weight_kg"] for point in points] == [70.0, 80.0]


def test_screening_reminders_are_prenatal_and_gestational_age_specific(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 67: reminders trigger at due gestational ages, not on gyn visits."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    due_episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(weeks=37)
    )
    early_episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(weeks=20)
    )
    assert {item["key"] for item in screening_reminders(db_session, due_episode)} == {
        "glucose_tolerance",
        "rhogam",
        "group_b_strep",
    }
    assert screening_reminders(db_session, early_episode) == []
    assert (
        screening_reminders(
            db_session,
            due_episode,
            visit_type=VisitType.GYN_ANNUAL,
        )
        == []
    )


def test_dismissing_screening_reminder_only_creates_ui_dismissal(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 68: dismissal hides the prompt without recording completion."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(weeks=25)
    )
    before_visit_count = len(get_patient_visits(db_session, physician, patient.id))
    dismissal = dismiss_screening_reminder(
        db_session, episode, physician, "glucose_tolerance"
    )
    db_session.commit()
    assert db_session.scalar(
        select(ReminderDismissal).where(ReminderDismissal.id == dismissal.id)
    )
    assert screening_reminders(db_session, episode) == []
    assert episode.status is PregnancyEpisodeStatus.ACTIVE
    assert len(get_patient_visits(db_session, physician, patient.id)) == before_visit_count
    assert not hasattr(episode, "glucose_tolerance_completed")


def test_separate_pregnancy_episodes_keep_visits_isolated(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 69: visits never cross-contaminate separate pregnancy episodes."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    first = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(days=300)
    )
    second = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(days=100)
    )
    first_visit = make_visit(db_session, physician, patient, first.id, [])
    second_visit = make_visit(db_session, physician, patient, second.id, [])
    db_session.commit()
    assert [visit.id for visit in first.visits] == [first_visit.id]
    assert [visit.id for visit in second.visits] == [second_visit.id]
    assert [point for point in pregnancy_trend(db_session, first)] == [
        point for point in pregnancy_trend(db_session, first)
    ]
    assert len(pregnancy_trend(db_session, first)) == 1
    assert len(pregnancy_trend(db_session, second)) == 1


def test_delivery_outcome_is_linked_and_visible_with_episode_history(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 70: delivery details render alongside the episode's visits."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    episode = create_pregnancy_episode(
        db_session, physician, patient.id, date.today() - timedelta(days=280)
    )
    visit = make_visit(db_session, physician, patient, episode.id, [])
    create_delivery_outcome(
        db_session,
        episode,
        physician,
        date.today(),
        "vaginal",
        "None",
        3220,
        8,
        9,
    )
    db_session.commit()
    assert isinstance(episode.delivery_outcome, DeliveryOutcome)
    login_as(client, physician)
    response = client.get(f"/visits/{visit.id}")
    assert response.status_code == 200
    assert "Delivery outcome" in response.text
    assert "Vaginal" in response.text


def test_invalid_icd10_rejected_and_valid_code_displays(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 71: diagnosis selection rejects unknown IDs and renders valid codes."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    codes = seed_codes(db_session)
    with pytest.raises(ValueError, match="diagnosis"):
        make_visit(db_session, physician, patient, None, [999999])
    visit = make_visit(db_session, physician, patient, None, [codes[2].id])
    db_session.commit()
    login_as(client, physician)
    response = client.get(f"/visits/{visit.id}")
    assert response.status_code == 200
    assert "Z01.419" in response.text


def test_phrase_template_is_shared_between_physicians_and_snapshotted(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 72: clinic sharing works while prior notes retain old phrase text."""

    physician = seeded_users[UserRole.PHYSICIAN]
    second_physician = create_user(
        db_session,
        clinic_id=physician.clinic_id,
        username="second_physician",
        password="Valid-Test-Password1",
        full_name="Second Physician",
        role=UserRole.PHYSICIAN,
        actor=physician,
    )
    patient = seed_patient(db_session, physician)
    visit = make_visit(db_session, physician, patient, None, [])
    template = create_phrase_template(
        db_session, physician, "Shared plan", "Return in four weeks."
    )
    insert_phrase_into_visit(db_session, visit, template, second_physician, "plan")
    update_phrase_template(
        db_session, template, physician, "Shared plan", "Return in six weeks."
    )
    db_session.commit()
    assert "Return in four weeks." in visit.plan
    assert "Return in six weeks." not in visit.plan
    assert visit.phrase_uses[0].text_snapshot == "Return in four weeks."


def test_locked_visit_api_rejects_direct_field_edit(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 73: the update API rejects direct edits after the lock window."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = make_visit(db_session, physician, patient, None, [])
    visit.created_at = datetime.now(timezone.utc) - VISIT_LOCK_WINDOW - timedelta(minutes=1)
    original_hpi = visit.hpi
    db_session.commit()
    login_as(client, physician)
    response = client.post(
        f"/visits/{visit.id}",
        data={
            "visit_type": "problem_focused",
            "hpi": "Attempted direct replacement",
            "assessment": "Changed",
            "plan": "Changed",
        },
    )
    assert response.status_code == 403
    assert visit.hpi == original_hpi


def test_amendment_preserves_original_and_displays_attribution(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 74: locked note amendments are separately attributed and visible."""

    physician = seeded_users[UserRole.PHYSICIAN]
    nurse = seeded_users[UserRole.NURSE_MA]
    patient = seed_patient(db_session, physician)
    visit = make_visit(db_session, physician, patient, None, [])
    visit.created_at = datetime.now(timezone.utc) - VISIT_LOCK_WINDOW - timedelta(minutes=1)
    original_hpi = visit.hpi
    db_session.commit()
    login_as(client, nurse)
    response = client.post(
        f"/visits/{visit.id}/amendments",
        data={"content": "Clarification entered by nurse."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.expire_all()
    reloaded = db_session.get(Visit, visit.id)
    assert reloaded is not None
    assert reloaded.hpi == original_hpi
    assert reloaded.amendments[0].content == "Clarification entered by nurse."
    assert reloaded.amendments[0].amended_by_user.full_name == nurse.full_name
    page = client.get(response.headers["location"])
    assert nurse.full_name in page.text


@pytest.mark.parametrize("procedure_type", list(ProcedureType))
def test_each_procedure_type_links_to_the_visit(
    seeded_users: dict[UserRole, User],
    db_session: Session,
    procedure_type: ProcedureType,
) -> None:
    """Test 75: every supported structured procedure persists on its visit."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = make_visit(db_session, physician, patient, None, [])
    procedure = create_procedure_record(
        db_session,
        visit,
        physician,
        procedure_type,
        {"notes": f"Recorded {procedure_type.value}."},
    )
    db_session.commit()
    assert procedure.visit_id == visit.id
    assert procedure.procedure_type is procedure_type
    assert visit.procedures[0].details["notes"] == f"Recorded {procedure_type.value}."


def test_partial_visit_save_keeps_the_fields_that_were_entered(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 76: the implemented partial create saves entered values without requiring every field."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = create_visit(
        db_session,
        physician,
        patient.id,
        VisitType.PROBLEM_FOCUSED,
        None,
        {"blood_pressure": "116/74"},
        None,
        None,
        "Only the available history was entered.",
        "",
        "",
        [],
    )
    db_session.commit()
    saved = db_session.get(Visit, visit.id)
    assert saved is not None
    assert saved.vitals["blood_pressure"] == "116/74"
    assert saved.hpi == "Only the available history was entered."
    assert saved.assessment == ""
    assert saved.plan == ""