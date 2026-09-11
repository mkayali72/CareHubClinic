"""PostgreSQL engine, ORM session, and default soft-delete query helpers."""

from collections.abc import Generator

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import (
    ORMExecuteState,
    Session,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.models.base import SoftDeleteMixin


engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def not_deleted_criteria(entity: type[SoftDeleteMixin]) -> ColumnElement[bool]:
    """Build the default predicate that excludes soft-deleted records.

    Args:
        entity: A mapped class inheriting from SoftDeleteMixin.

    Returns:
        A SQLAlchemy boolean expression matching records whose deleted_at value
        is NULL.
    """

    return entity.deleted_at.is_(None)


@event.listens_for(Session, "do_orm_execute")
def add_soft_delete_filter(execute_state: ORMExecuteState) -> None:
    """Apply the reusable soft-delete filter to ORM SELECT statements.

    Args:
        execute_state: SQLAlchemy execution state for the ORM statement.

    Side effects:
        Rewrites SELECT statements to exclude SoftDeleteMixin rows where
        deleted_at is populated, unless include_deleted=True is explicitly
        provided through statement execution options.
    """

    if (
        execute_state.is_select
        and not execute_state.is_column_load
        and not execute_state.is_relationship_load
        and not execute_state.execution_options.get("include_deleted", False)
    ):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                SoftDeleteMixin,
                not_deleted_criteria,
                include_aliases=True,
            )
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


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped SQLAlchemy ORM session.

    Yields:
        A Session that commits only when the caller explicitly commits and is
        always closed after the request.

    Side effects:
        Opens and closes one ORM session backed by the configured PostgreSQL
        connection pool.
    """

    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


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