"""Local clinic license evaluation, write enforcement, and check-in scheduling.

This module intentionally contains the only license-validity decision point.
The current implementation checks the local License row. A future remote
license-server integration should replace ``perform_license_check_in`` while
leaving request enforcement and UI consumers unchanged.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, JSONResponse, Response

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import License, LicenseStatus, User
from app.services.auth import get_current_user

logger = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LICENSE_BYPASS_PATHS = frozenset({"/login", "/logout", "/admin/license"})
DEFAULT_LICENSE_DAYS = 365
DEFAULT_GRACE_PERIOD_DAYS = 7


@dataclass(frozen=True)
class LicenseSnapshot:
    """Expose one evaluated license state to request handlers and templates."""

    status: LicenseStatus
    expires_at: datetime | None
    last_check_in_at: datetime | None
    grace_period_days: int
    days_remaining: int | None
    grace_days_remaining: int
    is_read_only: bool
    is_configured: bool
    message: str

    @property
    def status_label(self) -> str:
        """Return a human-readable status label for the shared shell."""

        return {
            LicenseStatus.ACTIVE: "Active",
            LicenseStatus.GRACE: "Read-only grace period",
            LicenseStatus.EXPIRED: "Expired",
            LicenseStatus.REVOKED: "Revoked",
        }[self.status]

    @property
    def is_writable(self) -> bool:
        """Return whether state-changing requests may proceed."""

        return not self.is_read_only


class LicenseWriteBlocked(Exception):
    """Raised by the request dependency when a clinic is read-only."""

    def __init__(self, request: Request, snapshot: LicenseSnapshot) -> None:
        self.request = request
        self.snapshot = snapshot
        super().__init__(snapshot.message)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for deterministic license comparisons."""

    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Treat legacy naive timestamps as UTC and normalize aware timestamps."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_license(db: Session, clinic_id: int) -> License | None:
    """Load the one active license configuration for a clinic."""

    return db.scalar(select(License).where(License.clinic_id == clinic_id))


def ensure_license(db: Session, clinic_id: int, *, now: datetime | None = None) -> License:
    """Create a local placeholder license when an older clinic lacks one.

    Migrations backfill existing PostgreSQL clinics. This lazy bootstrap keeps
    SQLite-based development fixtures and clinics created by older code usable
    until an administrator explicitly configures an expiration date.
    """

    license_record = get_license(db, clinic_id)
    if license_record is not None:
        return license_record
    checked_at = as_utc(now or utc_now())
    license_record = License(
        clinic_id=clinic_id,
        status=LicenseStatus.ACTIVE,
        expires_at=checked_at + timedelta(days=DEFAULT_LICENSE_DAYS),
        last_check_in_at=checked_at,
        grace_period_days=DEFAULT_GRACE_PERIOD_DAYS,
    )
    db.add(license_record)
    db.flush()
    return license_record


