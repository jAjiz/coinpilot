"""One evaluation per user at a time (spec §9.6).

A PostgreSQL advisory lock, held on a connection of its own for the length of an
evaluation. It is a session lock, not a transaction one, because the executor commits
many short transactions while it holds it. If the process dies, the connection closes and
the lock goes with it, so a crash never leaves a user locked out.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text


def lock_key(user_id: uuid.UUID) -> int:
    """The user id as the signed 64-bit key an advisory lock takes.

    Two users whose random ids share their first 64 bits would only wait on each other;
    neither would see the other's data.
    """
    return int.from_bytes(user_id.bytes[:8], "big", signed=True)


@contextmanager
def advisory_user_lock(engine: Engine, user_id: uuid.UUID) -> Iterator[bool]:
    """Yields whether the lock was taken. It never waits: a second evaluation is refused,
    not queued behind the first."""
    key = lock_key(user_id)
    with engine.connect() as connection:
        taken = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one())
        connection.commit()
        try:
            yield taken
        finally:
            if taken:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()
