"""Server-rendered page routes for the initial application shell."""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    """Render the empty clinic dashboard shell.

    Args:
        request: Incoming request used by Starlette's template renderer.

    Returns:
        A Jinja2 TemplateResponse containing the sidebar layout and placeholder
        dashboard content.
    """

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "page_title": "Overview",
        },
    )