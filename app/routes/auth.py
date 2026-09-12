"""Jinja2 and htmx routes for session-based staff authentication."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.database import get_db
from app.services.auth import (
    authenticate_user,
    get_current_user,
    login_user,
    logout_user,
)
from app.models import User
from app.templates import create_templates

router = APIRouter(tags=["authentication"])
templates = create_templates()


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
) -> Response:
    """Render the login form or redirect an existing session to /welcome.

    Args:
        request: Incoming browser request.
        current_user: Optional authenticated user from the session dependency.

    Returns:
        The login page for anonymous visitors or a redirect for signed-in users.
    """

    if current_user is not None:
        return RedirectResponse(url="/welcome", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"page_title": "Sign in", "error": None},
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    """Authenticate a staff user and establish a signed session.

    Args:
        request: Incoming form request.
        email: Submitted staff email.
        password: Submitted plaintext password, never persisted.
        db: Request-scoped SQLAlchemy session.

    Returns:
        An htmx redirect response or normal browser redirect on success. Invalid
        credentials render a safe error without revealing which field failed.
    """

    user = authenticate_user(db, email, password)
    if user is None:
        if request.headers.get("HX-Request") == "true":
            return templates.TemplateResponse(
                request=request,
                name="partials/login_feedback.html",
                context={"error": "Email or password is incorrect."},
                status_code=401,
            )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "page_title": "Sign in",
                "error": "Email or password is incorrect.",
            },
            status_code=401,
        )

    login_user(request, user)
    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = "/welcome"
        return response
    return RedirectResponse(url="/welcome", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    """End the current session and redirect to the login page.

    Args:
        request: Incoming request whose session should be cleared.
        db: Request-scoped SQLAlchemy session used to revoke the session.

    Returns:
        An htmx redirect response or normal browser redirect.
    """

    logout_user(request, db)
    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = "/login"
        return response
    return RedirectResponse(url="/login", status_code=303)