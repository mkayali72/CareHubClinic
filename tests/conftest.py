"""Shared pytest fixtures for isolated FastAPI foundation tests."""

from collections.abc import Callable, Generator, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import create_app
from app.models import Base, Clinic, User, UserRole
from app.services.auth import create_user
from app.services.csrf import enforce_csrf


@pytest.fixture()
def db_engine() -> Iterator[Engine]:
    """Create a fresh in-memory SQLite database for one test.

    Yields:
        An isolated SQLAlchemy engine whose schema is created before the test
        and dropped after it completes.
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Provide one ORM session backed by the isolated test database.

    Args:
        db_engine: Engine fixture for the current test.

    Yields:
        A SQLAlchemy Session that is closed after the test.
    """

    session_factory = sessionmaker(
        bind=db_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def override_database_dependency(
    db_session: Session,
) -> Generator[Session, None, None]:
    """Yield the test session when FastAPI asks for a database dependency.

    Args:
        db_session: Isolated session supplied by the fixture.

    Yields:
        The same isolated session for each request in the test.
    """

    yield db_session


def make_database_override(
    db_session: Session,
) -> Callable[[], Generator[Session, None, None]]:
    """Create a FastAPI dependency function for one isolated test session.

    Args:
        db_session: Isolated session supplied by the fixture.

    Returns:
        A generator dependency that yields the supplied session.
    """

    def override() -> Generator[Session, None, None]:
        """Yield the captured isolated session to FastAPI."""

        yield from override_database_dependency(db_session)

    return override


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """Create a TestClient whose database dependency never reaches PostgreSQL.

    Args:
        db_session: Isolated session supplied to all route dependencies.

    Yields:
        A FastAPI TestClient with the application database override installed.
    """

    application = create_app()
    application.dependency_overrides[get_db] = make_database_override(db_session)
    application.dependency_overrides[enforce_csrf] = lambda: None
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        application.dependency_overrides.clear()


@pytest.fixture()
def short_lived_client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Create a TestClient with a one-second signed session lifetime.

    Args:
        db_session: Isolated session supplied to route dependencies.
        monkeypatch: Pytest patch manager used to replace application settings.

    Yields:
        A TestClient configured for inactivity-expiry verification.
    """

    import app.main as main_module
    from dataclasses import replace

    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, session_max_age_seconds=1),
    )
    application = create_app()
    application.dependency_overrides[get_db] = make_database_override(db_session)
    application.dependency_overrides[enforce_csrf] = lambda: None
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        application.dependency_overrides.clear()


@pytest.fixture()
def seeded_users(db_session: Session) -> dict[UserRole, User]:
    """Create one clinic and one active user for every allowed role.

    Args:
        db_session: Isolated session used to persist the seed records.

    Returns:
        A mapping from every UserRole to its seeded User row.
    """

    clinic = Clinic(name="Test Clinic")
    db_session.add(clinic)
    db_session.flush()
    users: dict[UserRole, User] = {}
    for role in UserRole:
        users[role] = create_user(
            db=db_session,
            clinic_id=clinic.id,
            email=f"{role.value}@example.invalid",
            password="Valid-Test-Password1",
            full_name=f"Test {role.value}",
            role=role,
        )
    db_session.commit()
    return users