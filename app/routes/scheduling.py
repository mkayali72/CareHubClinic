"""Scheduling calendar, queue, appointment, and lookup routes."""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Appointment, AppointmentType, User, UserRole
from app.services.auth import require_roles
from app.services.scheduling import (
    APPOINTMENT_TYPE_ADMIN_ROLES,
    SCHEDULING_ROLES,
    SCHEDULING_WRITE_ROLES,
    advance_appointment_status,
    calendar_columns,
    cancel_appointment,
    create_appointment,
    create_appointment_type,
    create_walk_in,
    get_appointment_for_user,
    get_appointment_types,
    get_appointments_for_date,
    get_physicians,
    get_schedulable_patients,
    serialize_appointment,
    update_appointment,
    update_appointment_type,
)
from app.templates import create_templates

router = APIRouter(tags=["scheduling"])
templates = create_templates()


def parse_selected_date(value: str | None) -> date:
    """Parse an optional ISO date query value into a selected calendar date."""

    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD.") from error


def parse_scheduled_at(value: str) -> datetime:
    """Parse a browser datetime-local value into a clinic-local datetime."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="Scheduled time must use a valid date and time.",
        ) from error
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def _raise_service_error(error: ValueError | PermissionError) -> None:
    """Convert service validation failures into safe HTTP responses."""

    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    raise HTTPException(status_code=422, detail=str(error)) from error


def _queue_doctor_id(user: User) -> int | None:
    """Return the physician's own queue filter, or None for clinic-wide views."""

    return user.id if user.role is UserRole.PHYSICIAN else None


def _schedule_context(
    request: Request,
    db: Session,
    user: User,
    selected_date: date,
) -> dict[str, Any]:
    """Build shared calendar and queue context for one clinic date."""

    doctors = get_physicians(db, user.clinic_id)
    calendar_doctors = (
        [doctor for doctor in doctors if doctor.id == user.id]
        if user.role is UserRole.PHYSICIAN
        else doctors
    )
    appointments = get_appointments_for_date(
        db,
        user,
        selected_date,
        doctor_id=_queue_doctor_id(user),
    )
    queue_appointments = appointments
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": "Schedule",
        "user": user,
        "selected_date": selected_date,
        "previous_date": selected_date.fromordinal(selected_date.toordinal() - 1),
        "next_date": selected_date.fromordinal(selected_date.toordinal() + 1),
        "doctors": calendar_doctors,
        "calendar_columns": calendar_columns(calendar_doctors, appointments),
        "queue_appointments": queue_appointments,
        "patients": get_schedulable_patients(db, user.clinic_id),
        "appointment_types": get_appointment_types(db, user.clinic_id),
        "can_create": user.role in SCHEDULING_WRITE_ROLES,
        "can_manage_types": user.role in APPOINTMENT_TYPE_ADMIN_ROLES,
    }


def _queue_context(
    request: Request,
    db: Session,
    user: User,
    selected_date: date,
) -> dict[str, Any]:
    """Build context for the full queue page and its htmx rows."""

    appointments = get_appointments_for_date(
        db,
        user,
        selected_date,
        doctor_id=_queue_doctor_id(user),
    )
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": "Today's Queue" if selected_date == date.today() else "Queue",
        "user": user,
        "selected_date": selected_date,
        "previous_date": selected_date.fromordinal(selected_date.toordinal() - 1),
        "next_date": selected_date.fromordinal(selected_date.toordinal() + 1),
        "queue_appointments": appointments,
        "doctors": get_physicians(db, user.clinic_id),
        "appointment_types": get_appointment_types(db, user.clinic_id),
        "can_create": user.role in SCHEDULING_WRITE_ROLES,
    }


def _type_panel_context(request: Request, db: Session, user: User) -> dict[str, Any]:
    """Build the appointment-type editor partial context."""

    return {
        "request": request,
        "app_name": settings.app_name,
        "user": user,
        "appointment_types": get_appointment_types(db, user.clinic_id),
    }


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    selected_date: str | None = Query(default=None, alias="date"),
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the primary Google Calendar-style scheduling workspace."""

    return templates.TemplateResponse(
        request=request,
        name="schedule/index.html",
        context=_schedule_context(
            request,
            db,
            current_user,
            parse_selected_date(selected_date),
        ),
    )


@router.get("/schedule/grid", response_class=HTMLResponse)
def schedule_grid(
    request: Request,
    selected_date: str | None = Query(default=None, alias="date"),
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return only the calendar grid for htmx date navigation."""

    context = _schedule_context(
        request,
        db,
        current_user,
        parse_selected_date(selected_date),
    )
    return templates.TemplateResponse(
        request=request,
        name="schedule/partials/calendar.html",
        context=context,
    )


