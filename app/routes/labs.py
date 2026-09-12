"""HTMX lab ordering, result, pending-work, and clinic-admin routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.database import get_db
from app.models import (
    LabOrder,
    LabOrderSet,
    LabResult,
    LabTestDefinition,
    User,
    UserRole,
    Visit,
)
from app.services.auth import require_roles
from app.services.clinical import CLINICAL_ROLES
from app.services.labs import (
    LAB_RESULT_MAX_BYTES,
    create_lab_order_set,
    create_lab_result,
    create_lab_test_definition,
    get_lab_order_sets,
    get_lab_result_for_user,
    get_lab_test_definitions,
    get_pending_lab_orders,
    get_visit_lab_orders,
    lab_file_path_for_result,
    order_lab_tests,
    review_lab_result,
    update_lab_order_set,
    update_lab_test_definition,
)

router = APIRouter(tags=["labs"])
templates = Jinja2Templates(directory="app/templates")


def _error(error: ValueError | PermissionError) -> None:
    status = 403 if isinstance(error, PermissionError) else 422
    raise HTTPException(status_code=status, detail=str(error)) from error


def _visit_or_404(db: Session, visit_id: int, user: User) -> Any:
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
    """Build the inline slide-over context without navigating away from a visit."""

    visit = _visit_or_404(db, visit_id, user)
    return {
        "request": request,
        "user": user,
        "visit": visit,
        "lab_definitions": get_lab_test_definitions(
            db,
            user.clinic_id,
            active_only=True,
        ),
        "lab_order_sets": get_lab_order_sets(
            db,
            user.clinic_id,
            active_only=True,
        ),
        "lab_orders": get_visit_lab_orders(db, user, visit.id),
        "message": message,
        "error": error,
    }


@router.get(
    "/visits/{visit_id}/labs/order-panel",
    response_class=HTMLResponse,
)
def lab_order_panel(
    request: Request,
    visit_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the HTMX slide-over used to order labs from a visit note."""

    context = _panel_context(request, db, current_user, visit_id)
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="labs/order_panel.html",
        context=context,
    )


