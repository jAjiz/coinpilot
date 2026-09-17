"""Fixtures for the tests that need a real PostgreSQL.

Every one of them is skipped unless RUN_DB_INTEGRATION is true, so a developer with no
database still runs the unit suite.

Reading DATABASE_URL here is deliberate, and it is not what the global rule forbids: it
says where the test runs, not what the code under test is given.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from core.db.session import create_engine_from_url

_ROOT = Path(__file__).resolve().parents[2]


def _migrate(url: str) -> None:
    """Bring the test database to head.

    Running the real migrations rather than `create_all` means every test run also proves
    the migrations still apply.
    """
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "scripts" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _enabled() -> bool:
    return os.environ.get("RUN_DB_INTEGRATION", "").lower() == "true"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    if not _enabled():
        pytest.skip("RUN_DB_INTEGRATION is not true")
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    built = create_engine_from_url(url)
    _migrate(url)
    yield built
    built.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back.

    No test cleans up after itself, and no test can leak a row into the next one.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