def evaluate_license(
    license_record: License | None,
    *,
    now: datetime | None = None,
) -> LicenseSnapshot:
    """Evaluate active, grace, expired, or revoked state from one local row."""

    current = as_utc(now or utc_now())
    if license_record is None:
        return LicenseSnapshot(
            status=LicenseStatus.ACTIVE,
            expires_at=None,
            last_check_in_at=None,
            grace_period_days=DEFAULT_GRACE_PERIOD_DAYS,
            days_remaining=None,
            grace_days_remaining=0,
            is_read_only=False,
            is_configured=False,
            message="License status has not been configured.",
        )

    expires_at = as_utc(license_record.expires_at)
    grace_period_days = max(0, license_record.grace_period_days)
    if license_record.status is LicenseStatus.REVOKED:
        status = LicenseStatus.REVOKED
    elif current <= expires_at:
        status = LicenseStatus.ACTIVE
    elif current <= expires_at + timedelta(days=grace_period_days):
        status = LicenseStatus.GRACE
    else:
        status = LicenseStatus.EXPIRED

    remaining_seconds = (expires_at - current).total_seconds()
    days_remaining = max(0, int((remaining_seconds + 86399) // 86400))
    grace_end = expires_at + timedelta(days=grace_period_days)
    grace_remaining_seconds = max(0, (grace_end - current).total_seconds())
    grace_days_remaining = int((grace_remaining_seconds + 86399) // 86400)
    if status is LicenseStatus.GRACE:
        message = (
            "Your clinic is in a read-only license grace period. "
            "You can continue viewing records while renewal is completed."
        )
    elif status is LicenseStatus.EXPIRED:
        message = (
            "Your clinic license has expired. The workspace is read-only "
            "until the license is renewed."
        )
    elif status is LicenseStatus.REVOKED:
        message = (
            "Your clinic license is inactive. The workspace is read-only "
            "until an administrator renews it."
        )
    else:
        message = "Your clinic license is active."
    return LicenseSnapshot(
        status=status,
        expires_at=license_record.expires_at,
        last_check_in_at=license_record.last_check_in_at,
        grace_period_days=grace_period_days,
        days_remaining=days_remaining,
        grace_days_remaining=grace_days_remaining,
        is_read_only=status is not LicenseStatus.ACTIVE,
        is_configured=True,
        message=message,
    )


def get_license_snapshot(
    db: Session,
    clinic_id: int,
    *,
    now: datetime | None = None,
) -> LicenseSnapshot:
    """Read and evaluate the current clinic license without caching."""

    return evaluate_license(get_license(db, clinic_id), now=now)


def perform_license_check_in(
    license_record: License,
    *,
    now: datetime | None = None,
) -> LicenseSnapshot:
    """Perform the local placeholder check-in for one license.

    Replace this single function with the future remote license-server call.
    It currently refreshes ``last_check_in_at`` and derives status from the
    locally stored expiration and grace-period fields.
    """

    checked_at = as_utc(now or utc_now())
    license_record.last_check_in_at = checked_at
    snapshot = evaluate_license(license_record, now=checked_at)
    license_record.status = snapshot.status
    return snapshot


def refresh_license_statuses(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    """Check every clinic license and persist its latest local status."""

    licenses = list(db.scalars(select(License)))
    checked_at = as_utc(now or utc_now())
    for license_record in licenses:
        perform_license_check_in(license_record, now=checked_at)
    db.commit()
    return len(licenses)


def update_license_configuration(
    db: Session,
    license_record: License,
    *,
    expires_at: datetime,
    grace_period_days: int,
    status: LicenseStatus,
    now: datetime | None = None,
) -> LicenseSnapshot:
    """Apply clinic-admin license settings and immediately re-evaluate them."""

    if grace_period_days < 0:
        raise ValueError("Grace period days must be zero or greater.")
    license_record.expires_at = as_utc(expires_at)
    license_record.grace_period_days = grace_period_days
    license_record.status = status
    return perform_license_check_in(license_record, now=now)


def _blocked_response(request: Request, snapshot: LicenseSnapshot) -> Response:
    """Return a clear browser or HTMX response without replacing form state."""

    message = snapshot.message + " Unsaved form content remains on this page."
    if request.headers.get("HX-Request") == "true":
        return Response(
            content=message,
            status_code=423,
            media_type="text/plain",
            headers={
                "HX-Reswap": "none",
                "HX-Trigger": json.dumps(
                    {"license-write-blocked": {"message": message}}
                ),
            },
        )
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=423,
            content={"detail": message, "license_status": snapshot.status.value},
        )
    return HTMLResponse(
        content=(
            "<!doctype html><title>Workspace read-only</title>"
            '<main style="font-family:system-ui;max-width:42rem;margin:4rem auto;'
            'padding:1.5rem;border:1px solid #cbd5e1;border-radius:1rem">'
            "<h1>Workspace temporarily read-only</h1>"
            f"<p>{html.escape(message)}</p>"
            '<p><a href="/admin/license">View license status</a></p>'
            "</main>"
        ),
        status_code=423,
    )


def enforce_license_for_request(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response | None:
    """Run the uncached server-side write check on every application request."""

    snapshot = (
        get_license_snapshot(db, current_user.clinic_id)
        if current_user is not None
        else None
    )
    request.state.license_snapshot = snapshot
    if (
        current_user is None
        or request.method not in WRITE_METHODS
        or request.url.path in LICENSE_BYPASS_PATHS
        or snapshot is None
        or snapshot.is_writable
    ):
        return None
    raise LicenseWriteBlocked(request, snapshot)


def run_scheduled_license_check() -> int:
    """Run one scheduler tick using the application database session."""

    db = SessionLocal()
    try:
        return refresh_license_statuses(db)
    except Exception:
        db.rollback()
        logger.exception("Scheduled license check failed")
        return 0
    finally:
        db.close()