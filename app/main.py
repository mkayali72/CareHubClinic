"""FastAPI application entry point for the OB/GYN clinic scaffold."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.config import settings
from app.services.licensing import (
    LicenseWriteBlocked,
    _blocked_response,
    enforce_license_for_request,
    run_scheduled_license_check,
)
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
    licensing,
)


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
        dependencies=[Depends(enforce_license_for_request)],
    )
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
    application.include_router(licensing.router)
    return application


app = create_app()