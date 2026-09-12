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