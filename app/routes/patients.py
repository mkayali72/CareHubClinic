"""Patient demographics HTML and API routes with clinic-scoped RBAC."""

from datetime import date
import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import Patient, User, UserRole
from app.services.audit import soft_delete_record
from app.services.auth import require_roles
from app.services.billing import get_patient_invoices
from app.services.patients import (
    PATIENT_ROLES,
    build_patient_payload,
    can_view_clinical_patient_fields,
    create_patient,
    get_patient_for_user,
    patient_form_values,
    serialize_patient,
    update_patient,
)
from app.templates import create_templates
from app.services.prescriptions import get_current_prescriptions

router = APIRouter(tags=["patients"])
templates = create_templates()


def _patient_form_context(
    request: Request,
    current_user: User,
    patient: Patient | None,
    action: str,
) -> dict[str, Any]:
    """Build shared context for create and edit patient forms.

    Args:
        request: Incoming browser request.
        current_user: Authenticated staff user.
        patient: Existing record for edit mode, or None for create mode.
        action: Form submission URL.

    Returns:
        Jinja context for the patient form partial.
    """

    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": "Patient form",
        "patient": patient,
        "form_values": patient_form_values(patient),
        "form_action": action,
        "can_view_sensitive": can_view_clinical_patient_fields(current_user),
    }


