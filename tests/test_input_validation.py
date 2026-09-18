"""Regression coverage for numeric and date-shaped form values."""

from datetime import date

import pytest
from fastapi import HTTPException

from app.models import VisitType
from app.routes.scheduling import parse_scheduled_at, parse_selected_date
from app.services.clinical import normalize_visit_sections
from app.services.input_validation import validate_blood_pressure, validate_phone


def test_phone_validation_accepts_numeric_international_formatting() -> None:
    """Phone formatting may be conventional, but its content must be numeric."""

    assert validate_phone("+974 5555 0101") == "+974 5555 0101"


@pytest.mark.parametrize("value", ["call-me", "+974 ABC 0101", "123"])
def test_phone_validation_rejects_non_numeric_or_short_values(value: str) -> None:
    """Letters and incomplete phone values are rejected server-side."""

    with pytest.raises(ValueError):
        validate_phone(value)


@pytest.mark.parametrize("value", ["120/80", " 120 / 80 "])
def test_blood_pressure_validation_accepts_two_numeric_readings(value: str) -> None:
    """Blood pressure is a numeric systolic/diastolic pair."""

    assert validate_blood_pressure(value) == value.strip()


@pytest.mark.parametrize("value", ["120/low", "normal", "120"])
def test_blood_pressure_validation_rejects_text_or_incomplete_values(value: str) -> None:
    """Blood pressure cannot contain free text or a single reading."""

    with pytest.raises(ValueError):
        validate_blood_pressure(value)


def test_clinical_numeric_readings_reject_non_finite_and_text_values() -> None:
    """Clinical numeric fields reject values that browser controls could bypass."""

    with pytest.raises(ValueError):
        normalize_visit_sections(
            visit_type=VisitType.PRENATAL,
            vitals={"weight_kg": "nan"},
            prenatal_data={"fetal_heart_tones": "145 bpm"},
        )


def test_date_and_datetime_parsers_require_their_matching_shapes() -> None:
    """Date-only and datetime-local fields do not accept the other shape."""

    assert parse_selected_date("2026-09-18") == date(2026, 9, 18)
    with pytest.raises(HTTPException):
        parse_selected_date("2026-09-18T09:00")
    with pytest.raises(HTTPException):
        parse_scheduled_at("2026-09-18")