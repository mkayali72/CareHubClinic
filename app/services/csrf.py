"""Session-bound CSRF protection for browser form and HTMX writes."""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FORM_FIELD = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_csrf_token(request: Request) -> str:
    """Return the current session token, creating one for a new browser session."""

    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


class CSRFViolation(Exception):
    """Raised when a state-changing request lacks the session-bound token."""

    def __init__(self, request: Request) -> None:
        self.request = request
        super().__init__("CSRF validation failed.")


async def enforce_csrf(request: Request) -> None:
    """Require a matching form field or header on every state-changing request."""

    if request.method not in CSRF_WRITE_METHODS:
        return
    expected = request.session.get(CSRF_SESSION_KEY)
    submitted = request.headers.get(CSRF_HEADER)
    if not submitted:
        content_type = request.headers.get("content-type", "").lower()
        if content_type.startswith(
            ("application/x-www-form-urlencoded", "multipart/form-data")
        ):
            form = await request.form()
            submitted = form.get(CSRF_FORM_FIELD)
    if (
        not isinstance(expected, str)
        or not isinstance(submitted, str)
        or not hmac.compare_digest(expected, submitted)
    ):
        raise CSRFViolation(request)


def csrf_error_response(request: Request) -> Response:
    """Return a browser/HTMX-safe CSRF error without exposing internals."""

    message = "This form expired. Refresh the page and try again."
    if request.headers.get("HX-Request") == "true":
        return Response(
            content=message,
            status_code=403,
            media_type="text/plain",
            headers={"HX-Reswap": "none"},
        )
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(status_code=403, content={"detail": message})
    return HTMLResponse(
        content=(
            "<!doctype html><title>Request expired</title>"
            '<main style="font-family:system-ui;max-width:42rem;margin:4rem auto;'
            'padding:1.5rem;border:1px solid #cbd5e1;border-radius:1rem">'
            "<h1>Request expired</h1>"
            f"<p>{message}</p>"
            "<p>Refresh the page and submit the form again.</p>"
            "</main>"
        ),
        status_code=403,
    )