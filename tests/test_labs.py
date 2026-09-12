"""Automated coverage for Lab Orders, results, files, and catalog management."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LabOrder,
    LabOrderStatus,
    LabResult,
    User,
    UserRole,
    Visit,
    VisitType,
)
from app.services.auth import create_user
from app.services.clinical import create_pregnancy_episode, create_visit
from app.services.labs import (
    LAB_UPLOAD_ROOT,
    create_lab_order_set,
    create_lab_result,
    create_lab_test_definition,
    ensure_default_lab_test_definitions,
    get_lab_order_sets,
    get_lab_test_definitions,
    get_pending_lab_orders,
    order_lab_tests,
    review_lab_result,
    update_lab_order_set,
    update_lab_test_definition,
)
import app.services.labs as labs_service
from app.services.patients import create_patient


def login_as(client: TestClient, user: User) -> None:
    response = client.post(
        "/login",
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient(db: Session, user: User):
    patient = create_patient(
        db=db,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": "Lab Patient",
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db.commit()
    return patient


def seed_visit(db: Session, user: User):
    patient = seed_patient(db, user)
    visit = create_visit(
        db,
        user,
        patient.id,
        VisitType.PROBLEM_FOCUSED,
        None,
        {"blood_pressure": "120/80"},
        None,
        None,
        "Lab visit",
        "Assessment",
        "Plan",
        [],
    )
    db.commit()
    return patient, visit


def test_default_lab_catalog_and_admin_editing(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    admin = seeded_users[UserRole.CLINIC_ADMIN]
    physician = seeded_users[UserRole.PHYSICIAN]
    definitions = ensure_default_lab_test_definitions(db_session, admin.clinic_id)
    db_session.commit()
    assert {definition.name for definition in definitions} == {
        "CBC",
        "Urinalysis",
        "Glucose screen",
        "Rh/blood type",
        "STI panel",
        "Pap/HPV",
        "TSH",
    }
    with pytest.raises(PermissionError):
        create_lab_test_definition(db_session, physician, "Ferritin", "")
    added = create_lab_test_definition(db_session, admin, "Ferritin", "Iron stores")
    updated = update_lab_test_definition(
        db_session,
        added,
        admin,
        "Ferritin",
        "Updated iron stores",
        False,
    )
    db_session.flush()
    active_definitions = [
        definition
        for definition in get_lab_test_definitions(
            db_session,
            admin.clinic_id,
            active_only=True,
        )
    ]
    assert updated.description == "Updated iron stores"
    assert updated.active is False
    assert all(definition.name != "Ferritin" for definition in active_definitions)


def test_order_set_creates_multiple_patient_visit_orders_and_pending_view(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    physician = seeded_users[UserRole.PHYSICIAN]
    patient, visit = seed_visit(db_session, physician)
    definitions = get_lab_test_definitions(db_session, physician.clinic_id, active_only=True)
    order_set = create_lab_order_set(
        db_session,
        seeded_users[UserRole.CLINIC_ADMIN],
        "New OB Panel",
        "Starter prenatal panel",
        [definition.id for definition in definitions[:3]],
    )
    db_session.commit()
    orders = order_lab_tests(
        db_session,
        physician,
        visit.id,
        [],
        order_set.id,
    )
    db_session.commit()
    assert len(orders) == 3
    assert {order.patient_id for order in orders} == {patient.id}
    assert all(order.status is LabOrderStatus.ORDERED for order in orders)
    assert len(get_pending_lab_orders(db_session, physician)) == 3
    login_as(client, physician)
    panel = client.get(f"/visits/{visit.id}/labs/order-panel")
    assert panel.status_code == 200
    assert "Create lab orders" in panel.text
    pending = client.get("/labs/pending")
    assert pending.status_code == 200
    assert "New OB Panel" in pending.text or "CBC" in pending.text


def test_resulted_and_reviewed_statuses_require_physician_signoff(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    physician = seeded_users[UserRole.PHYSICIAN]
    nurse = seeded_users[UserRole.NURSE_MA]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    order = order_lab_tests(db_session, physician, visit.id, [definition.id])[0]
    result = create_lab_result(
        db_session,
        order,
        nurse,
        manual_value="Negative",
    )
    db_session.commit()
    assert order.status is LabOrderStatus.RESULTED
    assert get_pending_lab_orders(db_session, physician) == []
    with pytest.raises(PermissionError, match="physician"):
        review_lab_result(db_session, result, nurse)
    review_lab_result(db_session, result, physician)
    db_session.commit()
    assert order.status is LabOrderStatus.REVIEWED
    assert result.reviewed_by_user_id == physician.id
    assert result.reviewed_at is not None


def test_result_upload_is_validated_stored_private_and_authorized(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labs_service, "LAB_UPLOAD_ROOT", tmp_path / "private-labs")
    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    order = order_lab_tests(db_session, physician, visit.id, [definition.id])[0]
    result = create_lab_result(
        db_session,
        order,
        physician,
        filename="../../result.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7\nsecure result",
    )
    db_session.commit()
    assert result.file_path is not None
    assert Path(result.file_path).name == result.file_path
    stored = (labs_service.LAB_UPLOAD_ROOT / result.file_path)
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"%PDF-")
    assert stored.stat().st_mode & 0o777 == 0o600
    invalid_order = order_lab_tests(
        db_session,
        physician,
        visit.id,
        [definition.id],
    )[0]
    with pytest.raises(ValueError, match="PDF"):
        create_lab_result(
            db_session,
            order=invalid_order,
            actor=physician,
            filename="bad.txt",
            content_type="text/plain",
            content=b"not a lab result",
        )
    login_as(client, physician)
    download = client.get(f"/lab-results/{result.id}/file")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")


def test_lab_file_route_rejects_non_clinical_roles(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labs_service, "LAB_UPLOAD_ROOT", tmp_path / "private-labs")
    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    order = order_lab_tests(db_session, physician, visit.id, [definition.id])[0]
    result = create_lab_result(
        db_session,
        order,
        physician,
        filename="result.png",
        content_type="image/png",
        content=b"\x89PNG\r\n\x1a\nprivate",
    )
    db_session.commit()
    login_as(client, seeded_users[UserRole.FRONT_DESK])
    response = client.get(f"/lab-results/{result.id}/file")
    assert response.status_code == 403


def test_admin_can_edit_order_set_membership(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    admin = seeded_users[UserRole.CLINIC_ADMIN]
    definitions = get_lab_test_definitions(db_session, admin.clinic_id, active_only=True)
    order_set = create_lab_order_set(
        db_session,
        admin,
        "Custom Panel",
        "Initial",
        [definitions[0].id],
    )
    db_session.commit()
    update_lab_order_set(
        db_session,
        order_set,
        admin,
        "Expanded Panel",
        "Updated",
        [definitions[0].id, definitions[1].id],
        True,
    )
    db_session.commit()
    sets = get_lab_order_sets(db_session, admin.clinic_id)
    assert sets[0].name == "Expanded Panel"
    assert {definition.id for definition in sets[0].test_definitions} == {
        definitions[0].id,
        definitions[1].id,
    }


def test_lab_admin_screen_is_restricted(
    client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    login_as(client, seeded_users[UserRole.CLINIC_ADMIN])
    assert client.get("/admin/labs").status_code == 200
    login_as(client, seeded_users[UserRole.PHYSICIAN])
    assert client.get("/admin/labs").status_code == 403