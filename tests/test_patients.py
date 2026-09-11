"""Automated coverage for the Patient Demographics module."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditAction, AuditLog, Clinic, Patient, User, UserRole
from app.services.audit import restore_record
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


def complete_patient_form(name: str = "Form Patient") -> dict[str, object]:
    """Return a valid form payload suitable for direct route tests.

    Args:
        name: Patient name to include in the form.

    Returns:
        A complete patient form mapping.
    """

    return {
        "name": name,
        "date_of_birth": "1991-05-12",
        "contact_phone": "+974 5555 0199",
        "contact_email": "form@example.invalid",
        "contact_address": "Doha",
        "insurance_provider": "Qatar Care",
        "insurance_member_id": "M-199",
        "insurance_group_number": "G-19",
        "emergency_name": "Form Contact",
        "emergency_relationship": "Sibling",
        "emergency_phone": "+974 5555 0198",
        "allergy_name": ["Latex"],
        "allergy_reaction": ["Hives"],
        "allergy_severity": ["Mild"],
        "medication_name": ["Vitamin D"],
        "medication_dose": ["1000 IU"],
        "medication_frequency": ["Daily"],
        "contraception_method": "None documented",
    }


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


def test_front_desk_patient_api_excludes_clinical_fields(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify front_desk receives no clinical fields through the direct API."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    response = client.get(f"/api/patients/{patient.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == patient.name
    assert data["date_of_birth"] == "1992-04-18"
    assert "contact_info" in data
    assert "insurance_info" in data
    assert "emergency_contact" not in data
    assert "allergies" not in data
    assert "current_medications" not in data
    assert "contraception_method" not in data


def test_billing_clerk_patient_api_returns_only_billing_projection(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify billing_clerk can retrieve demographics and insurance only."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[UserRole.BILLING_CLERK])

    response = client.get(f"/api/patients/{patient.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Amina Hassan"
    assert data["date_of_birth"] == "1992-04-18"
    assert data["contact_info"]["phone"] == "+974 5555 0101"
    assert data["insurance_info"]["provider"] == "Qatar Care"
    assert set(data) == {
        "id",
        "name",
        "date_of_birth",
        "contact_info",
        "insurance_info",
        "clinic_id",
        "created_at",
    }


@pytest.mark.parametrize(
    "role",
    [
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.FRONT_DESK,
        UserRole.CLINIC_ADMIN,
    ],
)
def test_clinical_roles_can_view_any_patient_in_their_clinic(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    role: UserRole,
) -> None:
    """Verify there is no per-doctor restriction within a clinic."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    login_as(client, seeded_users[role])

    response = client.get(f"/api/patients/{patient.id}")

    assert response.status_code == 200
    assert response.json()["name"] == patient.name


