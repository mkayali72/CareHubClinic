"""Clinic-admin staff account management pages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import User, UserRole
from app.services.auth import (
    STAFF_ROLES,
    create_staff_account,
    deactivate_user,
    reactivate_user,
    reset_user_password,
)
from app.services.auth import require_roles
from app.templates import create_templates

router = APIRouter(tags=["staff administration"])
templates = create_templates()


def _staff_context(
    request: Request,
    db: Session,
    current_user: User,
    *,
    message: str = "",
    error: str = "",
    form_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the clinic-scoped staff management page context."""

    staff = list(
        db.scalars(
            select(User)
            .where(User.clinic_id == current_user.clinic_id)
            .execution_options(include_deleted=True)
            .order_by(User.full_name, User.username)
        )
    )
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": "Staff accounts",
        "user": current_user,
        "staff": staff,
        "staff_roles": STAFF_ROLES,
        "message": message,
        "error": error,
        "form_values": form_values or {},
    }


def _managed_user_or_404(db: Session, current_user: User, user_id: int) -> User:
    """Load a user from the current clinic, including soft-deleted accounts."""

    target = db.scalar(
        select(User)
        .where(User.id == user_id, User.clinic_id == current_user.clinic_id)
        .execution_options(include_deleted=True)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found.")
    return target


@router.get("/admin/staff", response_class=HTMLResponse)
def staff_accounts(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Show all staff accounts belonging to the administrator's clinic."""

    return templates.TemplateResponse(
        request=request,
        name="staff/index.html",
        context=_staff_context(request, db, current_user),
    )


@router.post("/admin/staff", response_class=HTMLResponse)
def create_staff(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Create one active staff account after validating the submitted form."""

    form_values = {"username": username, "full_name": full_name, "role": role}
    try:
        selected_role = UserRole(role)
        if selected_role not in STAFF_ROLES:
            raise ValueError("Select a supported staff role.")
        if password != password_confirmation:
            raise ValueError("The password entries do not match.")
        create_staff_account(
            db,
            current_user,
            username=username,
            password=password,
            full_name=full_name,
            role=selected_role,
        )
        db.commit()
    except (ValueError, IntegrityError) as error:
        db.rollback()
        message = (
            "That username is already in use."
            if isinstance(error, IntegrityError)
            else str(error)
        )
        return templates.TemplateResponse(
            request=request,
            name="staff/index.html",
            context=_staff_context(
                request,
                db,
                current_user,
                error=message,
                form_values=form_values,
            ),
            status_code=422,
        )
    return RedirectResponse(url="/admin/staff?saved=created", status_code=303)


@router.post("/admin/staff/{user_id}/deactivate")
def deactivate_staff(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Deactivate one staff account in the administrator's clinic."""

    target = _managed_user_or_404(db, current_user, user_id)
    try:
        deactivate_user(db, current_user, target)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(url="/admin/staff?saved=deactivated", status_code=303)


@router.post("/admin/staff/{user_id}/reactivate")
def reactivate_staff(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Reactivate one previously deactivated staff account."""

    target = _managed_user_or_404(db, current_user, user_id)
    try:
        reactivate_user(db, current_user, target)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(url="/admin/staff?saved=reactivated", status_code=303)


@router.post("/admin/staff/{user_id}/reset-password")
def reset_staff_password(
    user_id: int,
    password: str = Form(...),
    password_confirmation: str = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Set a new password without exposing the prior password."""

    target = _managed_user_or_404(db, current_user, user_id)
    try:
        if password != password_confirmation:
            raise ValueError("The password entries do not match.")
        reset_user_password(db, current_user, target, password)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(url="/admin/staff?saved=password-reset", status_code=303)