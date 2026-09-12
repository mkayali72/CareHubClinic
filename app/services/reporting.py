"""Clinic-scoped reporting queries, authorization, and lightweight exports.

Every report accepts an inclusive ``start_date`` and ``end_date``. Date columns
use ``start_date <= value <= end_date``. Appointment and timestamp columns use
the equivalent half-open interval ``[start at 00:00, day after end at 00:00)``
so every appointment on the end date is included.

The query functions intentionally return plain dictionaries. This keeps the
report numbers testable without rendering a template and gives the HTML, PDF,
and XLSX views one shared source of truth.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any, Callable
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from starlette.responses import Response

from app.models import (
    Appointment,
    AppointmentStatus,
    Charge,
    Clinic,
    DeliveryOutcome,
    Invoice,
    InvoiceStatus,
    Patient,
    PregnancyEpisode,
    PregnancyEpisodeStatus,
    User,
    UserRole,
    Visit,
)
from app.services.billing import ensure_billing_enabled
from app.services.clinical import CLINICAL_ROLES, gestational_age

SCHEDULING_REPORT_ROLES = (
    UserRole.PHYSICIAN,
    UserRole.NURSE_MA,
    UserRole.FRONT_DESK,
    UserRole.CLINIC_ADMIN,
)
FINANCIAL_REPORT_ROLES = (UserRole.CLINIC_ADMIN, UserRole.BILLING_CLERK)


class ReportingUnavailable(ValueError):
    """Raised when an authorized report is not currently available."""


REPORT_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "slug": "schedule",
        "title": "Daily schedule & census",
        "description": "Appointment volume, active census, and status mix by day.",
        "audience": "scheduling",
    },
    {
        "slug": "revenue",
        "title": "Revenue summary",
        "description": "Invoice totals and paid/unpaid financial activity.",
        "audience": "financial",
    },
    {
        "slug": "no-show-rate",
        "title": "No-show rate",
        "description": "No-shows divided by eligible appointments, excluding cancellations.",
        "audience": "scheduling",
    },
    {
        "slug": "screening",
        "title": "Patients due for screening",
        "description": "Pap and HPV due dates that are overdue as of the report end date.",
        "audience": "clinical",
    },
    {
        "slug": "pregnancies",
        "title": "Active pregnancies by trimester",
        "description": "Active pregnancy episodes grouped by gestational trimester.",
        "audience": "clinical",
    },
    {
        "slug": "deliveries",
        "title": "Delivery outcomes log",
        "description": "Delivery dates, modes, complications, and newborn measures.",
        "audience": "clinical",
    },
)

REPORT_BUILDERS: dict[str, Callable[[Session, User, date, date], dict[str, Any]]] = {}


def validate_date_range(start_date: date, end_date: date) -> None:
    """Reject an inverted inclusive date range before executing a report."""

    if start_date > end_date:
        raise ValueError("Report start date must be on or before the end date.")


def _appointment_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Return the half-open local-datetime bounds for an inclusive date range."""

    return (
        datetime.combine(start_date, time.min),
        datetime.combine(end_date + timedelta(days=1), time.min),
    )


def _definition(slug: str) -> dict[str, str]:
    for definition in REPORT_DEFINITIONS:
        if definition["slug"] == slug:
            return definition
    raise ValueError("Unknown report.")


def available_reports(db: Session, user: User) -> list[dict[str, str]]:
    """Return only reports the user's role and clinic configuration may open."""

    clinic = db.scalar(select(Clinic).where(Clinic.id == user.clinic_id))
    billing_enabled = bool(clinic and clinic.billing_module_enabled)
    available: list[dict[str, str]] = []
    for definition in REPORT_DEFINITIONS:
        audience = definition["audience"]
        allowed = (
            (audience == "scheduling" and user.role in SCHEDULING_REPORT_ROLES)
            or (audience == "clinical" and user.role in CLINICAL_ROLES)
            or (
                audience == "financial"
                and user.role in FINANCIAL_REPORT_ROLES
                and billing_enabled
            )
        )
        if allowed:
            available.append(definition)
    return available


