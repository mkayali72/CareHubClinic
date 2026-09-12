"""Environment-backed application configuration.

The module intentionally reads ordinary environment variables so the same
application configuration works in Replit, Docker Compose, and a local shell.
"""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Store runtime configuration for the FastAPI application.

    Attributes:
        app_name: Human-readable name used by the page shell and FastAPI metadata.
        app_env: Runtime environment label such as development or production.
        database_url: SQLAlchemy connection URL for PostgreSQL.
        host: Network interface used by the development server.
        port: Network port used by the development server.
    """

    app_name: str
    app_env: str
    database_url: str
    host: str
    port: int
    session_secret: str
    session_max_age_seconds: int
    session_inactivity_seconds: int
    login_max_failed_attempts: int
    login_lockout_seconds: int
    license_check_interval_seconds: int


def normalize_database_url(database_url: str) -> str:
    """Normalize common PostgreSQL URL aliases for the psycopg 3 driver.

    Args:
        database_url: A standard PostgreSQL URL from an environment variable or
            a driver-explicit SQLAlchemy URL.

    Returns:
        A SQLAlchemy URL that explicitly selects the installed psycopg driver.

    Assumptions:
        The application intentionally uses psycopg 3 rather than the legacy
        psycopg2 package, so generic PostgreSQL URLs need an explicit driver.
    """

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def get_settings() -> Settings:
    """Build application settings from standard environment variables.

    Returns:
        A validated immutable Settings instance.

    Raises:
        ValueError: If PORT is present but is not a positive integer.
    """

    raw_port = os.getenv("PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be a positive integer.") from exc
    if port <= 0:
        raise ValueError("PORT must be a positive integer.")

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://clinic:clinic@localhost:5432/obgyn",
    )

    def positive_int(name: str, default: str) -> int:
        """Read a positive integer setting from the environment."""

        raw_value = os.getenv(name, default)
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a positive integer.") from exc
        if value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
        return value

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    return Settings(
        app_name=os.getenv("APP_NAME", "OB/GYN Clinic"),
        app_env=app_env,
        database_url=normalize_database_url(database_url),
        host=os.getenv("HOST", "0.0.0.0"),
        port=port,
        session_secret=os.getenv(
            "SESSION_SECRET",
            "development-only-change-this-session-secret",
        ),
        session_max_age_seconds=positive_int("SESSION_MAX_AGE_SECONDS", "1209600"),
        session_inactivity_seconds=positive_int(
            "SESSION_INACTIVITY_SECONDS",
            "1800",
        ),
        login_max_failed_attempts=positive_int("LOGIN_MAX_FAILED_ATTEMPTS", "5"),
        login_lockout_seconds=positive_int("LOGIN_LOCKOUT_SECONDS", "900"),
        license_check_interval_seconds=positive_int(
            "LICENSE_CHECK_INTERVAL_SECONDS",
            "300",
        ),
    )


settings = get_settings()