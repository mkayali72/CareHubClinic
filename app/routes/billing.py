"""Server-side guarded routes for the clinic-optional Billing module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import (
    FeeScheduleItem,
    InvoiceStatus,
    User,
    UserRole,
    Visit,
)
from app.services.auth import require_roles
from app.services.billing import (
    BILLING_ROLES,
    BillingModuleDisabled,
    create_fee_schedule_item,
    create_invoice,
    ensure_billing_enabled,
    get_fee_schedule,
    get_invoice_for_user,
    get_invoices,
    set_billing_enabled,
    set_invoice_status,
    update_fee_schedule_item,
)

router = APIRouter(tags=["billing"])
templates = Jinja2Templates(directory="app/templates")


def _billing_gate(
    request: Request,
    db: Session,
    user: User,
) -> Response | None:
    """Return a deliberate 404 page when Billing is disabled.

    This check is intentionally repeated at every operational route boundary.
    A hidden link is not a security control: disabled financial endpoints must
    be structurally inaccessible to direct URL/API calls too.
    """

    try:
        ensure_billing_enabled(db, user.clinic_id)
    except BillingModuleDisabled:
        return templates.TemplateResponse(
            request=request,
            name="billing/not_available.html",
            context={
                "request": request,
                "app_name": settings.app_name,
                "page_title": "Billing unavailable",
                "user": user,
                "message": "Billing is not available for this clinic.",
            },
            status_code=404,
        )
    return None


def _visit_for_route(db: Session, user: User, visit_id: int) -> Visit:
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
) -> dict[str, Any]:
    visit = _visit_for_route(db, user, visit_id)
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": "Charge entry",
        "user": user,
        "visit": visit,
        "fee_schedule": get_fee_schedule(db, user, active_only=True),
        "invoices": get_invoices(db, user, patient_id=visit.patient_id),
        "message": message,
        "error": error,
    }


@router.get("/billing", response_class=HTMLResponse)
def billing_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(*BILLING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the clinic billing work queue."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    return templates.TemplateResponse(
        request=request,
        name="billing/dashboard.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": "Billing",
            "user": current_user,
            "invoices": get_invoices(db, current_user),
        },
    )


@router.get(
    "/visits/{visit_id}/billing/charge-panel",
    response_class=HTMLResponse,
)
def charge_panel(
    request: Request,
    visit_id: int,
    current_user: User = Depends(require_roles(*BILLING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the HTMX charge-entry panel for one visit."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    return templates.TemplateResponse(
        request=request,
        name="billing/charge_panel.html",
        context=_panel_context(request, db, current_user, visit_id),
    )


@router.post(
    "/visits/{visit_id}/billing/invoices",
    response_class=HTMLResponse,
)
def create_invoice_route(
    request: Request,
    visit_id: int,
    fee_schedule_item_id: list[int] = Form(default=[]),
    notes: str = Form(""),
    current_user: User = Depends(require_roles(*BILLING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create an unpaid invoice from selected fee schedule rows."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    try:
        invoice = create_invoice(
            db,
            current_user,
            visit_id,
            fee_schedule_item_id,
            notes,
        )
        db.commit()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            message=f"Invoice #{invoice.id} created and marked unpaid.",
        )
    except (PermissionError, ValueError) as error:
        db.rollback()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            error=str(error),
        )
        return templates.TemplateResponse(
            request=request,
            name="billing/charge_panel.html",
            context=context,
            status_code=403 if isinstance(error, PermissionError) else 422,
        )
    return templates.TemplateResponse(
        request=request,
        name="billing/charge_panel.html",
        context=context,
    )


@router.post("/billing/invoices/{invoice_id}/status")
def invoice_status_route(
    request: Request,
    invoice_id: int,
    status: InvoiceStatus = Form(...),
    current_user: User = Depends(require_roles(*BILLING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Mark an invoice paid or unpaid."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    try:
        invoice = set_invoice_status(db, current_user, invoice_id, status)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=403 if isinstance(error, PermissionError) else 422,
            detail=str(error),
        ) from error
    return RedirectResponse(url=f"/billing#invoice-{invoice.id}", status_code=303)


@router.get(
    "/billing/invoices/{invoice_id}/print",
    response_class=HTMLResponse,
)
def print_invoice(
    request: Request,
    invoice_id: int,
    current_user: User = Depends(require_roles(*BILLING_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render a clinic-branded invoice suitable for browser Save as PDF."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    try:
        invoice = get_invoice_for_user(db, current_user, invoice_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return templates.TemplateResponse(
        request=request,
        name="billing/print.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "invoice": invoice,
            "clinic": current_user.clinic,
        },
    )


@router.get("/admin/billing", response_class=HTMLResponse)
def billing_admin(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the enabled-clinic fee schedule editor."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    return templates.TemplateResponse(
        request=request,
        name="billing/admin.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": "Billing administration",
            "user": current_user,
            "items": get_fee_schedule(db, current_user),
        },
    )


@router.post("/admin/billing/fees", response_class=HTMLResponse)
def create_fee_route(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    unit_price: Decimal = Form(...),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a fee schedule item for an enabled clinic."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    try:
        create_fee_schedule_item(
            db,
            current_user,
            name,
            description,
            unit_price,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=403 if isinstance(error, PermissionError) else 422,
            detail=str(error),
        ) from error
    return RedirectResponse(url="/admin/billing", status_code=303)


@router.post("/admin/billing/fees/{item_id}", response_class=HTMLResponse)
def update_fee_route(
    request: Request,
    item_id: int,
    name: str = Form(...),
    description: str = Form(""),
    unit_price: Decimal = Form(...),
    active: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Edit or deactivate a fee schedule item."""

    blocked = _billing_gate(request, db, current_user)
    if blocked is not None:
        return blocked
    item = db.scalar(
        select(FeeScheduleItem).where(
            FeeScheduleItem.id == item_id,
            FeeScheduleItem.clinic_id == current_user.clinic_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Fee schedule item not found.")
    try:
        update_fee_schedule_item(
            db,
            current_user,
            item,
            name,
            description,
            unit_price,
            active,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        raise HTTPException(
            status_code=403 if isinstance(error, PermissionError) else 422,
            detail=str(error),
        ) from error
    return RedirectResponse(url="/admin/billing", status_code=303)


@router.get("/admin/clinic-features", response_class=HTMLResponse)
def clinic_features(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
) -> Response:
    """Render feature settings even when optional Billing is disabled."""

    return templates.TemplateResponse(
        request=request,
        name="billing/features.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": "Optional modules",
            "user": current_user,
            "billing_enabled": current_user.clinic.billing_module_enabled,
        },
    )


@router.post("/admin/clinic-features/billing")
def toggle_billing(
    request: Request,
    enabled: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Enable or disable Billing without changing any invoice history."""

    set_billing_enabled(db, current_user, enabled)
    db.commit()
    return RedirectResponse(url="/admin/clinic-features", status_code=303)