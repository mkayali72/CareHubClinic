"""FastAPI application entry point for the OB/GYN clinic scaffold."""

import asyncio
from contextlib import asynccontextmanager
import html
import logging

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response

from app.config import settings
from app.services.licensing import (
    LicenseWriteBlocked,
    _blocked_response,
    enforce_license_for_request,
    run_scheduled_license_check,
)
from app.services.csrf import CSRFViolation, csrf_error_response, enforce_csrf
from app.routes import (
    auth,
    billing,
    clinical,
    health,
    labs,
    pages,
    patients,
    prescriptions,
    reporting,
    scheduling,
    staff,
    licensing,
)

logger = logging.getLogger(__name__)


async def _license_scheduler() -> None:
    """Run local license check-ins in-process without another worker service."""

    while True:
        await asyncio.sleep(settings.license_check_interval_seconds)
        await asyncio.to_thread(run_scheduled_license_check)


@asynccontextmanager
async def app_lifespan(application: FastAPI):
    """Start and stop the in-process license check scheduler."""

    task = asyncio.create_task(_license_scheduler())
    application.state.license_scheduler_task = task
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A FastAPI instance with health, page, template, and static-file routes.

    Side effects:
        Registers routers and mounts the local static asset directory.
    """

    application = FastAPI(
        title=settings.app_name,
        description="Portable starter application for OB/GYN clinic operations.",
        version="0.1.0",
        lifespan=app_lifespan,
        debug=settings.app_env != "production",
        dependencies=[
            Depends(enforce_csrf),
            Depends(enforce_license_for_request),
        ],
    )
    application.add_exception_handler(
        CSRFViolation,
        lambda request, exc: csrf_error_response(request),
    )
    application.add_exception_handler(Exception, _unhandled_exception_response)
    application.add_exception_handler(
        LicenseWriteBlocked,
        lambda request, exc: _blocked_response(request, exc.snapshot),
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.app_env == "production",
    )
    application.mount("/static", StaticFiles(directory="app/static"), name="static")
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(pages.router)
    application.include_router(patients.router)
    application.include_router(scheduling.router)
    application.include_router(clinical.router)
    application.include_router(labs.router)
    application.include_router(prescriptions.router)
    application.include_router(reporting.router)
    application.include_router(billing.router)
    application.include_router(staff.router)
    application.include_router(licensing.router)
    return application


async def _unhandled_exception_response(
    request: Request,
    exc: Exception,
) -> Response:
    """Log only a generic event and avoid internal details in production."""

    logger.error("Unhandled application error")
    if settings.app_env != "production":
        detail = html.escape(str(exc)) or "Unhandled application error."
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc) or "Unhandled application error."},
            )
        return HTMLResponse(
            content=f"<!doctype html><title>Application error</title><p>{detail}</p>",
            status_code=500,
        )
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )
    return HTMLResponse(
        content=(
            "<!doctype html><title>Application error</title>"
            "<p>Something went wrong. Please try again later.</p>"
        ),
        status_code=500,
    )


app = create_app()