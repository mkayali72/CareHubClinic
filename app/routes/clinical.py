"""Clinical documentation pages and structured note actions."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import (
    DiagnosisCode,
    PhraseTemplate,
    PregnancyEpisode,
    PregnancyEpisodeStatus,
    ProcedureType,
    User,
    Visit,
    VisitType,
)
from app.services.auth import require_roles
from app.services.clinical import (
    CLINICAL_ROLES,
    FREE_TEXT_FIELDS,
    create_amendment,
    create_delivery_outcome,
    create_phrase_template,
    create_pregnancy_episode,
    create_procedure_record,
    create_visit,
    dismiss_screening_reminder,
    get_diagnosis_codes,
    get_patient_episodes,
    get_patient_visits,
    get_phrase_templates,
    get_visit_for_user,
    gestational_age,
    insert_phrase_into_visit,
    is_visit_locked,
    lock_visit,
    pregnancy_trend,
    screening_reminders,
    update_phrase_template,
    update_pregnancy_episode,
    update_visit,
)

router = APIRouter(tags=["clinical"])
templates = Jinja2Templates(directory="app/templates")


def _service_error(error: ValueError | PermissionError) -> None:
    """Translate service-layer validation into an HTTP response."""

    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    raise HTTPException(status_code=422, detail=str(error)) from error


def _patient_or_404(
    db: Session,
    patient_id: int,
    user: User,
) -> Any:
    """Load a patient through the clinical service's clinic checks."""

    from app.services.patients import get_patient_for_user

    patient = get_patient_for_user(db, patient_id, user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def _episode_or_404(
    db: Session,
    episode_id: int,
    user: User,
) -> PregnancyEpisode:
    """Load a clinic-scoped pregnancy episode."""

    episode = db.scalar(
        select(PregnancyEpisode).where(
            PregnancyEpisode.id == episode_id,
            PregnancyEpisode.clinic_id == user.clinic_id,
        )
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Pregnancy episode not found.")
    return episode


def _visit_or_404(db: Session, visit_id: int, user: User) -> Visit:
    """Load a clinic-scoped active visit."""

    visit = get_visit_for_user(db, visit_id, user)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found.")
    return visit


def _visit_type(value: str) -> VisitType:
    """Parse a browser form visit type."""

    try:
        return VisitType(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Unsupported visit type.") from error


def _procedure_type(value: str) -> ProcedureType:
    """Parse a browser form procedure type."""

    try:
        return ProcedureType(value)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="Unsupported procedure type.",
        ) from error


def _visit_values(visit: Visit | None) -> dict[str, Any]:
    """Flatten a Visit into values consumed by the single-page form."""

    if visit is None:
        return {
            "visit_type": VisitType.PRENATAL.value,
            "visit_date": date.today().isoformat(),
            "pregnancy_episode_id": "",
            "blood_pressure": "",
            "weight_kg": "",
            "height_cm": "",
            "fundal_height_cm": "",
            "fetal_heart_tones": "",
            "fetal_position": "",
            "presentation": "",
            "ultrasound_efw_grams": "",
            "ultrasound_afi_cm": "",
            "ultrasound_placenta_location": "",
            "ultrasound_presentation": "",
            "ultrasound_biometry": "",
            "menstrual_history": "",
            "pap_due_date": "",
            "hpv_due_date": "",
            "hpi": "",
            "assessment": "",
            "plan": "",
            "diagnosis_code_ids": [],
        }
    prenatal = visit.prenatal_data or {}
    ultrasound = prenatal.get("ultrasound", {})
    gyn = visit.gyn_data or {}
    return {
        "visit_type": visit.visit_type.value,
        "visit_date": visit.visit_date.isoformat(),
        "pregnancy_episode_id": visit.pregnancy_episode_id or "",
        "blood_pressure": visit.vitals.get("blood_pressure", ""),
        "weight_kg": visit.vitals.get("weight_kg") or "",
        "height_cm": visit.vitals.get("height_cm") or "",
        "fundal_height_cm": prenatal.get("fundal_height_cm") or "",
        "fetal_heart_tones": prenatal.get("fetal_heart_tones", ""),
        "fetal_position": prenatal.get("fetal_position", ""),
        "presentation": prenatal.get("presentation", ""),
        "ultrasound_efw_grams": ultrasound.get("efw_grams") or "",
        "ultrasound_afi_cm": ultrasound.get("afi_cm") or "",
        "ultrasound_placenta_location": ultrasound.get("placenta_location", ""),
        "ultrasound_presentation": ultrasound.get("presentation", ""),
        "ultrasound_biometry": ultrasound.get("biometry", ""),
        "menstrual_history": gyn.get("menstrual_history", ""),
        "pap_due_date": gyn.get("pap_due_date", ""),
        "hpv_due_date": gyn.get("hpv_due_date", ""),
        "hpi": visit.hpi,
        "assessment": visit.assessment,
        "plan": visit.plan,
        "diagnosis_code_ids": [
            link.diagnosis_code_id for link in visit.diagnosis_links
        ],
    }


def _clinical_context(
    request: Request,
    db: Session,
    user: User,
    patient_id: int,
    visit: Visit | None = None,
    saved: bool = False,
    next_action_done: bool = False,
) -> dict[str, Any]:
    """Build the complete single-page patient clinical workspace."""

    patient = _patient_or_404(db, patient_id, user)
    episodes = get_patient_episodes(db, user, patient.id)
    selected_episode = (
        visit.pregnancy_episode
        if visit is not None
        else (episodes[0] if episodes else None)
    )
    return {
        "request": request,
        "app_name": settings.app_name,
        "page_title": f"Clinical documentation · {patient.name}",
        "user": user,
        "patient": patient,
        "visit": visit,
        "visit_values": _visit_values(visit),
        "visits": get_patient_visits(db, user, patient.id),
        "episodes": episodes,
        "selected_episode": selected_episode,
        "selected_episode_age": (
            gestational_age(selected_episode) if selected_episode else None
        ),
        "trend": pregnancy_trend(db, selected_episode) if selected_episode else [],
        "reminders": (
            screening_reminders(
                db,
                selected_episode,
                visit_type=visit.visit_type if visit else None,
            )
            if selected_episode and selected_episode.status is PregnancyEpisodeStatus.ACTIVE
            else [],
        ),
        "diagnosis_codes": get_diagnosis_codes(db, user.clinic_id),
        "phrase_templates": get_phrase_templates(db, user.clinic_id),
        "visit_types": list(VisitType),
        "procedure_types": list(ProcedureType),
        "form_action": f"/visits/{visit.id}" if visit else "/visits",
        "is_locked": is_visit_locked(visit) if visit else False,
        "saved": saved,
        "next_action_done": next_action_done,
        "free_text_fields": FREE_TEXT_FIELDS,
    }


@router.get("/visits/patients/{patient_id}", response_class=HTMLResponse)
def patient_clinical_workspace(
    request: Request,
    patient_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render the single-page clinical workspace for a patient."""

    return templates.TemplateResponse(
        request=request,
        name="visits/workspace.html",
        context=_clinical_context(request, db, current_user, patient_id),
    )


@router.get("/visits/{visit_id}", response_class=HTMLResponse)
def visit_detail(
    request: Request,
    visit_id: int,
    saved: int = 0,
    next_action_done: int = 0,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Render a saved visit in the same single-page documentation workspace."""

    visit = _visit_or_404(db, visit_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name="visits/workspace.html",
        context=_clinical_context(
            request,
            db,
            current_user,
            visit.patient_id,
            visit=visit,
            saved=bool(saved),
            next_action_done=bool(next_action_done),
        ),
    )


def _visit_form_payload(
    visit_type: str,
    visit_date: date | None,
    pregnancy_episode_id: int | None,
    blood_pressure: str,
    weight_kg: str,
    height_cm: str,
    fundal_height_cm: str,
    fetal_heart_tones: str,
    fetal_position: str,
    presentation: str,
    ultrasound_efw_grams: str,
    ultrasound_afi_cm: str,
    ultrasound_placenta_location: str,
    ultrasound_presentation: str,
    ultrasound_biometry: str,
    menstrual_history: str,
    pap_due_date: date | None,
    hpv_due_date: date | None,
    hpi: str,
    assessment: str,
    plan: str,
    diagnosis_code_ids: list[int],
) -> dict[str, Any]:
    """Convert one browser note form into service-layer sections."""

    return {
        "visit_type": _visit_type(visit_type),
        "visit_date": visit_date,
        "pregnancy_episode_id": pregnancy_episode_id,
        "vitals": {
            "blood_pressure": blood_pressure,
            "weight_kg": weight_kg,
            "height_cm": height_cm,
        },
        "prenatal_data": {
            "fundal_height_cm": fundal_height_cm,
            "fetal_heart_tones": fetal_heart_tones,
            "fetal_position": fetal_position,
            "presentation": presentation,
            "ultrasound_efw_grams": ultrasound_efw_grams,
            "ultrasound_afi_cm": ultrasound_afi_cm,
            "ultrasound_placenta_location": ultrasound_placenta_location,
            "ultrasound_presentation": ultrasound_presentation,
            "ultrasound_biometry": ultrasound_biometry,
        },
        "gyn_data": {
            "menstrual_history": menstrual_history,
            "pap_due_date": pap_due_date,
            "hpv_due_date": hpv_due_date,
        },
        "hpi": hpi,
        "assessment": assessment,
        "plan": plan,
        "diagnosis_code_ids": diagnosis_code_ids,
    }


@router.post("/visits", response_class=HTMLResponse)
def create_visit_route(
    request: Request,
    patient_id: int = Form(...),
    visit_type: str = Form(...),
    visit_date: date | None = Form(None),
    pregnancy_episode_id: int | None = Form(None),
    blood_pressure: str = Form(""),
    weight_kg: str = Form(""),
    height_cm: str = Form(""),
    fundal_height_cm: str = Form(""),
    fetal_heart_tones: str = Form(""),
    fetal_position: str = Form(""),
    presentation: str = Form(""),
    ultrasound_efw_grams: str = Form(""),
    ultrasound_afi_cm: str = Form(""),
    ultrasound_placenta_location: str = Form(""),
    ultrasound_presentation: str = Form(""),
    ultrasound_biometry: str = Form(""),
    menstrual_history: str = Form(""),
    pap_due_date: date | None = Form(None),
    hpv_due_date: date | None = Form(None),
    hpi: str = Form(""),
    assessment: str = Form(""),
    plan: str = Form(""),
    diagnosis_code_ids: list[int] = Form(default=[]),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create and save a structured visit note."""

    payload = _visit_form_payload(
        visit_type,
        visit_date,
        pregnancy_episode_id,
        blood_pressure,
        weight_kg,
        height_cm,
        fundal_height_cm,
        fetal_heart_tones,
        fetal_position,
        presentation,
        ultrasound_efw_grams,
        ultrasound_afi_cm,
        ultrasound_placenta_location,
        ultrasound_presentation,
        ultrasound_biometry,
        menstrual_history,
        pap_due_date,
        hpv_due_date,
        hpi,
        assessment,
        plan,
        diagnosis_code_ids,
    )
    try:
        visit = create_visit(db, current_user, patient_id, **payload)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}?saved=1", status_code=303)


@router.post("/visits/{visit_id}", response_class=HTMLResponse)
def update_visit_route(
    request: Request,
    visit_id: int,
    visit_type: str = Form(...),
    visit_date: date | None = Form(None),
    pregnancy_episode_id: int | None = Form(None),
    blood_pressure: str = Form(""),
    weight_kg: str = Form(""),
    height_cm: str = Form(""),
    fundal_height_cm: str = Form(""),
    fetal_heart_tones: str = Form(""),
    fetal_position: str = Form(""),
    presentation: str = Form(""),
    ultrasound_efw_grams: str = Form(""),
    ultrasound_afi_cm: str = Form(""),
    ultrasound_placenta_location: str = Form(""),
    ultrasound_presentation: str = Form(""),
    ultrasound_biometry: str = Form(""),
    menstrual_history: str = Form(""),
    pap_due_date: date | None = Form(None),
    hpv_due_date: date | None = Form(None),
    hpi: str = Form(""),
    assessment: str = Form(""),
    plan: str = Form(""),
    diagnosis_code_ids: list[int] = Form(default=[]),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Update an unlocked visit note."""

    visit = _visit_or_404(db, visit_id, current_user)
    payload = _visit_form_payload(
        visit_type,
        visit_date,
        pregnancy_episode_id,
        blood_pressure,
        weight_kg,
        height_cm,
        fundal_height_cm,
        fetal_heart_tones,
        fetal_position,
        presentation,
        ultrasound_efw_grams,
        ultrasound_afi_cm,
        ultrasound_placenta_location,
        ultrasound_presentation,
        ultrasound_biometry,
        menstrual_history,
        pap_due_date,
        hpv_due_date,
        hpi,
        assessment,
        plan,
        diagnosis_code_ids,
    )
    try:
        update_visit(db, visit, current_user, **payload)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}?saved=1", status_code=303)


@router.post("/visits/{visit_id}/lock")
def lock_visit_route(
    visit_id: int,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Manually lock a visit note."""

    visit = _visit_or_404(db, visit_id, current_user)
    try:
        lock_visit(db, visit, current_user)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}", status_code=303)


@router.post("/visits/{visit_id}/amendments")
def create_amendment_route(
    visit_id: int,
    content: str = Form(...),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Append an amendment to a locked visit."""

    visit = _visit_or_404(db, visit_id, current_user)
    try:
        create_amendment(db, visit, current_user, content)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}", status_code=303)


@router.post("/visits/{visit_id}/phrases")
def insert_phrase_route(
    visit_id: int,
    phrase_template_id: int = Form(...),
    field_name: str = Form(...),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Insert a copied phrase template into a visit free-text field."""

    visit = _visit_or_404(db, visit_id, current_user)
    template = db.scalar(
        select(PhraseTemplate).where(
            PhraseTemplate.id == phrase_template_id,
            PhraseTemplate.clinic_id == current_user.clinic_id,
        )
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Phrase template not found.")
    try:
        insert_phrase_into_visit(db, visit, template, current_user, field_name)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}", status_code=303)


@router.post("/phrase-templates")
def create_phrase_template_route(
    patient_id: int = Form(...),
    name: str = Form(...),
    body: str = Form(...),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a reusable physician phrase template."""

    try:
        template = create_phrase_template(db, current_user, name, body)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{patient_id}",
        status_code=303,
    )


@router.post("/phrase-templates/{template_id}")
def update_phrase_template_route(
    template_id: int,
    patient_id: int = Form(...),
    name: str = Form(...),
    body: str = Form(...),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Edit a phrase template without altering saved visit text."""

    template = db.scalar(
        select(PhraseTemplate).where(
            PhraseTemplate.id == template_id,
            PhraseTemplate.clinic_id == current_user.clinic_id,
        )
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Phrase template not found.")
    try:
        update_phrase_template(db, template, current_user, name, body)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{patient_id}",
        status_code=303,
    )


@router.post("/pregnancy-episodes")
def create_pregnancy_episode_route(
    patient_id: int = Form(...),
    lmp: date = Form(...),
    edd: date | None = Form(None),
    corrected_edd: date | None = Form(None),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Create a pregnancy episode for a patient."""

    try:
        episode = create_pregnancy_episode(
            db,
            current_user,
            patient_id,
            lmp,
            edd,
            corrected_edd,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{patient_id}",
        status_code=303,
    )


@router.post("/pregnancy-episodes/{episode_id}")
def update_pregnancy_episode_route(
    episode_id: int,
    lmp: date = Form(...),
    edd: date | None = Form(None),
    corrected_edd: date | None = Form(None),
    status: PregnancyEpisodeStatus = Form(PregnancyEpisodeStatus.ACTIVE),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Update pregnancy dating and status."""

    episode = _episode_or_404(db, episode_id, current_user)
    try:
        update_pregnancy_episode(
            db,
            episode,
            current_user,
            lmp,
            edd,
            corrected_edd,
            status,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{episode.patient_id}",
        status_code=303,
    )


@router.post("/pregnancy-episodes/{episode_id}/delivery")
def create_delivery_outcome_route(
    episode_id: int,
    delivery_date: date = Form(...),
    mode: str = Form(...),
    complications: str = Form(""),
    birth_weight_grams: int | None = Form(None),
    apgar_one_minute: int | None = Form(None),
    apgar_five_minutes: int | None = Form(None),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Record delivery details and close a pregnancy episode."""

    episode = _episode_or_404(db, episode_id, current_user)
    try:
        create_delivery_outcome(
            db,
            episode,
            current_user,
            delivery_date,
            mode,
            complications,
            birth_weight_grams,
            apgar_one_minute,
            apgar_five_minutes,
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{episode.patient_id}",
        status_code=303,
    )


@router.post("/pregnancy-episodes/{episode_id}/reminders/{reminder_key}/dismiss")
def dismiss_reminder_route(
    episode_id: int,
    reminder_key: str,
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Hide a calculated screening reminder."""

    episode = _episode_or_404(db, episode_id, current_user)
    try:
        dismiss_screening_reminder(db, episode, current_user, reminder_key)
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(
        url=f"/visits/patients/{episode.patient_id}",
        status_code=303,
    )


@router.post("/visits/{visit_id}/procedures")
def create_procedure_route(
    visit_id: int,
    procedure_type: str = Form(...),
    details: str = Form(""),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Add a structured procedure record to a visit."""

    visit = _visit_or_404(db, visit_id, current_user)
    try:
        create_procedure_record(
            db,
            visit,
            current_user,
            _procedure_type(procedure_type),
            {"notes": details.strip()},
        )
        db.commit()
    except (PermissionError, ValueError) as error:
        db.rollback()
        _service_error(error)
    return RedirectResponse(url=f"/visits/{visit.id}", status_code=303)


@router.post("/visits/{visit_id}/next-action")
def visit_next_action(
    visit_id: int,
    action: str = Form(...),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Handle the post-save schedule-follow-up, done, or skip prompt."""

    visit = _visit_or_404(db, visit_id, current_user)
    if action == "schedule_follow_up":
        return RedirectResponse(
            url=f"/schedule?patient_id={visit.patient_id}",
            status_code=303,
        )
    if action not in {"mark_done", "skip"}:
        raise HTTPException(status_code=422, detail="Unknown next action.")
    return RedirectResponse(
        url=f"/visits/{visit.id}?next_action_done=1",
        status_code=303,
    )