def ensure_report_access(db: Session, user: User, slug: str) -> None:
    """Apply server-side RBAC and Billing feature checks for one report."""

    definition = _definition(slug)
    audience = definition["audience"]
    if audience == "financial":
        if user.role not in FINANCIAL_REPORT_ROLES:
            raise PermissionError("Financial reports require Billing permissions.")
        try:
            ensure_billing_enabled(db, user.clinic_id)
        except ValueError as error:
            raise ReportingUnavailable(
                "Revenue reporting is not available while Billing is disabled."
            ) from error
    elif audience == "clinical":
        if user.role not in CLINICAL_ROLES:
            raise PermissionError("This report requires a clinical role.")
    elif user.role not in SCHEDULING_REPORT_ROLES:
        raise PermissionError("This report requires a scheduling role.")


def daily_schedule_census(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Count active appointments and unique patients for each inclusive day.

    Cancelled and no-show appointments remain in the status mix because this is
    a schedule report, but ``active_census`` counts only appointments that are
    not cancelled or no-show. Soft-deleted appointments and patients are
    excluded. The appointment end date is inclusive through the full day.
    """

    validate_date_range(start_date, end_date)
    start_at, end_at = _appointment_bounds(start_date, end_date)
    query = (
        select(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor),
            joinedload(Appointment.appointment_type),
        )
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.clinic_id == user.clinic_id,
            Appointment.deleted_at.is_(None),
            Patient.deleted_at.is_(None),
            Appointment.scheduled_at >= start_at,
            Appointment.scheduled_at < end_at,
        )
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
    )
    appointments = list(db.scalars(query))
    by_day: dict[date, list[Appointment]] = defaultdict(list)
    for appointment in appointments:
        by_day[appointment.scheduled_at.date()].append(appointment)

    days: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        day_appointments = by_day.get(cursor, [])
        status_counts = {status.value: 0 for status in AppointmentStatus}
        active_patients: set[int] = set()
        rows: list[dict[str, Any]] = []
        for appointment in day_appointments:
            status_counts[appointment.status.value] += 1
            if appointment.status not in (
                AppointmentStatus.CANCELLED,
                AppointmentStatus.NO_SHOW,
            ):
                active_patients.add(appointment.patient_id)
            rows.append(
                {
                    "id": appointment.id,
                    "time": appointment.scheduled_at.strftime("%H:%M"),
                    "patient": appointment.patient.name,
                    "doctor": appointment.doctor.full_name if appointment.doctor else "Unassigned",
                    "type": (
                        appointment.appointment_type.name
                        if appointment.appointment_type
                        else "Appointment type removed"
                    ),
                    "status": appointment.status.value,
                }
            )
        days.append(
            {
                "date": cursor,
                "total_appointments": len(day_appointments),
                "active_census": len(active_patients),
                "status_counts": status_counts,
                "rows": rows,
            }
        )
        cursor += timedelta(days=1)
    return {
        "slug": "schedule",
        "title": "Daily schedule & census",
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "total_appointments": len(appointments),
    }


def revenue_summary(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Summarize active invoices created on inclusive calendar dates.

    Gross revenue is the sum of non-deleted charge snapshots on active invoices.
    Paid and unpaid totals are split by invoice status. Soft-deleted invoices,
    charges, visits, and patients are excluded. Disabling Billing does not make
    this historical query available: the module gate still applies at read time.
    """

    validate_date_range(start_date, end_date)
    ensure_billing_enabled(db, user.clinic_id)
    query = (
        select(Invoice)
        .options(
            joinedload(Invoice.patient),
            joinedload(Invoice.visit),
            selectinload(Invoice.charges.and_(Charge.deleted_at.is_(None))),
        )
        .join(Patient, Patient.id == Invoice.patient_id)
        .join(Visit, Visit.id == Invoice.visit_id)
        .where(
            Invoice.clinic_id == user.clinic_id,
            Invoice.deleted_at.is_(None),
            Patient.deleted_at.is_(None),
            Visit.deleted_at.is_(None),
            Invoice.created_at.is_not(None),
            func.date(Invoice.created_at) >= start_date,
            func.date(Invoice.created_at) <= end_date,
        )
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
    )
    invoices = list(db.scalars(query))
    rows: list[dict[str, Any]] = []
    gross = Decimal("0.00")
    paid = Decimal("0.00")
    unpaid = Decimal("0.00")
    for invoice in invoices:
        total = invoice.total_amount
        gross += total
        if invoice.status is InvoiceStatus.PAID:
            paid += total
        else:
            unpaid += total
        rows.append(
            {
                "invoice_id": invoice.id,
                "date": invoice.created_at.date(),
                "patient": invoice.patient.name,
                "status": invoice.status.value,
                "total": total,
                "items": [charge.description_snapshot for charge in invoice.charges],
            }
        )
    return {
        "slug": "revenue",
        "title": "Revenue summary",
        "start_date": start_date,
        "end_date": end_date,
        "invoice_count": len(invoices),
        "gross_total": gross,
        "paid_total": paid,
        "unpaid_total": unpaid,
        "paid_invoice_count": sum(
            invoice.status is InvoiceStatus.PAID for invoice in invoices
        ),
        "unpaid_invoice_count": sum(
            invoice.status is InvoiceStatus.UNPAID for invoice in invoices
        ),
        "rows": rows,
    }


def no_show_rate(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Calculate no-shows over eligible appointments in an inclusive range.

    The denominator includes scheduled, checked-in, in-room, with-doctor, done,
    and no-show appointments. Cancelled appointments are excluded from both
    numerator and denominator. Soft-deleted appointments and patients are
    excluded, and the end date includes every scheduled time on that day.
    """

    validate_date_range(start_date, end_date)
    start_at, end_at = _appointment_bounds(start_date, end_date)
    query = (
        select(Appointment)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.clinic_id == user.clinic_id,
            Appointment.deleted_at.is_(None),
            Patient.deleted_at.is_(None),
            Appointment.scheduled_at >= start_at,
            Appointment.scheduled_at < end_at,
        )
    )
    appointments = list(db.scalars(query))
    eligible = [
        appointment
        for appointment in appointments
        if appointment.status is not AppointmentStatus.CANCELLED
    ]
    no_shows = sum(
        appointment.status is AppointmentStatus.NO_SHOW for appointment in eligible
    )
    return {
        "slug": "no-show-rate",
        "title": "No-show rate",
        "start_date": start_date,
        "end_date": end_date,
        "total_appointments": len(appointments),
        "cancelled_count": len(appointments) - len(eligible),
        "eligible_count": len(eligible),
        "no_show_count": no_shows,
        "rate_percent": (
            (Decimal(no_shows) / Decimal(len(eligible)) * Decimal("100")).quantize(
                Decimal("0.01")
            )
            if eligible
            else Decimal("0.00")
        ),
    }


def patients_due_for_screening(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Find patients whose latest in-range Pap/HPV due date is overdue.

    The report examines active visits dated inclusively between the selected
    dates, keeps the latest non-empty Pap and HPV due-date field per patient,
    and marks a screening overdue when its due date is on or before
    ``end_date``. Invalid or blank JSON dates are ignored. Soft-deleted visits
    and patients are excluded; a patient appears once even when both screenings
    are overdue.
    """

    validate_date_range(start_date, end_date)
    visits = list(
        db.scalars(
            select(Visit)
            .join(Patient, Patient.id == Visit.patient_id)
            .where(
                Visit.clinic_id == user.clinic_id,
                Visit.deleted_at.is_(None),
                Patient.deleted_at.is_(None),
                Visit.visit_date >= start_date,
                Visit.visit_date <= end_date,
            )
            .options(joinedload(Visit.patient))
            .order_by(Visit.visit_date.asc(), Visit.id.asc())
        )
    )
    latest: dict[int, dict[str, Any]] = {}
    for visit in visits:
        record = latest.setdefault(
            visit.patient_id,
            {
                "patient_id": visit.patient_id,
                "patient": visit.patient.name,
                "last_visit_date": visit.visit_date,
                "pap_due_date": None,
                "hpv_due_date": None,
            },
        )
        record["last_visit_date"] = max(record["last_visit_date"], visit.visit_date)
        gyn_data = visit.gyn_data or {}
        for field in ("pap_due_date", "hpv_due_date"):
            value = gyn_data.get(field)
            if not value:
                continue
            try:
                parsed = date.fromisoformat(str(value))
            except ValueError:
                continue
            record[field] = parsed

    rows: list[dict[str, Any]] = []
    for record in latest.values():
        overdue: list[str] = []
        if record["pap_due_date"] and record["pap_due_date"] <= end_date:
            overdue.append("Pap")
        if record["hpv_due_date"] and record["hpv_due_date"] <= end_date:
            overdue.append("HPV")
        if overdue:
            rows.append({**record, "overdue": ", ".join(overdue)})
    rows.sort(key=lambda row: (row["patient"], row["patient_id"]))
    return {
        "slug": "screening",
        "title": "Patients due for screening",
        "start_date": start_date,
        "end_date": end_date,
        "patient_count": len(rows),
        "rows": rows,
    }


def active_pregnancies_by_trimester(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Snapshot active pregnancy episodes by trimester as of ``end_date``.

    Active, non-deleted episodes with LMP on or before the inclusive end date
    are counted once. Gestational age uses the episode's corrected EDD when
    present, otherwise its original EDD; first trimester is under 14 weeks,
    second is 14 through 27 weeks, and third is 28 weeks or more. This is a
    point-in-time report, so ``start_date`` documents the selected window while
    the active-pregnancy snapshot is anchored to its end.
    """

    validate_date_range(start_date, end_date)
    episodes = list(
        db.scalars(
            select(PregnancyEpisode)
            .join(Patient, Patient.id == PregnancyEpisode.patient_id)
            .where(
                PregnancyEpisode.clinic_id == user.clinic_id,
                PregnancyEpisode.deleted_at.is_(None),
                PregnancyEpisode.status == PregnancyEpisodeStatus.ACTIVE,
                PregnancyEpisode.lmp <= end_date,
                Patient.deleted_at.is_(None),
            )
            .options(joinedload(PregnancyEpisode.patient))
            .order_by(PregnancyEpisode.lmp.asc(), PregnancyEpisode.id.asc())
        )
    )
    rows: list[dict[str, Any]] = []
    counts = {"first": 0, "second": 0, "third": 0}
    for episode in episodes:
        age = gestational_age(episode, end_date)
        trimester = (
            "first" if age["weeks"] < 14 else "second" if age["weeks"] < 28 else "third"
        )
        counts[trimester] += 1
        rows.append(
            {
                "episode_id": episode.id,
                "patient": episode.patient.name,
                "lmp": episode.lmp,
                "edd": age["edd"],
                "gestational_age": age["display"],
                "trimester": trimester,
            }
        )
    return {
        "slug": "pregnancies",
        "title": "Active pregnancies by trimester",
        "start_date": start_date,
        "end_date": end_date,
        "counts": counts,
        "total": len(rows),
        "rows": rows,
    }


def delivery_outcomes_log(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """List delivery outcomes whose delivery date is in the inclusive range.

    Each active delivery outcome is joined to an active pregnancy episode and
    patient, so soft-deleted clinical records do not contribute. The log has
    one row per episode because the schema enforces one outcome per episode.
    """

    validate_date_range(start_date, end_date)
    outcomes = list(
        db.scalars(
            select(DeliveryOutcome)
            .join(PregnancyEpisode, PregnancyEpisode.id == DeliveryOutcome.pregnancy_episode_id)
            .join(Patient, Patient.id == PregnancyEpisode.patient_id)
            .where(
                PregnancyEpisode.clinic_id == user.clinic_id,
                PregnancyEpisode.deleted_at.is_(None),
                Patient.deleted_at.is_(None),
                DeliveryOutcome.delivery_date >= start_date,
                DeliveryOutcome.delivery_date <= end_date,
            )
            .options(joinedload(DeliveryOutcome.pregnancy_episode).joinedload(PregnancyEpisode.patient))
            .order_by(DeliveryOutcome.delivery_date.asc(), DeliveryOutcome.id.asc())
        )
    )
    rows = [
        {
            "outcome_id": outcome.id,
            "episode_id": outcome.pregnancy_episode_id,
            "patient": outcome.pregnancy_episode.patient.name,
            "delivery_date": outcome.delivery_date,
            "mode": outcome.mode,
            "complications": outcome.complications or "None documented",
            "birth_weight_grams": outcome.birth_weight_grams,
            "apgar_one_minute": outcome.apgar_one_minute,
            "apgar_five_minutes": outcome.apgar_five_minutes,
        }
        for outcome in outcomes
    ]
    return {
        "slug": "deliveries",
        "title": "Delivery outcomes log",
        "start_date": start_date,
        "end_date": end_date,
        "count": len(rows),
        "rows": rows,
    }


REPORT_BUILDERS.update(
    {
        "schedule": daily_schedule_census,
        "revenue": revenue_summary,
        "no-show-rate": no_show_rate,
        "screening": patients_due_for_screening,
        "pregnancies": active_pregnancies_by_trimester,
        "deliveries": delivery_outcomes_log,
    }
)


def build_report(
    db: Session,
    user: User,
    slug: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Authorize and execute one named report."""

    ensure_report_access(db, user, slug)
    validate_date_range(start_date, end_date)
    return REPORT_BUILDERS[slug](db, user, start_date, end_date)


def export_rows(report: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """Flatten a report into stable export columns and rows."""

    slug = report["slug"]
    if slug == "schedule":
        columns = ["Date", "Time", "Patient", "Doctor", "Appointment type", "Status"]
        rows = [
            [day["date"], item["time"], item["patient"], item["doctor"], item["type"], item["status"]]
            for day in report["days"]
            for item in day["rows"]
        ]
    elif slug == "revenue":
        columns = ["Invoice", "Date", "Patient", "Status", "Total", "Items"]
        rows = [
            [row["invoice_id"], row["date"], row["patient"], row["status"], row["total"], ", ".join(row["items"])]
            for row in report["rows"]
        ]
    elif slug == "no-show-rate":
        columns = ["Total appointments", "Cancelled", "Eligible", "No-shows", "No-show rate"]
        rows = [[
            report["total_appointments"],
            report["cancelled_count"],
            report["eligible_count"],
            report["no_show_count"],
            f'{report["rate_percent"]:.2f}%',
        ]]
    elif slug == "screening":
        columns = ["Patient ID", "Patient", "Last visit", "Pap due", "HPV due", "Overdue"]
        rows = [
            [
                row["patient_id"],
                row["patient"],
                row["last_visit_date"],
                row["pap_due_date"] or "",
                row["hpv_due_date"] or "",
                row["overdue"],
            ]
            for row in report["rows"]
        ]
    elif slug == "pregnancies":
        columns = ["Episode", "Patient", "LMP", "EDD", "Gestational age", "Trimester"]
        rows = [
            [row["episode_id"], row["patient"], row["lmp"], row["edd"], row["gestational_age"], row["trimester"]]
            for row in report["rows"]
        ]
    else:
        columns = [
            "Outcome",
            "Episode",
            "Patient",
            "Delivery date",
            "Mode",
            "Complications",
            "Birth weight (g)",
            "Apgar 1 min",
            "Apgar 5 min",
        ]
        rows = [
            [
                row["outcome_id"],
                row["episode_id"],
                row["patient"],
                row["delivery_date"],
                row["mode"],
                row["complications"],
                row["birth_weight_grams"] or "",
                row["apgar_one_minute"] or "",
                row["apgar_five_minutes"] or "",
            ]
            for row in report["rows"]
        ]
    return columns, rows


def export_xlsx(report: dict[str, Any]) -> Response:
    """Create a small workbook with metadata, summary, and detail rows."""

    columns, rows = export_rows(report)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.append([report["title"]])
    sheet.append(
        [
            "Inclusive date range",
            f'{report["start_date"].isoformat()} through {report["end_date"].isoformat()}',
        ]
    )
    sheet.append([])
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    header_row = 4
    for cell in sheet[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    sheet.freeze_panes = "A5"
    sheet.column_dimensions["A"].width = 18
    for column in sheet.iter_cols(min_row=header_row, max_row=sheet.max_row):
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = min(
            40,
            max(14, max(len(str(cell.value or "")) for cell in column) + 2),
        )
    buffer = BytesIO()
    workbook.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{report["slug"]}.xlsx"'},
    )


def export_pdf(report: dict[str, Any]) -> Response:
    """Create a compact text/table PDF without requiring a browser or JS."""

    columns, rows = export_rows(report)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_LEFT,
        fontSize=16,
        leading=20,
    )
    body_style = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontSize=8, leading=10)
    story: list[Any] = [
        Paragraph(escape(report["title"]), title_style),
        Paragraph(
            escape(
                f'Inclusive date range: {report["start_date"].isoformat()} through {report["end_date"].isoformat()}'
            ),
            body_style,
        ),
        Spacer(1, 0.15 * inch),
    ]
    table_data = [[Paragraph(escape(str(column)), body_style) for column in columns]]
    table_data.extend(
        [
            [
                Paragraph(
                    escape(str(value.isoformat() if isinstance(value, date) else value)),
                    body_style,
                )
                for value in row
            ]
            for row in rows
        ]
    )
    if len(table_data) == 1:
        table_data.append(
            [Paragraph("No records in this date range.", body_style)]
            + [""] * (len(columns) - 1)
        )
    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report["slug"]}.pdf"'},
    )