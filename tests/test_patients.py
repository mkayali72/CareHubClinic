"""Automated coverage for the Patient Demographics module."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditAction, AuditLog, Patient, User, UserRole
from app.services.patients import create_patient


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a TestClient as one seeded staff user.

    Args:
        client: FastAPI test client.
        user: Seeded user whose credentials should be submitted.
    """

    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient(db_session: Session, actor: User, name: str = "Amina Hassan") -> Patient:
    """Create one patient fixture with structured clinical data.

    Args:
        db_session: Isolated test database session.
        actor: Staff user creating the patient.
        name: Patient display name.

    Returns:
        A committed Patient row.
    """

    patient = create_patient(
        db=db_session,
        clinic_id=actor.clinic_id,
        actor=actor,
        payload={
            "name": name,
            "date_of_birth": date(1992, 4, 18),
            "contact_info": {
                "phone": "+974 5555 0101",
                "email": "amina@example.invalid",
                "address": "Doha",
            },
            "insurance_info": {
                "provider": "Qatar Care",
                "member_id": "M-100",
                "group_number": "G-10",
            },
            "emergency_contact": {
                "name": "Omar Hassan",
                "relationship": "Spouse",
                "phone": "+974 5555 0102",
            },
            "allergies": [
                {"name": "Penicillin", "reaction": "Rash", "severity": "Moderate"}
            ],
            "current_medications": [
                {"name": "Folic acid", "dose": "400 mcg", "frequency": "Daily"}
            ],
            "contraception_method": "Copper IUD",
        },
    )
    db_session.commit()
    return patient


@pytest.mark.parametrize(
    "role",
    [
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.FRONT_DESK,
        UserRole.BILLING_CLERK,
        UserRole.CLINIC_ADMIN,
    ],
)
def test_patient_list_is_visible_to_all_allowed_roles(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    role: UserRole,
) -> None:
    """Verify every specified role can open the clinic patient list."""

    seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[role])

    response = client.get("/patients")

    assert response.status_code == 200
    assert "Amina Hassan" in response.text


def test_patient_api_projection_hides_sensitive_fields_from_billing(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify billing_clerk receives demographic fields only at the API layer."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    clinical_response = client.get(f"/api/patients/{patient.id}")
    assert clinical_response.status_code == 200
    assert "allergies" in clinical_response.json()
    assert "current_medications" in clinical_response.json()
    assert "contraception_method" in clinical_response.json()

    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    billing_response = client.get(f"/api/patients/{patient.id}")
    billing_data = billing_response.json()
    assert billing_response.status_code == 200
    assert billing_data["name"] == "Amina Hassan"
    assert "contact_info" in billing_data
    assert "insurance_info" in billing_data
    assert "allergies" not in billing_data
    assert "current_medications" not in billing_data
    assert "contraception_method" not in billing_data
    assert "emergency_contact" not in billing_data


def test_patient_create_and_edit_forms_use_structured_entries(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify htmx forms create and update structured patient data."""

    login_as(client, seeded_users[UserRole.FRONT_DESK])
    form_data = {
        "name": "Lina Ali",
        "date_of_birth": "1988-02-03",
        "contact_phone": "+974 5000 0001",
        "insurance_provider": "Wellness",
        "allergy_name": ["Latex"],
        "allergy_reaction": ["Hives"],
        "allergy_severity": ["Mild"],
        "medication_name": ["Vitamin D"],
        "medication_dose": ["1000 IU"],
        "medication_frequency": ["Daily"],
        "contraception_method": "Oral contraceptive",
    }
    create_response = client.post(
        "/patients",
        data=form_data,
        headers={"HX-Request": "true"},
    )

    assert create_response.status_code == 200
    assert create_response.headers["HX-Trigger"] == "patientsChanged"
    patient = db_session.scalar(select(Patient).where(Patient.name == "Lina Ali"))
    assert patient is not None
    assert patient.allergies == [
        {"name": "Latex", "reaction": "Hives", "severity": "Mild"}
    ]
    assert patient.current_medications == [
        {"name": "Vitamin D", "dose": "1000 IU", "frequency": "Daily"}
    ]

    update_response = client.post(
        f"/patients/{patient.id}/edit",
        data={
            "name": "Lina Al-Hassan",
            "date_of_birth": "1988-02-03",
            "contact_phone": "+974 5000 0002",
            "allergy_name": "Latex",
            "allergy_reaction": "Hives",
            "allergy_severity": "Severe",
            "medication_name": "Vitamin D",
            "medication_dose": "2000 IU",
            "medication_frequency": "Daily",
            "contraception_method": "None documented",
        },
        headers={"HX-Request": "true"},
    )
    assert update_response.status_code == 200
    db_session.refresh(patient)
    assert patient.name == "Lina Al-Hassan"
    assert patient.allergies[0]["severity"] == "Severe"
    assert patient.current_medications[0]["dose"] == "2000 IU"


def test_billing_cannot_write_sensitive_fields_even_if_posted(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify API-layer write filtering preserves sensitive fields for billing."""

    login_as(client, seeded_users[UserRole.BILLING_CLERK])
    response = client.post(
        "/patients",
        data={
            "name": "Billing Patient",
            "date_of_birth": "1990-01-01",
            "allergy_name": ["Injected allergy"],
            "medication_name": ["Injected medication"],
            "contraception_method": "Injected method",
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    patient = db_session.scalar(
        select(Patient).where(Patient.name == "Billing Patient")
    )
    assert patient is not None
    assert patient.allergies == []
    assert patient.current_medications == []
    assert patient.contraception_method is None


def test_patient_tabs_conditionally_show_billing(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify the Billing tab follows the clinic billing feature flag."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    clinic = seeded_users[UserRole.CLINIC_ADMIN].clinic
    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])

    disabled_response = client.get(f"/patients/{patient.id}")
    assert "Billing" not in disabled_response.text

    clinic.billing_module_enabled = True
    db_session.commit()
    enabled_response = client.get(f"/patients/{patient.id}")
    assert enabled_response.status_code == 200
    assert ">Billing<" in enabled_response.text
    assert "Coming soon" in client.get(
        f"/patients/{patient.id}?tab=billing"
    ).text


def test_patient_list_is_newest_first_and_clinic_scoped(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify list ordering and clinic isolation for the patient API."""

    first = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "First Patient")
    second = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Second Patient")
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    response = client.get("/api/patients")

    assert response.status_code == 200
    names = [patient["name"] for patient in response.json()["patients"]]
    assert names[:2] == [second.name, first.name]


def test_only_clinic_admin_can_soft_delete_patient_and_list_hides_it(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify patient deletion is authorized, audited, and removed from lists."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.FRONT_DESK])
    rejected = client.post(
        f"/patients/{patient.id}/delete",
        follow_redirects=False,
    )
    assert rejected.status_code == 403

    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])
    deleted = client.post(
        f"/patients/{patient.id}/delete",
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/patients"

    db_session.expire_all()
    retained = db_session.scalar(
        select(Patient)
        .where(Patient.id == patient.id)
        .execution_options(include_deleted=True)
    )
    assert retained is not None
    assert retained.deleted_at is not None
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "patient",
            AuditLog.entity_id == patient.id,
            AuditLog.action == AuditAction.DELETE,
        )
    )
    assert audit is not None
    assert audit.actor_user_id == seeded_users[UserRole.CLINIC_ADMIN].id

    login_as(client, seeded_users[UserRole.FRONT_DESK])
    assert patient.name not in client.get("/patients").text
    assert client.get("/api/patients").json()["patients"] == []