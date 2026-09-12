"""FastAPI application entry point for the OB/GYN clinic scaffold."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
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
)


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
    return application


app = create_app()