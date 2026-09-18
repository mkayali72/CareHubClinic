"""Automated coverage for the responsive/theme and retry-safe UI contract."""

from datetime import date
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentType, Patient, User, UserRole
from app.services.patients import create_patient


APP_CSS = Path("app/static/css/app.css").read_text(encoding="utf-8")
APP_JS = Path("app/static/js/app.js").read_text(encoding="utf-8")


def login_as(client: TestClient, user: User) -> None:
    """Authenticate a test client using the fixture's CSRF bypass."""

    response = client.post(
        "/login",
        data={"username": user.username, "password": "Valid-Test-Password1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def seed_patient(db_session: Session, user: User) -> Patient:
    """Create the patient needed by the scheduling form test."""

    patient = create_patient(
        db=db_session,
        clinic_id=user.clinic_id,
        actor=user,
        payload={
            "name": "Responsive Test Patient",
            "date_of_birth": date(1990, 1, 2),
            "contact_info": {},
            "insurance_info": {},
            "emergency_contact": {},
            "allergies": [],
            "current_medications": [],
            "contraception_method": None,
        },
    )
    db_session.commit()
    return patient


def test_100_theme_controls_and_dark_mode_contract_span_shared_pages(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """Spot-check the shared shell on several non-login pages and its assets."""

    admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient = seed_patient(db_session, admin)
    login_as(client, admin)
    paths = (
        "/welcome",
        "/patients",
        f"/patients/{patient.id}",
        "/schedule",
        "/reports",
        "/admin/labs",
        "/admin/prescriptions",
        "/admin/license",
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'data-theme="light"' in response.text, path
        assert "data-theme-toggle" in response.text, path
        assert response.text.count('type="button" data-font-size=') == 7, path
        assert "Dashboard" in response.text, path
        assert "data-contrast-toggle" in response.text, path
        assert "/static/js/app.js" in response.text, path
        if path == "/schedule":
            assert re.search(r'<a class="[^"]*bg-indigo-50[^"]*" href="/schedule"', response.text)
            assert re.search(r'<a class="[^"]*bg-white[^"]*" href="/"', response.text)

    assert 'html[data-theme="dark"]' in APP_CSS
    assert 'root.dataset.theme = value' in APP_JS
    assert 'applyTheme(root.dataset.theme === "dark" ? "light" : "dark")' in APP_JS
    assert "localStorage.getItem" in APP_JS


def test_101_dropped_first_response_retry_does_not_duplicate_appointment(
    client: TestClient,
    seeded_users: dict[UserRole, User],
    db_session: Session,
) -> None:
    """A lost HTMX response can be retried with one durable appointment result."""

    front_desk = seeded_users[UserRole.FRONT_DESK]
    physician = seeded_users[UserRole.PHYSICIAN]
    admin = seeded_users[UserRole.CLINIC_ADMIN]
    patient = seed_patient(db_session, admin)
    appointment_type = AppointmentType(
        clinic_id=admin.clinic_id,
        name="Retry-safe appointment",
        default_duration_minutes=30,
    )
    db_session.add(appointment_type)
    db_session.commit()
    login_as(client, front_desk)

    data = {
        "patient_id": str(patient.id),
        "doctor_id": str(physician.id),
        "appointment_type_id": str(appointment_type.id),
        "scheduled_at": f"{date.today().isoformat()}T09:30",
        "duration_minutes": "0",
        "client_request_id": "test-101-dropped-response",
    }

    def post_then_drop_response() -> None:
        response = client.post(
            "/schedule/appointments",
            data=data,
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        raise ConnectionError("simulated response dropped after server commit")

    with pytest.raises(ConnectionError, match="simulated response"):
        post_then_drop_response()

    retry = client.post(
        "/schedule/appointments",
        data=data,
        headers={"HX-Request": "true"},
    )
    assert retry.status_code == 200
    appointments = list(
        db_session.scalars(
            select(Appointment).where(
                Appointment.clinic_id == admin.clinic_id,
                Appointment.client_request_id == data["client_request_id"],
            )
        )
    )
    assert len(appointments) == 1

    schedule = client.get("/schedule")
    assert schedule.status_code == 200
    assert 'hx-indicator="#appointment-submit-status"' in schedule.text
    assert "data-idempotency-form" in schedule.text
    assert "data-submit-status" in schedule.text
    assert "Connection lost. Nothing was duplicated; try again." in APP_JS
    assert 'form.setAttribute("aria-busy", "true")' in APP_JS