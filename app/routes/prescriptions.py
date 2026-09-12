"""Prescription ordering, print views, and clinic formulary administration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.database import get_db
from app.models import (
    MedicationDefinition,
    PregnancySafetyFlag,
    User,
    UserRole,
    Visit,
)
from app.services.auth import require_roles
from app.services.clinical import CLINICAL_ROLES
from app.services.prescriptions import (
    PrescriptionWarningRequired,
    create_medication_definition,
    create_prescription,
    get_current_prescriptions,
    get_medication_definitions,
    get_prescription_for_user,
    get_visit_prescriptions,
    update_medication_definition,
)
from app.templates import create_templates

router = APIRouter(tags=["prescriptions"])
templates = create_templates()


def _visit_or_404(db: Session, visit_id: int, user: User) -> Visit:
    """Load an active visit belonging to the authenticated clinic."""

    visit = db.scalar(
        select(Visit).where(
            Visit.id == visit_id,
            Visit.clinic_id == user.clinic_id,
        )
    )
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found.")
    return visit


def _panel_context(
    request: Request,
    db: Session,
    user: User,
    visit_id: int,
    *,
    message: str = "",
    error: str = "",
    warnings: dict[str, str] | None = None,
    selected_medication_id: int | None = None,
    form_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the inline prescription panel without replacing the note."""

    visit = _visit_or_404(db, visit_id, user)
    return {
        "request": request,
        "user": user,
        "visit": visit,
        "medication_definitions": get_medication_definitions(
            db,
            user.clinic_id,
            active_only=True,
        ),
        "prescriptions": get_visit_prescriptions(db, user, visit.id),
        "can_prescribe": user.role is UserRole.PHYSICIAN,
        "message": message,
        "error": error,
        "warnings": warnings or {},
        "selected_medication_id": selected_medication_id,
        "form_values": form_values
        or {"dosage": "", "frequency": "", "duration": ""},
    }


@router.get(
    "/visits/{visit_id}/prescriptions/order-panel",
    response_class=HTMLResponse,
)
def prescription_order_panel(
    request: Request,
    visit_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the HTMX prescription slide-over for a saved visit."""

    context = _panel_context(request, db, current_user, visit_id)
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="prescriptions/order_panel.html",
        context=context,
    )


@router.post(
    "/visits/{visit_id}/prescriptions",
    response_class=HTMLResponse,
)
def create_prescription_route(
    request: Request,
    visit_id: int,
    medication_definition_id: int = Form(...),
    dosage: str = Form(""),
    frequency: str = Form(""),
    duration: str = Form(""),
    acknowledge_pregnancy_warning: bool = Form(False),
    acknowledge_allergy_warning: bool = Form(False),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a prescription or return the required warning acknowledgment UI."""

    values = {
        "dosage": dosage,
        "frequency": frequency,
        "duration": duration,
    }
    try:
        create_prescription(
            db,
            current_user,
            visit_id,
            medication_definition_id,
            dosage,
            frequency,
            duration,
            acknowledge_pregnancy_warning=acknowledge_pregnancy_warning,
            acknowledge_allergy_warning=acknowledge_allergy_warning,
        )
        db.commit()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            message="Prescription confirmed and added to current medications.",
        )
    except PrescriptionWarningRequired as warning:
        db.rollback()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            warnings=warning.warnings,
            selected_medication_id=medication_definition_id,
            form_values=values,
        )
        return templates.TemplateResponse(
            request=request,
            name="prescriptions/order_panel.html",
            context=context,
            status_code=422,
        )
    except (PermissionError, ValueError) as error:
        db.rollback()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            error=str(error),
            selected_medication_id=medication_definition_id,
            form_values=values,
        )
        return templates.TemplateResponse(
            request=request,
            name="prescriptions/order_panel.html",
            context=context,
            status_code=403 if isinstance(error, PermissionError) else 422,
        )
    return templates.TemplateResponse(
        request=request,
        name="prescriptions/order_panel.html",
        context=context,
    )


@router.get("/patients/{patient_id}/prescriptions", response_class=HTMLResponse)
def patient_prescriptions(
    request: Request,
    patient_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render a patient's active prescription list as a reusable fragment."""

    return templates.TemplateResponse(
        request=request,
        name="patients/partials/prescriptions.html",
        context={
            "request": request,
            "user": current_user,
            "current_prescriptions": get_current_prescriptions(
                db,
                current_user,
                patient_id,
            ),
            "standalone": True,
        },
    )


@router.get("/prescriptions/{prescription_id}/print", response_class=HTMLResponse)
def print_prescription(
    request: Request,
    prescription_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render a clinic-branded print view suitable for browser Save as PDF."""

    try:
        prescription = get_prescription_for_user(db, current_user, prescription_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="prescriptions/print.html",
        context={
            "request": request,
            "prescription": prescription,
            "clinic": prescription.patient.clinic,
            "app_name": prescription.patient.clinic.name,
        },
    )


def _admin_context(request: Request, db: Session, user: User) -> dict[str, Any]:
    """Build formulary administration context."""

    return {
        "request": request,
        "user": user,
        "definitions": get_medication_definitions(db, user.clinic_id),
        "safety_flags": list(PregnancySafetyFlag),
        "message": "",
        "error": "",
    }


@router.get("/admin/prescriptions", response_class=HTMLResponse)
def prescription_admin(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the clinic-admin medication formulary screen."""

    context = _admin_context(request, db, current_user)
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="prescriptions/admin.html",
        context=context,
    )


@router.post("/admin/prescriptions/medications", response_class=HTMLResponse)
def create_medication_definition_route(
    name: str = Form(...),
    description: str = Form(""),
    pregnancy_safety_flag: str = Form(...),
    allergy_category: str = Form(""),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a clinic formulary entry."""

    try:
        create_medication_definition(
            db,
            current_user,
            name,
            description,
            pregnancy_safety_flag,
            allergy_category,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=403 if isinstance(error, PermissionError) else 422,
            detail=str(error),
        ) from error
    return RedirectResponse(url="/admin/prescriptions", status_code=303)


@router.post(
    "/admin/prescriptions/medications/{definition_id}",
    response_class=HTMLResponse,
)
def update_medication_definition_route(
    definition_id: int,
    name: str = Form(...),
    description: str = Form(""),
    pregnancy_safety_flag: str = Form(...),
    allergy_category: str = Form(""),
    active: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Edit or deactivate a clinic formulary entry."""

    definition = db.scalar(
        select(MedicationDefinition).where(
            MedicationDefinition.id == definition_id,
            MedicationDefinition.clinic_id == current_user.clinic_id,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Medication not found.")
    try:
        update_medication_definition(
            db,
            definition,
            current_user,
            name,
            description,
            pregnancy_safety_flag,
            allergy_category,
            active,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=403 if isinstance(error, PermissionError) else 422,
            detail=str(error),
        ) from error
    return RedirectResponse(url="/admin/prescriptions", status_code=303)