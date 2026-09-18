"""Automated coverage for Lab Orders, results, files, and catalog management."""

from datetime import date, timedelta
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LabOrder,
    LabOrderStatus,
    LabResult,
    LabTestDefinition,
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
    get_visit_lab_orders,
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
        data={"username": user.username, "password": "Valid-Test-Password1"},
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


PDF_RESULT = b"%PDF-1.7\nvalid lab result\n%%EOF"
JPG_RESULT = b"\xff\xd8\xff\xe0valid jpeg result\xff\xd9"
XSS_PAYLOAD = '<script>alert("lab-xss")</script>'
SQL_PAYLOAD = "' OR 1=1 --"


def make_lab_order(
    db_session: Session,
    user: User,
    visit: Visit,
    definition: LabTestDefinition,
) -> LabOrder:
    """Create one ordered test for the numbered Prompt 7.T cases."""

    return order_lab_tests(
        db_session,
        user,
        visit.id,
        [definition.id],
    )[0]


def test_39_upload_endpoint_rejects_disallowed_and_oversized_files_and_authorizes_valid_files(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 39: enforce upload security server-side and restrict retrieval."""

    monkeypatch.setattr(labs_service, "LAB_UPLOAD_ROOT", tmp_path / "private-labs")
    physician = seeded_users[UserRole.PHYSICIAN]
    nurse = seeded_users[UserRole.NURSE_MA]
    front_desk = seeded_users[UserRole.FRONT_DESK]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    disallowed_order = make_lab_order(db_session, physician, visit, definition)
    oversized_order = make_lab_order(db_session, physician, visit, definition)
    pdf_order = make_lab_order(db_session, physician, visit, definition)
    jpg_order = make_lab_order(db_session, physician, visit, definition)
    db_session.commit()
    login_as(client, physician)

    disallowed = client.post(
        f"/lab-orders/{disallowed_order.id}/result",
        files={"result_file": ("result.txt", b"not allowed", "text/plain")},
    )
    assert disallowed.status_code == 422
    oversized = client.post(
        f"/lab-orders/{oversized_order.id}/result",
        files={
            "result_file": (
                "oversized.pdf",
                b"%PDF-" + b"0" * labs_service.LAB_RESULT_MAX_BYTES,
                "application/pdf",
            )
        },
    )
    assert oversized.status_code == 422
    assert disallowed_order.result is None
    assert oversized_order.result is None

    valid_pdf = client.post(
        f"/lab-orders/{pdf_order.id}/result",
        files={"result_file": ("report.pdf", PDF_RESULT, "application/pdf")},
    )
    valid_jpg = client.post(
        f"/lab-orders/{jpg_order.id}/result",
        files={"result_file": ("report.jpg", JPG_RESULT, "image/jpeg")},
    )
    assert valid_pdf.status_code == 200
    assert valid_jpg.status_code == 200
    db_session.expire_all()
    pdf_result = db_session.scalar(
        select(LabResult).where(LabResult.lab_order_id == pdf_order.id)
    )
    jpg_result = db_session.scalar(
        select(LabResult).where(LabResult.lab_order_id == jpg_order.id)
    )
    assert pdf_result is not None and jpg_result is not None

    assert client.get(f"/lab-results/{pdf_result.id}/file").content == PDF_RESULT
    login_as(client, nurse)
    assert client.get(f"/lab-results/{jpg_result.id}/file").content == JPG_RESULT
    login_as(client, front_desk)
    assert client.get(f"/lab-results/{pdf_result.id}/file").status_code == 403


def test_40_lab_text_fields_use_parameterized_queries_and_template_escaping(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 40: SQL/XSS payloads remain data in every lab text input."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    physician = seeded_users[UserRole.PHYSICIAN]
    definition = create_lab_test_definition(
        db_session,
        admin,
        XSS_PAYLOAD,
        SQL_PAYLOAD,
    )
    definitions = get_lab_test_definitions(db_session, admin.clinic_id)
    assert [item.id for item in definitions if item.id == definition.id] == [definition.id]
    assert all(item.name != SQL_PAYLOAD for item in definitions)
    order_set = create_lab_order_set(
        db_session,
        admin,
        XSS_PAYLOAD + " bundle",
        SQL_PAYLOAD,
        [definition.id],
    )
    patient, visit = seed_visit(db_session, physician)
    order = make_lab_order(db_session, physician, visit, definition)
    create_lab_result(
        db_session,
        order,
        physician,
        manual_value=f"{XSS_PAYLOAD} {SQL_PAYLOAD}",
    )
    db_session.commit()
    login_as(client, admin)
    admin_page = client.get("/admin/labs")
    assert admin_page.status_code == 200
    assert XSS_PAYLOAD not in admin_page.text
    assert "&lt;script&gt;" in admin_page.text
    login_as(client, physician)
    panel = client.get(f"/visits/{visit.id}/labs/order-panel")
    assert panel.status_code == 200
    assert XSS_PAYLOAD not in panel.text
    assert "&lt;script&gt;" in panel.text
    assert "&#39; OR 1=1 --" in panel.text
    assert order_set.name == XSS_PAYLOAD + " bundle"
    assert order_set.description == SQL_PAYLOAD
    assert patient.id == visit.patient_id


def test_77_single_test_and_full_new_ob_panel_link_orders_to_visit(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 77: individual and complete order-set ordering create correct rows."""

    physician = seeded_users[UserRole.PHYSICIAN]
    admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient, visit = seed_visit(db_session, physician)
    definitions = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )
    panel = create_lab_order_set(
        db_session,
        admin,
        "New OB Panel",
        "Full prenatal starter panel",
        [definition.id for definition in definitions],
    )
    single = make_lab_order(db_session, physician, visit, definitions[0])
    bundle_orders = order_lab_tests(db_session, physician, visit.id, [], panel.id)
    db_session.commit()
    persisted = list(
        db_session.scalars(
            select(LabOrder).where(
                LabOrder.visit_id == visit.id,
                LabOrder.patient_id == patient.id,
            )
        )
    )
    assert len(bundle_orders) == len(definitions)
    assert len(persisted) == len(definitions) + 1
    assert single.order_set_id is None
    assert {order.order_set_id for order in bundle_orders} == {panel.id}
    assert {order.lab_test_definition_id for order in bundle_orders} == {
        definition.id for definition in definitions
    }
    assert all(order.visit_id == visit.id for order in persisted)