def _form_payload(
    name: str,
    date_of_birth: date,
    contact_phone: str,
    contact_email: str,
    contact_address: str,
    insurance_provider: str,
    insurance_member_id: str,
    insurance_group_number: str,
    emergency_name: str,
    emergency_relationship: str,
    emergency_phone: str,
    allergy_name: list[str],
    allergy_reaction: list[str],
    allergy_severity: list[str],
    medication_name: list[str],
    medication_dose: list[str],
    medication_frequency: list[str],
    contraception_method: str,
    include_clinical_fields: bool,
) -> dict[str, Any]:
    """Convert submitted form fields into a validated patient payload.

    Args:
        name: Patient display name.
        date_of_birth: Patient date of birth.
        contact_phone: Primary phone.
        contact_email: Email address.
        contact_address: Mailing address.
        insurance_provider: Insurance payer.
        insurance_member_id: Insurance member identifier.
        insurance_group_number: Insurance group identifier.
        emergency_name: Emergency contact name.
        emergency_relationship: Emergency contact relationship.
        emergency_phone: Emergency contact phone.
        allergy_name: Repeated allergy names.
        allergy_reaction: Repeated allergy reactions.
        allergy_severity: Repeated allergy severities.
        medication_name: Repeated medication names.
        medication_dose: Repeated medication doses.
        medication_frequency: Repeated medication frequencies.
        contraception_method: Standing contraception method.
        include_clinical_fields: Whether sensitive fields may be written.

    Returns:
        Validated model payload.

    Raises:
        HTTPException: If structured list rows are malformed.
    """

    try:
        return build_patient_payload(
            name=name,
            date_of_birth=date_of_birth,
            contact_phone=contact_phone,
            contact_email=contact_email,
            contact_address=contact_address,
            insurance_provider=insurance_provider,
            insurance_member_id=insurance_member_id,
            insurance_group_number=insurance_group_number,
            emergency_name=emergency_name,
            emergency_relationship=emergency_relationship,
            emergency_phone=emergency_phone,
            allergy_name=allergy_name,
            allergy_reaction=allergy_reaction,
            allergy_severity=allergy_severity,
            medication_name=medication_name,
            medication_dose=medication_dose,
            medication_frequency=medication_frequency,
            contraception_method=contraception_method,
            include_clinical_fields=include_clinical_fields,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _patient_or_404(db: Session, patient_id: int, user: User) -> Patient:
    """Load a clinic-scoped patient or raise a safe not-found response.

    Args:
        db: Request-scoped SQLAlchemy session.
        patient_id: Patient identifier.
        user: Authenticated staff user.

    Returns:
        The active patient belonging to the user's clinic.

    Raises:
        HTTPException: If the patient is missing or belongs to another clinic.
    """

    patient = get_patient_for_user(db, patient_id, user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def _patient_list_query(
    db: Session,
    clinic_id: int,
    search_query: str = "",
) -> list[Patient]:
    """Return newest-first patients optionally matching name or phone.

    Args:
        db: Request-scoped SQLAlchemy session.
        clinic_id: Clinic whose active patients may be returned.
        search_query: User-entered name or phone fragment.

    Returns:
        Active patients in the clinic that match the search, or all clinic
        patients when the search is blank.
    """

    statement = select(Patient).where(Patient.clinic_id == clinic_id)
    normalized_query = search_query.strip()
    if normalized_query:
        phone_value = Patient.contact_info["phone"].as_string()
        phone_conditions = [
            Patient.name.ilike(f"%{normalized_query}%"),
            phone_value.ilike(f"%{normalized_query}%"),
        ]
        digits_only_query = re.sub(r"\D", "", normalized_query)
        if digits_only_query:
            compact_phone_value = phone_value
            for character in (" ", "-", "(", ")", "+", "."):
                compact_phone_value = func.replace(
                    compact_phone_value,
                    character,
                    "",
                )
            phone_conditions.append(
                compact_phone_value.ilike(f"%{digits_only_query}%")
            )
        statement = statement.where(or_(*phone_conditions))

    return list(
        db.scalars(
            statement.order_by(Patient.created_at.desc(), Patient.id.desc())
        )
    )


def _detail_context(
    request: Request,
    db: Session,
    patient: Patient,
    current_user: User,
    active_tab: str = "summary",
    show_form: bool = False,
) -> dict[str, Any]:
    """Build the patient detail template context.

    Args:
        request: Incoming browser request.
        patient: Active patient to display.
        current_user: Authenticated staff user.
        active_tab: Selected detail tab.
        show_form: Whether the edit form should replace the summary content.

    Returns:
        Jinja context for the detail page or content fragment.
    """

    allowed_tabs = {"summary", "visits", "labs", "prescriptions", "billing"}
    if active_tab not in allowed_tabs:
        active_tab = "summary"
    if active_tab == "billing" and not patient.clinic.billing_module_enabled:
        active_tab = "summary"
    billing_enabled = patient.clinic.billing_module_enabled
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": patient.name,
        "patient": patient,
        "user": current_user,
        "active_tab": active_tab,
        "show_form": show_form,
        "form_values": patient_form_values(patient),
        "can_view_sensitive": can_view_clinical_patient_fields(current_user),
        "can_delete": current_user.role is UserRole.CLINIC_ADMIN,
        "billing_enabled": billing_enabled,
        "can_operate_billing": current_user.role
        in {UserRole.BILLING_CLERK, UserRole.CLINIC_ADMIN},
        "billing_invoices": (
            get_patient_invoices(db, current_user, patient.id)
            if billing_enabled
            else []
        ),
        "current_prescriptions": (
            get_current_prescriptions(db, current_user, patient.id)
            if can_view_clinical_patient_fields(current_user)
            else []
        ),
    }


@router.get("/patients", response_class=HTMLResponse)
def patient_list(
    request: Request,
    search: str = Query(default=""),
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the clinic-scoped patient list, newest records first.

    Args:
        request: Incoming browser request.
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        The patient list page.
    """

    patients = _patient_list_query(db, current_user.clinic_id, search)
    return templates.TemplateResponse(
        request=request,
        name="patients/list.html",
        context={
            "app_name": settings.app_name,
            "page_title": "Patients",
            "user": current_user,
            "patients": patients,
            "search_query": search.strip(),
            "can_view_sensitive": can_view_clinical_patient_fields(current_user),
            "can_delete": current_user.role is UserRole.CLINIC_ADMIN,
        },
    )


@router.get("/patients/rows", response_class=HTMLResponse)
def patient_rows(
    request: Request,
    search: str = Query(default=""),
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the htmx-refreshable patient table rows.

    Args:
        request: Incoming htmx request.
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        An HTML table-row fragment.
    """

    patients = _patient_list_query(db, current_user.clinic_id, search)
    return templates.TemplateResponse(
        request=request,
        name="patients/partials/rows.html",
        context={
            "request": request,
            "patients": patients,
            "search_query": search.strip(),
            "user": current_user,
            "can_view_sensitive": can_view_clinical_patient_fields(current_user),
            "can_delete": current_user.role is UserRole.CLINIC_ADMIN,
        },
    )


@router.get("/api/patients")
def patient_api_list(
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return role-projected patient demographics for the authenticated clinic.

    Args:
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        JSON containing only fields permitted for the current role.
    """

    patients = db.scalars(
        select(Patient)
        .where(Patient.clinic_id == current_user.clinic_id)
        .order_by(Patient.created_at.desc(), Patient.id.desc())
    )
    return JSONResponse(
        content={"patients": [serialize_patient(patient, current_user) for patient in patients]}
    )


@router.get("/api/patients/{patient_id}")
def patient_api_detail(
    patient_id: int,
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return one clinic-scoped patient with API-layer field filtering.

    Args:
        patient_id: Patient identifier.
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        JSON patient projection for the current role.

    Raises:
        HTTPException: If the patient is missing or outside the user's clinic.
    """

    patient = _patient_or_404(db, patient_id, current_user)
    return JSONResponse(content=serialize_patient(patient, current_user))


@router.get("/patients/new", response_class=HTMLResponse)
def new_patient_form(
    request: Request,
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
) -> Response:
    """Return the htmx create-patient form fragment.

    Args:
        request: Incoming browser request.
        current_user: Staff user with an allowed patient role.

    Returns:
        A patient form fragment.
    """

    return templates.TemplateResponse(
        request=request,
        name="patients/partials/form_container.html",
        context=_patient_form_context(request, current_user, None, "/patients"),
    )


@router.post("/patients", response_class=HTMLResponse)
def create_patient_route(
    request: Request,
    name: str = Form(...),
    date_of_birth: date = Form(...),
    contact_phone: str = Form(""),
    contact_email: str = Form(""),
    contact_address: str = Form(""),
    insurance_provider: str = Form(""),
    insurance_member_id: str = Form(""),
    insurance_group_number: str = Form(""),
    emergency_name: str = Form(""),
    emergency_relationship: str = Form(""),
    emergency_phone: str = Form(""),
    allergy_name: list[str] = Form(default=[]),
    allergy_reaction: list[str] = Form(default=[]),
    allergy_severity: list[str] = Form(default=[]),
    medication_name: list[str] = Form(default=[]),
    medication_dose: list[str] = Form(default=[]),
    medication_frequency: list[str] = Form(default=[]),
    contraception_method: str = Form(""),
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a patient through the htmx form and return a success fragment.

    Args:
        request: Incoming form request.
        name: Patient display name.
        date_of_birth: Patient date of birth.
        contact_phone: Primary phone.
        contact_email: Email address.
        contact_address: Mailing address.
        insurance_provider: Insurance payer.
        insurance_member_id: Insurance member identifier.
        insurance_group_number: Insurance group identifier.
        emergency_name: Emergency contact name.
        emergency_relationship: Emergency contact relationship.
        emergency_phone: Emergency contact phone.
        allergy_name: Repeated allergy names.
        allergy_reaction: Repeated allergy reactions.
        allergy_severity: Repeated allergy severities.
        medication_name: Repeated medication names.
        medication_dose: Repeated medication doses.
        medication_frequency: Repeated medication frequencies.
        contraception_method: Standing contraception method.
        current_user: Staff user creating the record.
        db: Request-scoped SQLAlchemy session.

    Returns:
        An htmx success fragment with a link to the new patient.
    """

    payload = _form_payload(
        name,
        date_of_birth,
        contact_phone,
        contact_email,
        contact_address,
        insurance_provider,
        insurance_member_id,
        insurance_group_number,
        emergency_name,
        emergency_relationship,
        emergency_phone,
        allergy_name,
        allergy_reaction,
        allergy_severity,
        medication_name,
        medication_dose,
        medication_frequency,
        contraception_method,
        can_view_clinical_patient_fields(current_user),
    )
    patient = create_patient(db, current_user.clinic_id, current_user, payload)
    db.commit()
    response = templates.TemplateResponse(
        request=request,
        name="patients/partials/create_success.html",
        context={"request": request, "patient": patient},
    )
    response.headers["HX-Trigger"] = "patientsChanged"
    return response


@router.get("/patients/{patient_id}", response_class=HTMLResponse)
def patient_detail(
    request: Request,
    patient_id: int,
    tab: str = "summary",
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the tabbed patient detail page.

    Args:
        request: Incoming browser request.
        patient_id: Patient identifier.
        tab: Active tab name.
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        The patient detail page with placeholder future-module tabs.
    """

    patient = _patient_or_404(db, patient_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name="patients/detail.html",
        context=_detail_context(request, db, patient, current_user, tab),
    )


@router.get("/patients/{patient_id}/edit", response_class=HTMLResponse)
def edit_patient_form(
    request: Request,
    patient_id: int,
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the htmx edit form for a clinic-scoped patient.

    Args:
        request: Incoming browser request.
        patient_id: Patient identifier.
        current_user: Staff user with an allowed patient role.
        db: Request-scoped SQLAlchemy session.

    Returns:
        The patient detail content with its edit form.
    """

    patient = _patient_or_404(db, patient_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name="patients/partials/content.html",
        context=_detail_context(request, db, patient, current_user, show_form=True),
    )


@router.post("/patients/{patient_id}/edit", response_class=HTMLResponse)
def update_patient_route(
    request: Request,
    patient_id: int,
    name: str = Form(...),
    date_of_birth: date = Form(...),
    contact_phone: str = Form(""),
    contact_email: str = Form(""),
    contact_address: str = Form(""),
    insurance_provider: str = Form(""),
    insurance_member_id: str = Form(""),
    insurance_group_number: str = Form(""),
    emergency_name: str = Form(""),
    emergency_relationship: str = Form(""),
    emergency_phone: str = Form(""),
    allergy_name: list[str] = Form(default=[]),
    allergy_reaction: list[str] = Form(default=[]),
    allergy_severity: list[str] = Form(default=[]),
    medication_name: list[str] = Form(default=[]),
    medication_dose: list[str] = Form(default=[]),
    medication_frequency: list[str] = Form(default=[]),
    contraception_method: str = Form(""),
    current_user: User = Depends(require_roles(*PATIENT_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Update a patient using an htmx form without a full page reload.

    Args:
        request: Incoming form request.
        patient_id: Patient identifier.
        name: Patient display name.
        date_of_birth: Patient date of birth.
        contact_phone: Primary phone.
        contact_email: Email address.
        contact_address: Mailing address.
        insurance_provider: Insurance payer.
        insurance_member_id: Insurance member identifier.
        insurance_group_number: Insurance group identifier.
        emergency_name: Emergency contact name.
        emergency_relationship: Emergency contact relationship.
        emergency_phone: Emergency contact phone.
        allergy_name: Repeated allergy names.
        allergy_reaction: Repeated allergy reactions.
        allergy_severity: Repeated allergy severities.
        medication_name: Repeated medication names.
        medication_dose: Repeated medication doses.
        medication_frequency: Repeated medication frequencies.
        contraception_method: Standing contraception method.
        current_user: Staff user updating the record.
        db: Request-scoped SQLAlchemy session.

    Returns:
        Updated patient detail content.
    """

    patient = _patient_or_404(db, patient_id, current_user)
    payload = _form_payload(
        name,
        date_of_birth,
        contact_phone,
        contact_email,
        contact_address,
        insurance_provider,
        insurance_member_id,
        insurance_group_number,
        emergency_name,
        emergency_relationship,
        emergency_phone,
        allergy_name,
        allergy_reaction,
        allergy_severity,
        medication_name,
        medication_dose,
        medication_frequency,
        contraception_method,
        can_view_clinical_patient_fields(current_user),
    )
    if not can_view_clinical_patient_fields(current_user):
        payload = {
            key: value
            for key, value in payload.items()
            if key in {"name", "date_of_birth", "contact_info", "insurance_info"}
        }
    update_patient(db, patient, current_user, payload)
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="patients/partials/content.html",
        context=_detail_context(request, db, patient, current_user),
    )


@router.post("/patients/{patient_id}/delete")
def delete_patient(
    request: Request,
    patient_id: int,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Soft-delete a patient and write a delete audit event.

    Args:
        request: Incoming browser or htmx request.
        patient_id: Patient identifier.
        current_user: Clinic administrator authorizing the deletion.
        db: Request-scoped SQLAlchemy session.

    Returns:
        An htmx row/detail response or a normal redirect to the patient list.
    """

    patient = _patient_or_404(db, patient_id, current_user)
    soft_delete_record(
        db=db,
        record=patient,
        actor=current_user,
        entity_type="patient",
        entity_id=patient.id,
    )
    db.commit()
    if request.headers.get("HX-Request") == "true":
        if request.headers.get("HX-Target") == "#patient-detail":
            return templates.TemplateResponse(
                request=request,
                name="patients/partials/deleted.html",
                context={"request": request},
            )
        response = Response(status_code=200, content="")
        response.headers["HX-Trigger"] = "patientsChanged"
        return response
    return RedirectResponse(url="/patients", status_code=303)