@router.post(
    "/visits/{visit_id}/labs/orders",
    response_class=HTMLResponse,
)
def create_lab_orders_route(
    request: Request,
    visit_id: int,
    definition_ids: list[int] = Form(default=[]),
    order_set_id: int | None = Form(None),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create individual and/or order-set lab orders inside the open panel."""

    try:
        order_lab_tests(
            db,
            current_user,
            visit_id,
            definition_ids,
            order_set_id,
        )
        db.commit()
        context = _panel_context(
            request,
            db,
            current_user,
            visit_id,
            message="Lab orders created.",
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
            name="labs/order_panel.html",
            context=context,
            status_code=422 if isinstance(error, ValueError) else 403,
        )
    return templates.TemplateResponse(
        request=request,
        name="labs/order_panel.html",
        context=context,
    )


def _order_for_user(db: Session, order_id: int, user: User) -> LabOrder:
    order = db.scalar(
        select(LabOrder)
        .options(joinedload(LabOrder.visit))
        .where(
            LabOrder.id == order_id,
            LabOrder.clinic_id == user.clinic_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Lab order not found.")
    return order


@router.post(
    "/lab-orders/{order_id}/result",
    response_class=HTMLResponse,
)
async def create_lab_result_route(
    request: Request,
    order_id: int,
    manual_value: str = Form(""),
    result_file: UploadFile | None = File(None),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Accept a manual or securely validated uploaded lab result."""

    order = _order_for_user(db, order_id, current_user)
    content = None
    filename = None
    content_type = None
    if result_file is not None and result_file.filename:
        filename = result_file.filename
        content_type = result_file.content_type
        content = await result_file.read(LAB_RESULT_MAX_BYTES + 1)
    try:
        create_lab_result(
            db,
            order,
            current_user,
            manual_value=manual_value,
            filename=filename,
            content_type=content_type,
            content=content,
        )
        db.commit()
        context = _panel_context(
            request,
            db,
            current_user,
            order.visit_id,
            message="Lab result saved as resulted.",
        )
    except (PermissionError, ValueError) as error:
        db.rollback()
        context = _panel_context(
            request,
            db,
            current_user,
            order.visit_id,
            error=str(error),
        )
        return templates.TemplateResponse(
            request=request,
            name="labs/order_panel.html",
            context=context,
            status_code=422 if isinstance(error, ValueError) else 403,
        )
    return templates.TemplateResponse(
        request=request,
        name="labs/order_panel.html",
        context=context,
    )


@router.post(
    "/lab-results/{result_id}/review",
    response_class=HTMLResponse,
)
def review_lab_result_route(
    request: Request,
    result_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Record physician sign-off and distinguish reviewed from merely resulted."""

    result = db.scalar(
        select(LabResult)
        .options(joinedload(LabResult.lab_order))
        .join(LabResult.lab_order)
        .where(
            LabResult.id == result_id,
            LabOrder.clinic_id == current_user.clinic_id,
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Lab result not found.")
    try:
        review_lab_result(db, result, current_user)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _error(error)
    return RedirectResponse(
        url=f"/visits/{result.lab_order.visit_id}",
        status_code=303,
    )


@router.get("/lab-results/{result_id}/file")
def lab_result_file(
    result_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Serve a private result file only after clinic and clinical-role checks."""

    try:
        result = get_lab_result_for_user(db, result_id, current_user)
        path = lab_file_path_for_result(result)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        path,
        media_type=result.content_type or "application/octet-stream",
        filename=result.original_filename or "lab-result",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/labs/pending", response_class=HTMLResponse)
def pending_labs(
    request: Request,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the clinic-scoped outstanding lab order queue."""

    return templates.TemplateResponse(
        request=request,
        name="labs/pending.html",
        context={
            "request": request,
            "user": current_user,
            "pending_orders": get_pending_lab_orders(db, current_user),
        },
    )


def _admin_context(request: Request, db: Session, user: User) -> dict[str, Any]:
    return {
        "request": request,
        "user": user,
        "definitions": get_lab_test_definitions(db, user.clinic_id),
        "order_sets": get_lab_order_sets(db, user.clinic_id),
        "message": "",
        "error": "",
    }


@router.get("/admin/labs", response_class=HTMLResponse)
def lab_admin(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    """Render clinic-admin catalog and order-set management screens."""

    context = _admin_context(request, db, current_user)
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="labs/admin.html",
        context=context,
    )


@router.post("/admin/labs/test-definitions", response_class=HTMLResponse)
def create_lab_definition_route(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    try:
        create_lab_test_definition(db, current_user, name, description)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _error(error)
    return RedirectResponse(url="/admin/labs", status_code=303)


@router.post("/admin/labs/test-definitions/{definition_id}", response_class=HTMLResponse)
def update_lab_definition_route(
    definition_id: int,
    name: str = Form(...),
    description: str = Form(""),
    active: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    definition = db.scalar(
        select(LabTestDefinition).where(
            LabTestDefinition.id == definition_id,
            LabTestDefinition.clinic_id == current_user.clinic_id,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Lab test not found.")
    try:
        update_lab_test_definition(
            db,
            definition,
            current_user,
            name,
            description,
            active,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _error(error)
    return RedirectResponse(url="/admin/labs", status_code=303)


@router.post("/admin/labs/order-sets", response_class=HTMLResponse)
def create_lab_order_set_route(
    name: str = Form(...),
    description: str = Form(""),
    definition_ids: list[int] = Form(default=[]),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    try:
        create_lab_order_set(
            db,
            current_user,
            name,
            description,
            definition_ids,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _error(error)
    return RedirectResponse(url="/admin/labs", status_code=303)


@router.post("/admin/labs/order-sets/{order_set_id}", response_class=HTMLResponse)
def update_lab_order_set_route(
    order_set_id: int,
    name: str = Form(...),
    description: str = Form(""),
    definition_ids: list[int] = Form(default=[]),
    active: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.CLINIC_ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    order_set = db.scalar(
        select(LabOrderSet)
        .options(joinedload(LabOrderSet.test_definitions))
        .where(
            LabOrderSet.id == order_set_id,
            LabOrderSet.clinic_id == current_user.clinic_id,
        )
    )
    if order_set is None:
        raise HTTPException(status_code=404, detail="Lab order set not found.")
    try:
        update_lab_order_set(
            db,
            order_set,
            current_user,
            name,
            description,
            definition_ids,
            active,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _error(error)
    return RedirectResponse(url="/admin/labs", status_code=303)