def test_78_htmx_lab_panel_returns_fragment_without_replacing_in_progress_note_form(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 78: ordering mid-note targets only the lab panel, not the note form."""

    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    login_as(client, physician)
    workspace = client.get(f"/visits/{visit.id}")
    assert workspace.status_code == 200
    assert 'hx-target="#lab-order-panel"' in workspace.text
    # A browser can have unsaved textarea content here; the HTMX response is
    # deliberately scoped to the empty panel target and contains no note fields.
    response = client.post(
        f"/visits/{visit.id}/labs/orders",
        data={"definition_ids": [str(definition.id)]},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Lab orders created." in response.text
    assert 'name="hpi"' not in response.text
    assert 'name="assessment"' not in response.text
    assert 'name="plan"' not in response.text
    assert len(get_visit_lab_orders(db_session, physician, visit.id)) == 1


def test_79_manual_file_and_combined_lab_results_persist_and_render(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 79: manual-only, file-only, and combined results are retained."""

    monkeypatch.setattr(labs_service, "LAB_UPLOAD_ROOT", tmp_path / "private-labs")
    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definitions = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[:3]
    manual_order = make_lab_order(db_session, physician, visit, definitions[0])
    file_order = make_lab_order(db_session, physician, visit, definitions[1])
    combined_order = make_lab_order(db_session, physician, visit, definitions[2])
    create_lab_result(db_session, manual_order, physician, manual_value="Negative")
    create_lab_result(
        db_session,
        file_order,
        physician,
        filename="file.pdf",
        content_type="application/pdf",
        content=PDF_RESULT,
    )
    create_lab_result(
        db_session,
        combined_order,
        physician,
        manual_value="See attached report",
        filename="combined.pdf",
        content_type="application/pdf",
        content=PDF_RESULT,
    )
    db_session.commit()
    login_as(client, physician)
    panel = client.get(f"/visits/{visit.id}/labs/order-panel")
    assert panel.status_code == 200
    assert "Negative" in panel.text
    assert "See attached report" in panel.text
    for order, expected_value, expected_file in (
        (manual_order, "Negative", None),
        (file_order, None, "file.pdf"),
        (combined_order, "See attached report", "combined.pdf"),
    ):
        db_session.refresh(order)
        assert order.result is not None
        assert order.result.manual_value == expected_value
        assert (order.result.original_filename if order.result.file_path else None) == expected_file


def test_80_retrieved_uploaded_result_is_unchanged_after_refetch(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 80: repeated authorized reads return the same stored bytes."""

    monkeypatch.setattr(labs_service, "LAB_UPLOAD_ROOT", tmp_path / "private-labs")
    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definition = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[0]
    order = make_lab_order(db_session, physician, visit, definition)
    result = create_lab_result(
        db_session,
        order,
        physician,
        filename="stable.pdf",
        content_type="application/pdf",
        content=PDF_RESULT,
    )
    db_session.commit()
    login_as(client, physician)
    first = client.get(f"/lab-results/{result.id}/file")
    time.sleep(0.02)
    db_session.expire_all()
    second = client.get(f"/lab-results/{result.id}/file")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content == PDF_RESULT


def test_81_reviewed_result_has_signoff_metadata_and_unreviewed_state_is_distinct(
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 81: physician review metadata and status are explicit."""

    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definitions = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[:2]
    unreviewed_order = make_lab_order(db_session, physician, visit, definitions[0])
    reviewed_order = make_lab_order(db_session, physician, visit, definitions[1])
    unreviewed = create_lab_result(
        db_session,
        unreviewed_order,
        physician,
        manual_value="Pending interpretation",
    )
    reviewed = create_lab_result(
        db_session,
        reviewed_order,
        physician,
        manual_value="Normal",
    )
    review_lab_result(db_session, reviewed, physician)
    db_session.commit()
    assert unreviewed.reviewed_by_user_id is None
    assert unreviewed.reviewed_at is None
    assert unreviewed_order.status is LabOrderStatus.RESULTED
    assert reviewed.reviewed_by_user_id == physician.id
    assert reviewed.reviewed_at is not None
    assert reviewed_order.status is LabOrderStatus.REVIEWED


def test_82_pending_labs_is_fresh_and_excludes_every_resulted_order(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Test 82: a fresh pending query removes an order immediately after result entry."""

    physician = seeded_users[UserRole.PHYSICIAN]
    _, visit = seed_visit(db_session, physician)
    definitions = get_lab_test_definitions(
        db_session,
        physician.clinic_id,
        active_only=True,
    )[:2]
    first = make_lab_order(db_session, physician, visit, definitions[0])
    second = make_lab_order(db_session, physician, visit, definitions[1])
    db_session.commit()
    login_as(client, physician)
    before = client.get("/labs/pending")
    assert before.status_code == 200
    assert definitions[0].name in before.text
    create_lab_result(db_session, first, physician, manual_value="Negative")
    db_session.commit()
    after = client.get("/labs/pending")
    assert after.status_code == 200
    assert definitions[0].name not in after.text
    assert definitions[1].name in after.text
    assert [order.id for order in get_pending_lab_orders(db_session, physician)] == [second.id]