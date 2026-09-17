"""The value series and the record of every evaluation.

Neither can be reconstructed afterwards, which is why both are written from day one
rather than added once somebody asks a question they answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.db.models import EvaluationSession, PortfolioSnapshot

RUNNING = "RUNNING"


def record_snapshot(
    session: Session,
    user_id: uuid.UUID,
    as_of: datetime,
    fiat: str,
    total_value: Decimal,
    cash: Decimal,
    holdings: dict[str, object],
) -> PortfolioSnapshot:
    """One point in the series.

    `holdings` carries the unmanaged assets too, each flagged, so the user sees their real
    account rather than a partial view of it.
    """
    snapshot = PortfolioSnapshot(
        user_id=user_id,
        as_of=as_of,
        fiat=fiat,
        total_value=total_value,
        cash=cash,
        holdings=holdings,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def latest_snapshot(session: Session, user_id: uuid.UUID) -> PortfolioSnapshot | None:
    """What `GET /portfolio` returns immediately, with its own `as_of`."""
    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.as_of.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def snapshots_since(
    session: Session,
    user_id: uuid.UUID,
    since: datetime,
    limit: int = 1000,
) -> list[PortfolioSnapshot]:
    """The series from a start point, oldest first, because a chart reads left to right."""
    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id, PortfolioSnapshot.as_of >= since)
        .order_by(PortfolioSnapshot.as_of)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def start_evaluation(session: Session, user_id: uuid.UUID, started_at: datetime) -> EvaluationSession:
    """Open the record before the work, so a process that dies still leaves a trace."""
    record = EvaluationSession(user_id=user_id, started_at=started_at, status=RUNNING)
    session.add(record)
    session.flush()
    return record


def finish_evaluation(
    session: Session,
    evaluation_id: uuid.UUID,
    status: str,
    finished_at: datetime,
    log_messages: str | None = None,
) -> EvaluationSession | None:
    """Close the record and compute its duration.

    `status` is a plain string, not an enumeration. Telemetry gains values over time and
    the column deliberately carries no check constraint.
    """
    record = session.get(EvaluationSession, evaluation_id)
    if record is None:
        return None
    record.status = status
    record.finished_at = finished_at
    record.duration_ms = int((finished_at - record.started_at).total_seconds() * 1000)
    record.log_messages = log_messages
    session.flush()
    return record


def list_evaluations(session: Session, user_id: uuid.UUID, limit: int = 50) -> list[EvaluationSession]:
    stmt = (
        select(EvaluationSession)
        .where(EvaluationSession.user_id == user_id)
        .order_by(EvaluationSession.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def delete_evaluations_before(session: Session, cutoff: datetime) -> int:
    """Retention, across every user at once. Returns how many rows went.

    This is a system-wide sweep and takes no `user_id`, which is the one deliberate
    exception to the rule that every query is scoped to a tenant.
    """
    result = session.execute(delete(EvaluationSession).where(EvaluationSession.started_at < cutoff))
    session.flush()
    return result.rowcount
