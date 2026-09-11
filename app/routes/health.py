"""Health-check endpoints for the application and its database dependency."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.database import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> JSONResponse:
    """Check that the app is running and PostgreSQL accepts a simple query.

    Returns:
        A JSON response with status 200 when SELECT 1 succeeds, or status 503
        with a degraded status when the database cannot be reached.

    Side effects:
        Opens a database connection and executes SELECT 1.
    """

    try:
        database_ok = check_database_connection()
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable"},
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "database": "ok" if database_ok else "unavailable"},
    )