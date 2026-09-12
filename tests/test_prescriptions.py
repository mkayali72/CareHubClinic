"""Automated coverage for the Prescriptions module."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditAction,
    AuditLog,
    MedicationDefinition,
    Patient,
    PregnancySafetyFlag,
    Prescription,
    User,
    UserRole,
    Visit,
    VisitType,
)
from app.services.clinical import create_pregnancy_episode, create_visit
from app.services.patients import create_patient
from app.services.prescriptions import (
    PrescriptionWarningRequired,
    create_medication_definition,
    create_prescription,
    ensure_default_medication_definitions,
    get_current_prescriptions,
    get_prescription_warnings,
    soft_delete_prescription,
)


def login_as(client: TestClient, user: User) -> None:
    """Authenticate one seeded user."""

    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient(db_session: Session, user: User) -> Patient:
    """Create a clinical patient with one structured allergy."""

    patient = create_patient(
        db_session,
        user.clinic_id,
        user,
        {
            "name": "Prescription Patient",
            "date_of_birth": date(1990, 2, 3),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [{"name": "Penicillin", "reaction": "Hives", "severity": "Severe"}],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    return patient


def seed_visit(db_session: Session, user: User, patient: Patient) -> Visit:
    """Create a minimal problem-focused visit."""

    visit = create_visit(
        db_session,
        user,
        patient.id,
        VisitType.PROBLEM_FOCUSED,
        None,
        {},
        None,
        None,
        "Medication discussion.",
        "Review.",
        "Follow instructions.",
        [],
    )
    db_session.commit()
    return visit


def test_starter_formulary_is_seeded_with_tri_state_safety_values(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """New clinics receive relevant medications and all safety flag values."""

    physician = seeded_users[UserRole.PHYSICIAN]
    definitions = ensure_default_medication_definitions(db_session, physician.clinic_id)
    db_session.commit()
    names = {definition.name for definition in definitions}
    flags = {definition.pregnancy_safety_flag for definition in definitions}
    assert {"Prenatal vitamin", "Ibuprofen", "Amoxicillin"} <= names
    assert {
        PregnancySafetyFlag.TRUE,
        PregnancySafetyFlag.FALSE,
        PregnancySafetyFlag.UNKNOWN,
    } <= flags


def test_safety_warning_requires_acknowledgment_then_persists_it(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Unsafe pregnancy medications warn first and record a physician override."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    create_pregnancy_episode(
        db_session,
        physician,
        patient.id,
        date.today() - timedelta(days=100),
    )
    visit = seed_visit(db_session, physician, patient)
    definition = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Unsafe test medication",
        "Test entry",
        "false",
        "unrelated",
    )
    with pytest.raises(PrescriptionWarningRequired) as error:
        create_prescription(
            db_session,
            physician,
            visit.id,
            definition.id,
            "1 tablet",
            "daily",
            "5 days",
        )
    assert "pregnancy" in error.value.warnings
    assert db_session.scalar(select(Prescription)) is None
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "1 tablet",
        "daily",
        "5 days",
        acknowledge_pregnancy_warning=True,
    )
    db_session.commit()
    assert prescription.pregnancy_warning_acknowledged is True
    assert prescription.allergy_warning_acknowledged is False


def test_unknown_pregnancy_safety_and_category_allergy_warnings_can_both_fire(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Unknown safety and a matching category require separate acknowledgments."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    create_pregnancy_episode(
        db_session,
        physician,
        patient.id,
        date.today() - timedelta(days=100),
    )
    visit = seed_visit(db_session, physician, patient)
    definition = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Category conflict medication",
        "Test entry",
        "unknown",
        "penicillin",
    )
    warnings = get_prescription_warnings(db_session, patient, definition)
    assert set(warnings) == {"pregnancy", "allergy"}
    with pytest.raises(PrescriptionWarningRequired) as error:
        create_prescription(
            db_session,
            physician,
            visit.id,
            definition.id,
            "1 dose",
            "once",
            "1 day",
            acknowledge_pregnancy_warning=True,
        )
    assert set(error.value.warnings) == {"allergy"}
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "1 dose",
        "once",
        "1 day",
        acknowledge_pregnancy_warning=True,
        acknowledge_allergy_warning=True,
    )
    db_session.commit()
    assert prescription.allergy_warning_acknowledged is True


def test_only_physician_can_confirm_and_current_view_excludes_soft_deleted(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Prescription confirmation is physician-only and active projections refresh."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    definition = ensure_default_medication_definitions(
        db_session,
        physician.clinic_id,
    )[0]
    with pytest.raises(PermissionError):
        create_prescription(
            db_session,
            seeded_users[UserRole.NURSE_MA],
            visit.id,
            definition.id,
            "1 tablet",
            "daily",
            "10 days",
        )
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "1 tablet",
        "daily",
        "10 days",
    )
    db_session.commit()
    assert get_current_prescriptions(db_session, physician, patient.id) == [prescription]
    soft_delete_prescription(db_session, prescription, seeded_users[UserRole.CLINIC_ADMIN])
    db_session.commit()
    assert get_current_prescriptions(db_session, physician, patient.id) == []
    retained = db_session.scalar(
        select(Prescription)
        .execution_options(include_deleted=True)
        .where(Prescription.id == prescription.id)
    )
    assert retained is not None
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "prescription",
            AuditLog.entity_id == prescription.id,
            AuditLog.action == AuditAction.DELETE,
        )
    ) is not None


def test_prescription_panel_summary_admin_and_print_routes_render(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Browser routes expose the slide-over, Summary, admin, and branded print view."""

    physician = seeded_users[UserRole.PHYSICIAN]
    clinic_admin = seeded_users[UserRole.CLINIC_ADMIN]
    clinic_admin.clinic.branding_reference = "/static/clinic-logo.svg"
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    definition = ensure_default_medication_definitions(db_session, physician.clinic_id)[0]
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "1 tablet",
        "daily",
        "7 days",
    )
    db_session.commit()

    login_as(client, physician)
    panel = client.get(f"/visits/{visit.id}/prescriptions/order-panel")
    assert panel.status_code == 200
    assert "Prescribe for this visit" in panel.text
    summary = client.get(f"/patients/{patient.id}")
    assert summary.status_code == 200
    assert definition.name in summary.text
    patient_tab = client.get(f"/patients/{patient.id}?tab=prescriptions")
    assert patient_tab.status_code == 200
    assert "Print / save PDF" in patient_tab.text
    printed = client.get(f"/prescriptions/{prescription.id}/print")
    assert printed.status_code == 200
    assert "clinic-logo.svg" in printed.text
    assert clinic_admin.clinic.name in printed.text

    login_as(client, clinic_admin)
    admin_page = client.get("/admin/prescriptions")
    assert admin_page.status_code == 200
    assert "Medication formulary" in admin_page.text