@router.get("/queue", response_class=HTMLResponse)
def queue_page(
    request: Request,
    selected_date: str | None = Query(default=None, alias="date"),
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the clinic or physician Today's Queue view."""

    return templates.TemplateResponse(
        request=request,
        name="schedule/queue.html",
        context=_queue_context(
            request,
            db,
            current_user,
            parse_selected_date(selected_date),
        ),
    )


@router.get("/queue/rows", response_class=HTMLResponse)
def queue_rows(
    request: Request,
    selected_date: str | None = Query(default=None, alias="date"),
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return queue rows for htmx status refreshes."""

    return templates.TemplateResponse(
        request=request,
        name="schedule/partials/queue_rows.html",
        context=_queue_context(
            request,
            db,
            current_user,
            parse_selected_date(selected_date),
        ),
    )


@router.get("/api/appointments")
def appointment_api_list(
    selected_date: str | None = Query(default=None, alias="date"),
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return clinic-scoped appointments for a calendar date."""

    appointments = get_appointments_for_date(
        db,
        current_user,
        parse_selected_date(selected_date),
        doctor_id=_queue_doctor_id(current_user),
    )
    return JSONResponse(
        content={"appointments": [serialize_appointment(appointment) for appointment in appointments]}
    )


@router.post("/schedule/appointments", response_class=HTMLResponse)
def create_appointment_route(
    request: Request,
    patient_id: int = Form(...),
    doctor_id: int = Form(...),
    appointment_type_id: int = Form(...),
    scheduled_at: str = Form(...),
    duration_minutes: int = Form(0),
    client_request_id: str | None = Form(default=None),
    current_user: User = Depends(require_roles(*SCHEDULING_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create an appointment for an existing patient."""

    parsed_scheduled_at = parse_scheduled_at(scheduled_at)
    client_request_id = client_request_id.strip() if client_request_id else None
    if client_request_id and len(client_request_id) > 128:
        raise HTTPException(status_code=422, detail="The client request ID is too long.")
    if client_request_id:
        existing = db.scalar(
            select(Appointment)
            .where(
                Appointment.clinic_id == current_user.clinic_id,
                Appointment.client_request_id == client_request_id,
            )
            .execution_options(include_deleted=True)
        )
        if existing is not None:
            if request.headers.get("HX-Request") == "true":
                return templates.TemplateResponse(
                    request=request,
                    name="schedule/partials/calendar.html",
                    context=_schedule_context(
                        request,
                        db,
                        current_user,
                        existing.scheduled_at.date(),
                    ),
                )
            return RedirectResponse(
                url=f"/schedule?date={existing.scheduled_at.date().isoformat()}",
                status_code=303,
            )
    try:
        create_appointment(
            db=db,
            clinic_id=current_user.clinic_id,
            actor=current_user,
            patient_id=patient_id,
            doctor_id=doctor_id,
            appointment_type_id=appointment_type_id,
            scheduled_at=parsed_scheduled_at,
            duration_minutes=duration_minutes or None,
            client_request_id=client_request_id,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/calendar.html",
            context=_schedule_context(
                request,
                db,
                current_user,
                parsed_scheduled_at.date(),
            ),
        )
    return RedirectResponse(
        url=f"/schedule?date={parsed_scheduled_at.date().isoformat()}",
        status_code=303,
    )


@router.post("/schedule/walk-ins", response_class=HTMLResponse)
def create_walk_in_route(
    request: Request,
    name: str = Form(...),
    date_of_birth: date = Form(...),
    phone: str = Form(""),
    doctor_id: int = Form(...),
    appointment_type_id: int = Form(...),
    current_user: User = Depends(require_roles(*SCHEDULING_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a new walk-in patient and checked-in appointment in one step."""

    try:
        create_walk_in(
            db=db,
            clinic_id=current_user.clinic_id,
            actor=current_user,
            name=name,
            date_of_birth=date_of_birth,
            phone=phone,
            doctor_id=doctor_id,
            appointment_type_id=appointment_type_id,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/queue_rows.html",
            context=_queue_context(request, db, current_user, date.today()),
        )
    return RedirectResponse(url="/queue", status_code=303)


@router.post("/schedule/appointments/{appointment_id}/edit", response_class=HTMLResponse)
def edit_appointment_route(
    request: Request,
    appointment_id: int,
    patient_id: int = Form(...),
    doctor_id: int = Form(...),
    appointment_type_id: int = Form(...),
    scheduled_at: str = Form(...),
    duration_minutes: int = Form(0),
    current_user: User = Depends(require_roles(*SCHEDULING_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Edit an active appointment for an existing patient."""

    appointment = get_appointment_for_user(db, appointment_id, current_user)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    try:
        update_appointment(
            db=db,
            appointment=appointment,
            actor=current_user,
            patient_id=patient_id,
            doctor_id=doctor_id,
            appointment_type_id=appointment_type_id,
            scheduled_at=parse_scheduled_at(scheduled_at),
            duration_minutes=duration_minutes or None,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/calendar.html",
            context=_schedule_context(
                request,
                db,
                current_user,
                appointment.scheduled_at.date(),
            ),
        )
    return RedirectResponse(
        url=f"/schedule?date={appointment.scheduled_at.date().isoformat()}",
        status_code=303,
    )


@router.post("/schedule/appointments/{appointment_id}/cancel")
def cancel_appointment_route(
    request: Request,
    appointment_id: int,
    current_user: User = Depends(require_roles(*SCHEDULING_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Cancel an active appointment without deleting its record."""

    appointment = get_appointment_for_user(db, appointment_id, current_user)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    appointment_date = appointment.scheduled_at.date()
    try:
        cancel_appointment(db, appointment, current_user)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/queue_rows.html",
            context=_queue_context(request, db, current_user, appointment_date),
        )
    return RedirectResponse(
        url=f"/queue?date={appointment_date.isoformat()}",
        status_code=303,
    )


@router.post("/schedule/appointments/{appointment_id}/advance")
def advance_status_route(
    request: Request,
    appointment_id: int,
    current_user: User = Depends(require_roles(*SCHEDULING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Advance one appointment by one queue status."""

    appointment = get_appointment_for_user(db, appointment_id, current_user)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    try:
        advance_appointment_status(db, appointment, current_user)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/queue_rows.html",
            context=_queue_context(request, db, current_user, appointment.scheduled_at.date()),
        )
    return RedirectResponse(
        url=f"/queue?date={appointment.scheduled_at.date().isoformat()}",
        status_code=303,
    )


@router.post("/schedule/types", response_class=HTMLResponse)
def create_appointment_type_route(
    request: Request,
    name: str = Form(...),
    default_duration_minutes: int = Form(...),
    current_user: User = Depends(require_roles(*APPOINTMENT_TYPE_ADMIN_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a clinic appointment type as a clinic administrator."""

    try:
        create_appointment_type(
            db=db,
            clinic_id=current_user.clinic_id,
            actor=current_user,
            name=name,
            default_duration_minutes=default_duration_minutes,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/appointment_types.html",
            context=_type_panel_context(request, db, current_user),
        )
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/schedule/types/{appointment_type_id}", response_class=HTMLResponse)
def update_appointment_type_route(
    request: Request,
    appointment_type_id: int,
    name: str = Form(...),
    default_duration_minutes: int = Form(...),
    current_user: User = Depends(require_roles(*APPOINTMENT_TYPE_ADMIN_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Edit a clinic appointment type as a clinic administrator."""

    appointment_type = db.scalar(
        select(AppointmentType).where(
            AppointmentType.id == appointment_type_id,
            AppointmentType.clinic_id == current_user.clinic_id,
        )
    )
    if appointment_type is None:
        raise HTTPException(status_code=404, detail="Appointment type not found.")
    try:
        update_appointment_type(
            db=db,
            appointment_type=appointment_type,
            actor=current_user,
            name=name,
            default_duration_minutes=default_duration_minutes,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _raise_service_error(error)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="schedule/partials/appointment_types.html",
            context=_type_panel_context(request, db, current_user),
        )
    return RedirectResponse(url="/schedule", status_code=303)
