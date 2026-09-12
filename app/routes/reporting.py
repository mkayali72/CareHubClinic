"""RBAC-protected server-rendered Reporting pages and exports."""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, Response

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.auth import require_authenticated_user
from app.services.reporting import (
    REPORT_DEFINITIONS,
    ReportingUnavailable,
    available_reports,
    build_report,
    export_pdf,
    export_xlsx,
)
from app.templates import create_templates

router = APIRouter(tags=["reporting"])
templates = create_templates()


def _selected_range(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    """Resolve optional filters to one inclusive range for the report UI."""

    today = date.today()
    resolved_end = end_date or today
    resolved_start = start_date or resolved_end - timedelta(days=6)
    if resolved_start > resolved_end:
        raise HTTPException(
            status_code=422,
            detail="Report start date must be on or before the end date.",
        )
    return resolved_start, resolved_end


def _report_or_error(
    db: Session,
    user: User,
    report_slug: str,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    start, end = _selected_range(start_date, end_date)
    try:
        return build_report(db, user, report_slug, start, end)
    except ReportingUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/reports", response_class=HTMLResponse)
def reporting_index(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    """List only report types permitted for the signed-in staff member."""

    return templates.TemplateResponse(
        request=request,
        name="reports/index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": "Reporting",
            "user": current_user,
            "reports": available_reports(db, current_user),
            "date_boundary_note": (
                "Date filters are inclusive: both the start date and the full end date are counted."
            ),
        },
    )


@router.get("/reports/{report_slug}/export/{export_format}")
def report_export(
    report_slug: str,
    export_format: str,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export one authorized report as PDF or Excel."""

    if export_format not in {"pdf", "xlsx"}:
        raise HTTPException(status_code=404, detail="Export format not supported.")
    report = _report_or_error(
        db,
        current_user,
        report_slug,
        start_date,
        end_date,
    )
    return export_pdf(report) if export_format == "pdf" else export_xlsx(report)


@router.get("/reports/{report_slug}", response_class=HTMLResponse)
def reporting_detail(
    request: Request,
    report_slug: str,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    """Render one authorized report and its hand-checkable detail rows."""

    report = _report_or_error(
        db,
        current_user,
        report_slug,
        start_date,
        end_date,
    )
    return templates.TemplateResponse(
        request=request,
        name="reports/detail.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "page_title": report["title"],
            "user": current_user,
            "report": report,
            "reports": available_reports(db, current_user),
            "definitions": REPORT_DEFINITIONS,
        },
    )