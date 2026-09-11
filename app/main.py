"""FastAPI application entry point for the OB/GYN clinic scaffold."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes import health, pages


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
    application.mount("/static", StaticFiles(directory="app/static"), name="static")
    application.include_router(health.router)
    application.include_router(pages.router)
    return application


app = create_app()