"""Engine construction and the transaction boundary.

The URL arrives as an argument. `configure` sets the process-wide engine once, at
start-up, and everything else asks `get_engine` for it, so no other module reads the
environment on its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


# How long opening a connection may take, not how long a query may run. psycopg's own
# default is 130 s, and every request waited that long on a database that was down.
CONNECT_TIMEOUT_SECONDS = 5


def create_engine_from_url(url: str) -> Engine:
    """Build an engine.

    `pool_pre_ping` costs one round trip and survives a dropped connection, which a
    long-lived scheduler process will meet. `hide_parameters` keeps bound values out of
    an error's text: they are balances and order amounts read with a user's key, and an
    error's text reaches the log.
    """
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        future=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


def configure(url: str) -> None:
    """Set the process-wide engine. Called once, at application start-up."""
    global _engine, _factory
    _engine = create_engine_from_url(url)
    _factory = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("the database engine is not configured")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work. Commits on success, rolls back on any exception."""
    if _factory is None:
        raise RuntimeError("the database engine is not configured")
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
