"""Dedicated application security hardening coverage."""

from dataclasses import replace
from datetime import date
import html
from pathlib import Path
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import create_app
from app.models import LabResult, Patient, User, UserRole
from app.services import auth as auth_service
from app.services.csrf import enforce_csrf
from app.services.labs import lab_file_path_for_result
from app.services.patients import create_patient


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
            "email": user.email,
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
        data={"email": user.email, "password": "Valid-Test-Password1"},
    )
    assert missing.status_code == 403

    login = secure_client.post(
        "/login",
        data={
            "email": user.email,
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
                "email": user.email,
                "password": "Wrong-Password1",
                "_csrf_token": token,
            },
        )
        assert response.status_code == 401
    correct_while_locked = secure_client.post(
        "/login",
        data={
            "email": user.email,
            "password": "Valid-Test-Password1",
            "_csrf_token": token,
        },
    )
    assert correct_while_locked.status_code == 401
    db_session.refresh(user)
    assert user.locked_until is not None


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
        data={"email": user.email, "password": "Valid-Test-Password1"},
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
        data={"email": user.email, "password": "Valid-Test-Password1"},
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
        data={"email": user.email, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    ).status_code == 303
    response = client.get("/patients")
    assert response.status_code == 200
    hrefs = re.findall(r'href="([^"]+)"', response.text)
    assert all("PHI%20Patient" not in href for href in hrefs)
    assert all("Secret%20Allergy" not in href for href in hrefs)
    assert f"/patients/{patient.id}" in hrefs