def test_non_clinical_roles_cannot_access_prescription_routes(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Front-desk and billing users cannot receive clinical prescription data."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    for role in (UserRole.FRONT_DESK, UserRole.BILLING_CLERK):
        login_as(client, seeded_users[role])
        assert client.get(f"/visits/{visit.id}/prescriptions/order-panel").status_code == 403
        assert client.get(f"/patients/{patient.id}/prescriptions").status_code == 403
        assert client.get(f"/patients/{patient.id}?tab=summary").status_code == 200
        assert "Active prescriptions" not in client.get(
            f"/patients/{patient.id}?tab=summary"
        ).text


def test_83_inline_slide_over_prescription_links_visit_and_patient(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 83: the inline POST creates a prescription for the current visit."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    definition = next(
        definition
        for definition in ensure_default_medication_definitions(
            db_session,
            physician.clinic_id,
        )
        if definition.name == "Prenatal vitamin"
    )

    login_as(client, physician)
    response = client.post(
        f"/visits/{visit.id}/prescriptions",
        data={
            "medication_definition_id": str(definition.id),
            "dosage": "1 capsule",
            "frequency": "daily",
            "duration": "30 days",
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Prescription confirmed and added to current medications." in response.text
    prescription = db_session.scalar(select(Prescription))
    assert prescription is not None
    assert prescription.visit_id == visit.id
    assert prescription.patient_id == patient.id
    assert prescription.medication_definition_id == definition.id


def test_84_unsafe_pregnancy_warning_is_only_active_pregnancy_scoped(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 84: unsafe medication warns with pregnancy and not without one."""

    physician = seeded_users[UserRole.PHYSICIAN]
    pregnant_patient = seed_patient(db_session, physician)
    non_pregnant_patient = seed_patient(db_session, physician)
    create_pregnancy_episode(
        db_session,
        physician,
        pregnant_patient.id,
        date.today() - timedelta(days=90),
    )
    pregnant_visit = seed_visit(db_session, physician, pregnant_patient)
    non_pregnant_visit = seed_visit(db_session, physician, non_pregnant_patient)
    definition = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Explicit unsafe test medication",
        "Test medication",
        "false",
        "unrelated",
    )

    pregnant_warnings = get_prescription_warnings(
        db_session,
        pregnant_patient,
        definition,
    )
    assert "pregnancy" in pregnant_warnings
    with pytest.raises(PrescriptionWarningRequired) as warning:
        create_prescription(
            db_session,
            physician,
            pregnant_visit.id,
            definition.id,
            "1 tablet",
            "daily",
            "5 days",
        )
    assert "pregnancy" in warning.value.warnings

    non_pregnant_warnings = get_prescription_warnings(
        db_session,
        non_pregnant_patient,
        definition,
    )
    assert "pregnancy" not in non_pregnant_warnings
    prescription = create_prescription(
        db_session,
        physician,
        non_pregnant_visit.id,
        definition.id,
        "1 tablet",
        "daily",
        "5 days",
    )
    db_session.commit()
    assert prescription.pregnancy_warning_acknowledged is False


def test_85_allergy_conflict_warns_and_non_conflicting_medication_does_not(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 85: allergy matching is warned while an unrelated category is not."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    conflicting = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Allergy conflict test medication",
        "Test medication",
        "true",
        "penicillin",
    )
    non_conflicting = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Allergy safe test medication",
        "Test medication",
        "true",
        "vitamin",
    )

    conflict_warnings = get_prescription_warnings(db_session, patient, conflicting)
    assert "allergy" in conflict_warnings
    with pytest.raises(PrescriptionWarningRequired) as warning:
        create_prescription(
            db_session,
            physician,
            visit.id,
            conflicting.id,
            "1 tablet",
            "daily",
            "5 days",
        )
    assert "allergy" in warning.value.warnings

    no_conflict_warnings = get_prescription_warnings(
        db_session,
        patient,
        non_conflicting,
    )
    assert "allergy" not in no_conflict_warnings
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        non_conflicting.id,
        "1 capsule",
        "daily",
        "30 days",
    )
    db_session.commit()
    assert prescription.allergy_warning_acknowledged is False


def test_86_printed_prescription_contains_all_clinic_and_prescriber_content(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 86: rendered print output contains the complete prescription."""

    physician = seeded_users[UserRole.PHYSICIAN]
    clinic = physician.clinic
    clinic.branding_reference = "/static/clinic-logo.svg"
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    definition = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Rendered print medication",
        "Medication description",
        "true",
        "unrelated",
    )
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "250 mg",
        "twice daily",
        "10 days",
    )
    db_session.commit()

    login_as(client, physician)
    response = client.get(f"/prescriptions/{prescription.id}/print")

    assert response.status_code == 200
    rendered = response.text
    for expected in (
        clinic.name,
        "clinic-logo.svg",
        patient.name,
        definition.name,
        "250 mg",
        "twice daily",
        "10 days",
        physician.full_name,
    ):
        assert expected in rendered
    assert "Print / Save as PDF" in rendered


def test_87_summary_updates_immediately_when_prescription_is_discontinued(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 87: Summary shows a new prescription, then removes its active view."""

    physician = seeded_users[UserRole.PHYSICIAN]
    patient = seed_patient(db_session, physician)
    visit = seed_visit(db_session, physician, patient)
    definition = create_medication_definition(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "Summary lifecycle medication",
        "Medication description",
        "true",
        "unrelated",
    )
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        definition.id,
        "5 mg",
        "every morning",
        "14 days",
    )
    db_session.commit()

    login_as(client, physician)
    added_summary = client.get(f"/patients/{patient.id}?tab=summary")
    assert added_summary.status_code == 200
    assert definition.name in added_summary.text
    assert "5 mg" in added_summary.text
    assert "every morning" in added_summary.text

    soft_delete_prescription(
        db_session,
        prescription,
        seeded_users[UserRole.CLINIC_ADMIN],
    )
    db_session.commit()

    discontinued_summary = client.get(f"/patients/{patient.id}?tab=summary")
    assert discontinued_summary.status_code == 200
    assert definition.name not in discontinued_summary.text
    assert "No active prescriptions." in discontinued_summary.text
    retained = db_session.scalar(
        select(Prescription)
        .execution_options(include_deleted=True)
        .where(Prescription.id == prescription.id)
    )
    assert retained is not None
    assert retained.deleted_at is not None