"""Shared template configuration for security context."""

from fastapi.templating import Jinja2Templates

from app.services.csrf import get_csrf_token


def create_templates() -> Jinja2Templates:
    """Create a template environment with a request-bound CSRF token."""

    return Jinja2Templates(
        directory="app/templates",
        context_processors=[lambda request: {"csrf_token": get_csrf_token(request)}],
    )