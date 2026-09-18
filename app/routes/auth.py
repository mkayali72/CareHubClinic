"""Jinja2 and htmx routes for session-based staff authentication."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.services.auth import (
    authenticate_user,
    change_own_password,
    get_current_user,
    login_user,
    logout_user,
    require_authenticated_user,
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
        context={
            "page_title": "Sign in",
            "error": None,
            "message": (
                "Your password was changed. Sign in again with your new password."
                if request.query_params.get("password_changed") == "1"
                else None
            ),
        },
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    """Authenticate a staff user and establish a signed session.

    Args:
        request: Incoming form request.
        username: Submitted staff username.
        password: Submitted plaintext password, never persisted.
        db: Request-scoped SQLAlchemy session.

    Returns:
        An htmx redirect response or normal browser redirect on success. Invalid
        credentials render a safe error without revealing which field failed.
    """

    user = authenticate_user(db, username, password)
    if user is None:
        if request.headers.get("HX-Request") == "true":
            return templates.TemplateResponse(
                request=request,
                name="partials/login_feedback.html",
                context={"error": "Username or password is incorrect."},
                status_code=401,
            )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "page_title": "Sign in",
                "error": "Username or password is incorrect.",
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


@router.get("/account/password", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
) -> Response:
    """Render the authenticated user's password-change form."""

    return templates.TemplateResponse(
        request=request,
        name="auth/change_password.html",
        context={
            "app_name": settings.app_name,
            "page_title": "Change password",
            "user": current_user,
            "error": None,
        },
    )


@router.post("/account/password", response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    password_confirmation: str = Form(...),
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    """Change the authenticated user's password and end all existing sessions."""

    error: str | None = None
    try:
        if new_password != password_confirmation:
            raise ValueError("The password entries do not match.")
        change_own_password(
            db=db,
            user=current_user,
            current_password=current_password,
            new_password=new_password,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        error = str(exc)

    if error is not None:
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "app_name": settings.app_name,
                "page_title": "Change password",
                "user": current_user,
                "error": error,
            },
            status_code=422,
        )

    request.session.clear()
    return RedirectResponse(url="/login?password_changed=1", status_code=303)