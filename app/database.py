"""PostgreSQL engine and connection helpers.

This module creates only the SQLAlchemy engine. No table metadata or model
imports are registered yet because schema design is deliberately deferred.
"""

from collections.abc import Generator

from sqlalchemy import Connection, Engine, create_engine, text

from app.config import settings


engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)


def get_connection() -> Generator[Connection, None, None]:
    """Yield a SQLAlchemy connection for future request-scoped database work.

    Yields:
        An open SQLAlchemy Connection that is closed after the caller finishes.

    Side effects:
        Opens and closes one connection from the configured PostgreSQL pool.
    """

    with engine.connect() as connection:
        yield connection


def check_database_connection() -> bool:
    """Run a minimal PostgreSQL connectivity probe.

    Returns:
        True when PostgreSQL responds successfully to SELECT 1.

    Raises:
        Exception: The original SQLAlchemy or driver exception when the probe
            cannot connect. The health router converts it into a safe response.
    """

    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1