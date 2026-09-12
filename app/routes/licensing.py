"""Clinic-admin license status and local placeholder configuration routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import AuditAction, LicenseStatus, User, UserRole
from app.services.auth import require_roles
from app.services.audit import record_audit_event
from app.services.licensing import (
    ensure_license,
    get_license_snapshot,
    update_license_configuration,
)

router = APIRouter(tags=["licensing"])
templates = Jinja2Templates(directory="app/templates")


def _utc_form_value(value: datetime) -> datetime:
    """Interpret the browser's timezone-less datetime-local value as UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/admin/license", response_class=HTMLResponse)
def license_status(
    request: Request,
    saved: int = 0,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Show the clinic license status and editable local test configuration."""

    license_record = ensure_license(db, current_user.clinic_id)
    db.commit()
    snapshot = get_license_snapshot(db, current_user.clinic_id)
    return templates.TemplateResponse(
        request=request,
        name="licensing/status.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": "License status",
            "user": current_user,
            "license": license_record,
            "license_snapshot": snapshot,
            "license_statuses": [LicenseStatus.ACTIVE, LicenseStatus.REVOKED],
            "saved": bool(saved),
        },
    )


@router.post("/admin/license", response_class=HTMLResponse)
def update_license(
    request: Request,
    expires_at: datetime = Form(...),
    grace_period_days: int = Form(...),
    status: str = Form(LicenseStatus.ACTIVE.value),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Update local license expiration for renewal and testing workflows."""

    if status not in {LicenseStatus.ACTIVE.value, LicenseStatus.REVOKED.value}:
        raise HTTPException(status_code=422, detail="Unsupported license status.")
    license_record = ensure_license(db, current_user.clinic_id)
    previous = {
        "status": license_record.status.value,
        "expires_at": license_record.expires_at.isoformat(),
        "grace_period_days": license_record.grace_period_days,
    }
    try:
        snapshot = update_license_configuration(
            db,
            license_record,
            expires_at=_utc_form_value(expires_at),
            grace_period_days=grace_period_days,
            status=LicenseStatus(status),
        )
        record_audit_event(
            db=db,
            actor_user_id=current_user.id,
            action=AuditAction.UPDATE,
            entity_type="license",
            entity_id=license_record.id,
            details={
                "previous": previous,
                "status": license_record.status.value,
                "expires_at": license_record.expires_at.isoformat(),
                "grace_period_days": license_record.grace_period_days,
            },
        )
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.state.license_snapshot = snapshot
    return RedirectResponse(url="/admin/license?saved=1", status_code=303)