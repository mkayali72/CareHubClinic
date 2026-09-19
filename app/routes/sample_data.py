"""Clinic-admin routes for first-run sample records."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import (
    AppointmentType,
    LabOrder,
    LabOrderStatus,
    Patient,
    User,
    UserRole,
)
from app.services.auth import STAFF_ROLES, require_roles
from app.services.sample_data import (
    delete_sample_appointment_type,
    delete_sample_lab_order,
    delete_sample_patient,
    delete_sample_staff,
    get_sample_data,
    update_sample_lab_order,
    update_sample_staff,
)
from app.services.scheduling import update_appointment_type
from app.templates import create_templates

router = APIRouter(tags=["sample data"])
templates = create_templates()


def _context(request: Request, db: Session, user: User, **values: Any) -> dict[str, Any]:
    context = get_sample_data(db, user)
    context.update(
        {
            "request": request,
            "app_name": settings.app_name,
            "page_title": "Sample data",
            "user": user,
            "staff_roles": STAFF_ROLES,
            "message": "",
            "error": "",
        }
    )
    context.update(values)
    return context


def _redirect(status: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin/sample-data?saved={status}", status_code=303)


def _target(
    db: Session,
    model: type[Any],
    record_id: int,
    clinic_id: int,
    *,
    include_deleted: bool = False,
) -> Any:
    statement = select(model).where(model.id == record_id)
    if hasattr(model, "clinic_id"):
        statement = statement.where(model.clinic_id == clinic_id)
    if include_deleted:
        statement = statement.execution_options(include_deleted=True)
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(status_code=404, detail="Sample record not found.")
    return record


@router.get("/admin/sample-data", response_class=HTMLResponse)
def sample_data_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Show all generated sample rows and their safe management actions."""

    return templates.TemplateResponse(
        request=request,
        name="sample_data/index.html",
        context=_context(request, db, current_user),
    )


@router.post("/admin/sample-data/staff/{user_id}/edit")
def edit_sample_staff(
    user_id: int,
    username: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    target = _target(db, User, user_id, current_user.clinic_id)
    try:
        update_sample_staff(
            db,
            current_user,
            target,
            username,
            full_name,
            UserRole(role),
        )
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("updated")


@router.post("/admin/sample-data/appointment-types/{appointment_type_id}/edit")
def edit_sample_appointment_type(
    appointment_type_id: int,
    name: str = Form(...),
    default_duration_minutes: int = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    appointment_type = _target(
        db,
        AppointmentType,
        appointment_type_id,
        current_user.clinic_id,
    )
    try:
        update_appointment_type(
            db,
            appointment_type,
            current_user,
            name,
            default_duration_minutes,
        )
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("updated")


@router.post("/admin/sample-data/lab-orders/{order_id}/edit")
def edit_sample_lab_order(
    order_id: int,
    lab_test_definition_id: int = Form(...),
    status: str = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    order = _target(
        db,
        LabOrder,
        order_id,
        current_user.clinic_id,
    )
    try:
        update_sample_lab_order(
            db,
            current_user,
            order,
            lab_test_definition_id,
            LabOrderStatus(status),
        )
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("updated")


@router.post("/admin/sample-data/staff/{user_id}/delete")
def delete_sample_staff_route(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    target = _target(db, User, user_id, current_user.clinic_id)
    try:
        delete_sample_staff(db, current_user, target)
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("deleted")


@router.post("/admin/sample-data/appointment-types/{appointment_type_id}/delete")
def delete_sample_appointment_type_route(
    appointment_type_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    appointment_type = _target(
        db,
        AppointmentType,
        appointment_type_id,
        current_user.clinic_id,
    )
    try:
        delete_sample_appointment_type(db, current_user, appointment_type)
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("deleted")


@router.post("/admin/sample-data/lab-orders/{order_id}/delete")
def delete_sample_lab_order_route(
    order_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    order = _target(
        db,
        LabOrder,
        order_id,
        current_user.clinic_id,
    )
    try:
        delete_sample_lab_order(db, current_user, order)
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("deleted")


@router.post("/admin/sample-data/patients/{patient_id}/delete")
def delete_sample_patient_route(
    patient_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    patient = _target(
        db,
        Patient,
        patient_id,
        current_user.clinic_id,
    )
    try:
        delete_sample_patient(db, current_user, patient)
        db.commit()
    except (ValueError, PermissionError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _redirect("deleted")