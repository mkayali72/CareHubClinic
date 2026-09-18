"""Dedicated application security hardening coverage."""

from dataclasses import replace
from datetime import date
import html
import logging
from pathlib import Path
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import create_app
from app.models import Clinic, LabResult, Patient, User, UserRole, VisitType
from app.services import auth as auth_service
from app.services.billing import create_fee_schedule_item, create_invoice
from app.services.clinical import create_visit
from app.services.csrf import enforce_csrf
from app.services.labs import (
    LAB_RESULT_MAX_BYTES,
    _validate_uploaded_file,
    create_lab_order_set,
    create_lab_test_definition,
    lab_file_path_for_result,
)
from app.services.patients import create_patient
from app.services.prescriptions import (
    create_medication_definition,
    create_prescription,
)
from app.services.scheduling import create_appointment_type


def database_override(db_session: Session):
    """Use the isolated test database for a security-only application."""

    yield db_session


@pytest.fixture()
def secure_client(db_session: Session):
    """Create a client with the real CSRF and license dependencies enabled."""

    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


def extract_csrf_token(response) -> str:
    """Extract the token exposed by the login or shared application shell."""

    match = re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        response.text,
    )
    assert match is not None, response.text
    return html.unescape(match.group(1))


def login_with_csrf(client: TestClient, user: User) -> str:
    """Log in through the real form-protected endpoint and refresh its token."""

    token = extract_csrf_token(client.get("/login"))
    response = client.post(
        "/login",
        data={
            "username": user.username,
            "password": "Valid-Test-Password1",
            "_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return extract_csrf_token(client.get("/welcome"))


def test_csrf_rejects_missing_tokens_and_accepts_session_bound_tokens(
    secure_client: TestClient,
    seeded_users: dict[UserRole, User],
) -> None:
    """Every state-changing request requires the browser's session token."""

    user = seeded_users[UserRole.CLINIC_ADMIN]
    login_page = secure_client.get("/login")
    token = extract_csrf_token(login_page)
    missing = secure_client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
    )
    assert missing.status_code == 403

    login = secure_client.post(
        "/login",
        data={
            "username": user.username,
            "password": "Valid-Test-Password1",
            "_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    fresh_token = extract_csrf_token(secure_client.get("/welcome"))
    blocked_write = secure_client.post(
        "/patients",
        data={"name": "CSRF blocked", "date_of_birth": "1990-01-01"},
    )
    assert blocked_write.status_code == 403

    accepted_write = secure_client.post(
        "/patients",
        data={
            "name": "CSRF accepted",
            "date_of_birth": "1990-01-01",
            "_csrf_token": fresh_token,
        },
    )
    assert accepted_write.status_code == 200


def test_csrf_dependency_is_registered_globally_for_all_write_routes() -> None:
    """The protection is app-wide rather than dependent on individual routers."""

    application = create_app()
    assert any(
        dependency.dependency is enforce_csrf
        for dependency in application.router.dependencies
    )


def test_35_production_session_cookie_requires_secure_transport(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production cookies require HTTPS even though TLS termination is external."""

    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, app_env="production"),
    )
    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/login")
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_login_endpoint_locks_out_repeated_failed_attempts(
    secure_client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Repeated bad passwords trigger the existing account lockout policy."""

    user = seeded_users[UserRole.PHYSICIAN]
    token = extract_csrf_token(secure_client.get("/login"))
    for _ in range(5):
        response = secure_client.post(
            "/login",
            data={
                "username": user.username,
                "password": "Wrong-Password1",
                "_csrf_token": token,
            },
        )
        assert response.status_code == 401
    correct_while_locked = secure_client.post(
        "/login",
        data={
            "username": user.username,
            "password": "Valid-Test-Password1",
            "_csrf_token": token,
        },
    )
    assert correct_while_locked.status_code == 401
    db_session.refresh(user)
    assert user.locked_until is not None


def test_36_error_conditions_do_not_log_or_return_secrets(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected, CSRF, and authentication errors stay free of sensitive data."""

    import app.main as main_module

    secret_values = (
        "password=correct-horse",
        "session-token-secret",
        "PHI Patient Qatar 123",
    )
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, app_env="production"),
    )
    application = create_app()

    @application.get("/security-test-sensitive-error")
    def sensitive_error():
        raise RuntimeError(" ".join(secret_values))

    application.dependency_overrides[get_db] = lambda: db_session
    with caplog.at_level(logging.ERROR):
        with TestClient(
            application,
            base_url="https://testserver",
            raise_server_exceptions=False,
        ) as client:
            unexpected = client.get(
                "/security-test-sensitive-error",
                headers={"Accept": "application/json"},
            )
            csrf = client.post(
                "/login",
                data={
                    "username": "unknown_user",
                    "password": secret_values[0],
                },
            )
            authentication = client.post(
                "/login",
                data={
                    "username": "unknown_user",
                    "password": secret_values[0],
                    "_csrf_token": extract_csrf_token(client.get("/login")),
                },
            )

    assert unexpected.status_code == 500
    assert csrf.status_code == 403
    assert authentication.status_code == 401
    combined_response_text = unexpected.text + csrf.text + authentication.text
    combined_logs = caplog.text
    for secret in secret_values:
        assert secret not in combined_response_text
        assert secret not in combined_logs


def test_inactivity_timeout_expires_authenticated_session(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle sessions expire even when the signed cookie itself has not aged out."""

    monkeypatch.setattr(
        auth_service,
        "settings",
        replace(auth_service.settings, session_inactivity_seconds=1),
    )
    user = seeded_users[UserRole.PHYSICIAN]
    response = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    time.sleep(1.1)
    expired = client.get("/welcome", follow_redirects=False)
    assert expired.status_code == 303
    assert expired.headers["location"] == "/login"


def test_production_errors_are_generic_while_development_can_expose_debug_detail(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production clients never receive exception messages or stack details."""

    import app.main as main_module

    def make_error_client(environment: str):
        monkeypatch.setattr(
            main_module,
            "settings",
            replace(main_module.settings, app_env=environment),
        )
        application = create_app()

        @application.get("/security-test-error")
        def security_test_error():
            raise RuntimeError("database-password=do-not-expose")

        application.dependency_overrides[get_db] = lambda: db_session
        return TestClient(application, raise_server_exceptions=False)

    with make_error_client("development") as development:
        debug_response = development.get("/security-test-error")
        assert debug_response.status_code == 500
        assert "database-password=do-not-expose" in debug_response.text

    with make_error_client("production") as production:
        safe_response = production.get(
            "/security-test-error",
            headers={"Accept": "application/json"},
        )
        assert safe_response.status_code == 500
        assert safe_response.json() == {"detail": "Internal server error."}
        assert "database-password" not in safe_response.text
        assert "Traceback" not in safe_response.text
        assert "/app/" not in safe_response.text
        assert "site-packages" not in safe_response.text


def test_xss_payload_is_escaped_and_no_unsafe_template_filter_exists(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """User-controlled patient text is escaped and templates do not bypass it."""

    user = seeded_users[UserRole.CLINIC_ADMIN]
    patient = create_patient(
        db_session,
        user.clinic_id,
        user,
        {
            "name": "<script>alert('xss')</script>",
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    login = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    response = client.get("/patients")
    assert response.status_code == 200
    assert "<script>alert('xss')</script>" not in response.text
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in response.text
    template_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app/templates").rglob("*.html")
    )
    assert "|safe" not in template_source
    assert patient.id is not None


def test_37_phi_is_absent_from_urls_across_rendered_routes(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Patient names and clinical details never become URL path/query values."""

    user = seeded_users[UserRole.CLINIC_ADMIN]
    phi_marker = "PHI_URL_SENTINEL_123"
    patient = create_patient(
        db_session,
        user.clinic_id,
        user,
        {
            "name": phi_marker,
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {"phone": "555-0100"},
            "insurance_info": {"provider": "Private Payer"},
            "emergency_contact": {"name": "Emergency Secret"},
            "allergies": [{"name": "Confidential Allergy", "reaction": "Private"}],
            "current_medications": [{"name": "Confidential Medication"}],
            "contraception_method": "Private Method",
        },
    )
    db_session.commit()
    assert client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    ).status_code == 303

    paths = [
        "/welcome",
        "/patients",
        f"/patients/{patient.id}",
        "/schedule",
        "/schedule/grid",
        "/queue",
        "/labs/pending",
        "/admin/labs",
        "/admin/prescriptions",
        "/admin/license",
        "/reports",
    ]
    for path in paths:
        response = client.get(path, follow_redirects=False)
        url_values = [str(response.url)]
        url_values.extend(re.findall(r'(?:href|action)="([^"]+)"', response.text))
        for value in url_values:
            assert phi_marker not in value
            assert "Confidential%20Allergy" not in value
            assert "Confidential%20Medication" not in value
            assert "Emergency%20Secret" not in value


def test_39_file_upload_validation_retest() -> None:
    """File extension, type, signature, and size checks remain enforced."""

    valid_pdf = b"%PDF-1.7\nvalid\n%%EOF"
    assert _validate_uploaded_file(
        "report.pdf",
        "application/pdf",
        valid_pdf,
    ) == ("report.pdf", "application/pdf")
    for filename, content_type, content in (
        ("report.txt", "text/plain", b"not allowed"),
        ("report.pdf", "application/pdf", b"not a pdf"),
        (
            "report.pdf",
            "application/pdf",
            b"%PDF-" + b"0" * LAB_RESULT_MAX_BYTES,
        ),
    ):
        with pytest.raises(ValueError):
            _validate_uploaded_file(filename, content_type, content)


def test_40_comprehensive_text_fields_remain_data_and_render_escaped(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Exercise text fields across patient, scheduling, clinical, lab, Rx, and billing."""

    xss = '<script>alert("prompt12")</script>'
    sql = "' OR 1=1 --"
    admin = seeded_users[UserRole.CLINIC_ADMIN]
    physician = seeded_users[UserRole.PHYSICIAN]
    patient = create_patient(
        db_session,
        physician.clinic_id,
        physician,
        {
            "name": xss,
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {"phone": xss, "email": sql},
            "insurance_info": {"provider": xss, "member_id": sql},
            "emergency_contact": {"name": xss, "relationship": sql, "phone": xss},
            "allergies": [{"name": xss, "reaction": sql, "severity": xss}],
            "current_medications": [{"name": xss, "dose": sql, "frequency": xss}],
            "contraception_method": xss,
        },
    )
    appointment_type = create_appointment_type(
        db_session,
        admin.clinic_id,
        admin,
        xss,
        30,
    )
    definition = create_lab_test_definition(db_session, admin, xss + " lab", sql)
    order_set = create_lab_order_set(
        db_session,
        admin,
        xss + " bundle",
        sql,
        [definition.id],
    )
    medication = create_medication_definition(
        db_session,
        admin,
        xss + " medication",
        sql,
        "false",
        xss,
    )
    visit = create_visit(
        db_session,
        physician,
        patient.id,
        VisitType.PROBLEM_FOCUSED,
        None,
        {},
        None,
        None,
        xss,
        sql,
        xss,
        [],
    )
    prescription = create_prescription(
        db_session,
        physician,
        visit.id,
        medication.id,
        xss,
        sql,
        xss,
        acknowledge_allergy_warning=True,
    )
    clinic = db_session.get(Clinic, admin.clinic_id)
    assert clinic is not None
    clinic.billing_module_enabled = True
    fee = create_fee_schedule_item(db_session, admin, xss + " fee", sql, "10")
    invoice = create_invoice(db_session, admin, visit.id, [fee.id], notes=xss)
    db_session.commit()

    assert appointment_type.name == xss
    assert order_set.description == sql
    assert prescription.dosage == xss
    assert invoice.notes == xss

    pages = []
    for path in ("/patients", f"/patients/{patient.id}", "/schedule", "/admin/labs"):
        login_with_csrf(client, admin)
        pages.append(client.get(path).text)
    login_with_csrf(client, physician)
    pages.extend(
        [
            client.get(f"/visits/{visit.id}").text,
            client.get(f"/patients/{patient.id}/prescriptions").text,
        ]
    )
    for page in pages:
        assert xss not in page
        assert '<script>alert("prompt12")</script>' not in page
    assert any("&lt;script&gt;" in page for page in pages)
    assert patient.id and appointment_type.id and definition.id and prescription.id


def test_raw_sql_and_logging_audit_find_no_injection_or_phi_logging_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The application uses ORM parameters and generic operational logging."""

    python_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app").rglob("*.py")
    )
    raw_sql_calls = re.findall(r"\b(?:text|exec_driver_sql)\s*\(", python_source)
    assert raw_sql_calls == ["text("]
    assert 'text("SELECT 1")' in python_source
    assert "logger.error(\"Unhandled application error\")" in python_source
    assert "logger.error(\"Scheduled license check failed\")" in python_source
    assert "password" not in caplog.text.lower()


def test_lab_file_resolution_rejects_absolute_and_parent_paths() -> None:
    """Stored lab filenames cannot escape the private upload directory."""

    for unsafe_path in ("../outside.pdf", "/tmp/outside.pdf", "nested/../../x.pdf"):
        with pytest.raises(ValueError, match="Invalid stored"):
            lab_file_path_for_result(LabResult(file_path=unsafe_path))


def test_patient_phi_does_not_appear_in_generated_url_values(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Patient names and clinical details are rendered as content, never URL data."""

    user = seeded_users[UserRole.CLINIC_ADMIN]
    patient = create_patient(
        db_session,
        user.clinic_id,
        user,
        {
            "name": "PHI Patient Unique Name",
            "date_of_birth": date(1990, 1, 1),
            "contact_info": {"phone": "555-0100"},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [{"name": "Secret Allergy", "reaction": "Private"}],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    assert client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    ).status_code == 303
    response = client.get("/patients")
    assert response.status_code == 200
    hrefs = re.findall(r'href="([^"]+)"', response.text)
    assert all("PHI%20Patient" not in href for href in hrefs)
    assert all("Secret%20Allergy" not in href for href in hrefs)
    assert f"/patients/{patient.id}" in hrefs