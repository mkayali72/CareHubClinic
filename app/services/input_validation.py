"""Shared validation for form values whose shape matters at every boundary."""

from __future__ import annotations

import re

PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]*$")
BLOOD_PRESSURE_PATTERN = re.compile(r"^[0-9]{2,3}\s*/\s*[0-9]{2,3}$")
DECIMAL_NUMBER_PATTERN = re.compile(r"^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")
INTEGER_NUMBER_PATTERN = re.compile(r"^[0-9]+$")


def validate_phone(value: str, *, field_name: str = "Phone") -> str:
    """Validate a phone number while allowing common international formatting.

    Phone numbers are not converted to numeric database values because doing so
    would lose leading zeroes. Formatting characters are accepted only when the
    remaining value is numeric.
    """

    normalized = value.strip()
    if not normalized:
        return ""
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must contain a numeric phone number "
            "(digits with optional +, spaces, parentheses, or hyphens)."
        )
    digits = re.sub(r"\D", "", normalized)
    if len(digits) < 7:
        raise ValueError(f"{field_name} must contain at least 7 digits.")
    return normalized


def validate_blood_pressure(value: str) -> str:
    """Validate a blood pressure reading such as ``120/80``."""

    normalized = value.strip()
    if not normalized:
        return ""
    if not BLOOD_PRESSURE_PATTERN.fullmatch(normalized):
        raise ValueError("Blood pressure must contain two numeric readings separated by '/'.")
    return normalized


def validate_numeric_text(
    value: object,
    *,
    field_name: str = "Number",
    integer: bool = False,
    allow_blank: bool = True,
) -> str:
    """Validate a non-negative decimal or integer form value.

    This deliberately rejects letters, signs, whitespace inside the value, and
    exponent notation. Browser controls are helpful, but this remains the
    authoritative check for direct or tampered requests.
    """

    normalized = "" if value is None else str(value).strip()
    if not normalized:
        if allow_blank:
            return ""
        raise ValueError(f"{field_name} is required.")
    pattern = INTEGER_NUMBER_PATTERN if integer else DECIMAL_NUMBER_PATTERN
    if not pattern.fullmatch(normalized):
        kind = "whole number" if integer else "number"
        raise ValueError(f"{field_name} must be a {kind}.")
    return normalized