def test_patient_create_and_edit_forms_use_structured_entries(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify htmx forms create and update structured patient data."""

    login_as(client, seeded_users[UserRole.NURSE_MA])
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


def test_every_patient_crud_route_matches_role_permission_matrix(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Exercise every patient route directly for every staff role."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    non_admin_roles = [
        UserRole.PHYSICIAN,
        UserRole.NURSE_MA,
        UserRole.FRONT_DESK,
        UserRole.BILLING_CLERK,
    ]

    for role in [*non_admin_roles, UserRole.CLINIC_ADMIN]:
        login_as(client, seeded_users[role])
        assert client.get("/patients").status_code == 200
        assert client.get("/patients/rows").status_code == 200
        assert client.get("/api/patients").status_code == 200
        assert client.get("/api/patients/" + str(patient.id)).status_code == 200
        assert client.get("/patients/new").status_code == 200
        assert client.get(f"/patients/{patient.id}").status_code == 200
        assert client.get(f"/patients/{patient.id}/edit").status_code == 200

        created_name = f"CRUD {role.value}"
        create_response = client.post(
            "/patients",
            data=complete_patient_form(created_name),
            headers={"HX-Request": "true"},
        )
        assert create_response.status_code == 200

        update_response = client.post(
            f"/patients/{patient.id}/edit",
            data=complete_patient_form(f"Updated by {role.value}"),
            headers={"HX-Request": "true"},
        )
        assert update_response.status_code == 200

        delete_response = client.post(
            f"/patients/{patient.id}/delete",
            follow_redirects=False,
        )
        if role is UserRole.CLINIC_ADMIN:
            assert delete_response.status_code == 303
        else:
            assert delete_response.status_code == 403


def test_soft_deleted_patient_is_hidden_for_all_roles_and_restores_with_data(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify immediate hiding and the admin service restore mechanism."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    original_data = {
        "name": patient.name,
        "date_of_birth": patient.date_of_birth,
        "contact_info": patient.contact_info,
        "insurance_info": patient.insurance_info,
        "emergency_contact": patient.emergency_contact,
        "allergies": patient.allergies,
        "current_medications": patient.current_medications,
        "contraception_method": patient.contraception_method,
    }

    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])
    deleted = client.post(
        f"/patients/{patient.id}/delete",
        follow_redirects=False,
    )
    assert deleted.status_code == 303

    for role in UserRole:
        login_as(client, seeded_users[role])
        assert patient.name not in client.get("/patients").text
        assert all(
            item["id"] != patient.id
            for item in client.get("/api/patients").json()["patients"]
        )
        assert client.get(f"/api/patients/{patient.id}").status_code == 404

    db_session.expire_all()
    deleted_patient = db_session.scalar(
        select(Patient)
        .where(Patient.id == patient.id)
        .execution_options(include_deleted=True)
    )
    assert deleted_patient is not None
    restore_record(
        db=db_session,
        record=deleted_patient,
        actor=seeded_users[UserRole.CLINIC_ADMIN],
        entity_type="patient",
        entity_id=deleted_patient.id,
    )
    db_session.commit()
    db_session.expire_all()

    restored = db_session.scalar(select(Patient).where(Patient.id == patient.id))
    assert restored is not None
    assert restored.deleted_at is None
    for field_name, expected_value in original_data.items():
        assert getattr(restored, field_name) == expected_value
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == patient.id,
            AuditLog.action == AuditAction.RESTORE,
        )
    ) is not None


def test_patient_delete_retains_row_and_audit_links_without_orphaned_state(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify deletion does not hard-delete or corrupt patient-linked state."""

    patient = seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN])
    clinic_id = patient.clinic_id
    patient_id = patient.id
    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])

    response = client.post(
        f"/patients/{patient_id}/delete",
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    retained = db_session.scalar(
        select(Patient)
        .where(Patient.id == patient_id)
        .execution_options(include_deleted=True)
    )
    assert retained is not None
    assert retained.clinic_id == clinic_id
    assert retained.name == "Amina Hassan"
    audit_events = list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "patient",
                AuditLog.entity_id == patient_id,
            )
            .order_by(AuditLog.id)
        )
    )
    assert [event.action for event in audit_events] == [
        AuditAction.CREATE,
        AuditAction.DELETE,
    ]
    assert all(event.actor_user_id is not None for event in audit_events)
    assert db_session.get(Clinic, clinic_id) is not None


@pytest.mark.parametrize("missing_field", ["name", "date_of_birth"])
def test_patient_create_missing_required_fields_returns_clear_validation_error(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    missing_field: str,
) -> None:
    """Verify each required create field fails with a client validation response."""

    login_as(client, seeded_users[UserRole.FRONT_DESK])
    form_data = complete_patient_form("Validation Patient")
    form_data.pop(missing_field)

    response = client.post(
        "/patients",
        data=form_data,
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 422
    assert missing_field in response.text
    assert db_session.scalar(
        select(Patient).where(Patient.name == "Validation Patient")
    ) is None


def test_similar_patient_is_allowed_because_duplicate_detection_is_not_implemented(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Document the current duplicate behavior without silently adding a rule."""

    seed_patient(db_session, seeded_users[UserRole.CLINIC_ADMIN], "Amina Hassan")
    login_as(client, seeded_users[UserRole.FRONT_DESK])

    response = client.post(
        "/patients",
        data=complete_patient_form("Amina Hassan"),
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert db_session.query(Patient).filter(Patient.name == "Amina Hassan").count() == 2


def test_structured_clinical_fields_save_and_reload_with_multiple_entries(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Verify multiple allergy and medication rows survive API reload."""

    login_as(client, seeded_users[UserRole.PHYSICIAN])
    form_data = complete_patient_form("Multiple Entries Patient")
    form_data.update(
        {
            "allergy_name": ["Penicillin", "Latex"],
            "allergy_reaction": ["Rash", "Hives"],
            "allergy_severity": ["Moderate", "Mild"],
            "medication_name": ["Folic acid", "Vitamin D"],
            "medication_dose": ["400 mcg", "1000 IU"],
            "medication_frequency": ["Daily", "Weekly"],
            "contraception_method": "Copper IUD",
        }
    )
    create_response = client.post(
        "/patients",
        data=form_data,
        headers={"HX-Request": "true"},
    )
    assert create_response.status_code == 200

    patient = db_session.scalar(
        select(Patient).where(Patient.name == "Multiple Entries Patient")
    )
    assert patient is not None
    reload_response = client.get(f"/api/patients/{patient.id}")

    assert reload_response.status_code == 200
    data = reload_response.json()
    assert data["allergies"] == [
        {"name": "Penicillin", "reaction": "Rash", "severity": "Moderate"},
        {"name": "Latex", "reaction": "Hives", "severity": "Mild"},
    ]
    assert data["current_medications"] == [
        {"name": "Folic acid", "dose": "400 mcg", "frequency": "Daily"},
        {"name": "Vitamin D", "dose": "1000 IU", "frequency": "Weekly"},
    ]
    assert data["contraception_method"] == "Copper IUD"