"""Server-rendered page routes for the initial application shell."""

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.models import User, UserRole
from app.services.auth import get_current_user, require_authenticated_user
from app.services.scheduling import get_appointments_for_date
from app.templates import create_templates
from sqlalchemy.orm import Session
from datetime import date

router = APIRouter(tags=["pages"])
templates = create_templates()


@router.get("/")
def dashboard(
    request: Request,
    current_user: User | None = Depends(get_current_user),
) -> Response:
    """Route the root URL to login or the authenticated landing page.

    Args:
        request: Incoming request used by Starlette's template renderer.

    Returns:
        A redirect to /login for anonymous visitors or /welcome for users with
        a valid session.
    """

    return RedirectResponse(
        url="/welcome" if current_user is not None else "/login",
        status_code=303,
    )


@router.get("/welcome")
def welcome(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    """Render the minimal authenticated landing page.

    Args:
        request: Incoming browser request.
        current_user: Authenticated staff user required by the dependency.

    Returns:
        A Jinja2 response showing the user's name and role.
    """

    physician_queue = (
        get_appointments_for_date(
            db,
            current_user,
            date.today(),
            doctor_id=current_user.id,
        )
        if current_user.role is UserRole.PHYSICIAN
        else []
    )
    return templates.TemplateResponse(
        request=request,
        name="welcome.html",
        context={
            "app_name": settings.app_name,
            "page_title": "Welcome",
            "user": current_user,
            "physician_queue": physician_queue,
            "today": date.today(),
        },
    )