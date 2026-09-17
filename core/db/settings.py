"""Per-user settings, the asset targets, and the one query the scheduler runs each tick."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.db.models import AssetConfig, UserSettings

# A sort key for a row that has one of the two times set and the other null. It is never
# compared against a real date, only used to push the null side out of the way.
_FAR_FUTURE = datetime(9999, 12, 31, tzinfo=UTC)

# `fiat` is deliberately absent: it is immutable for now, and leaving it out makes that a
# property of the code rather than a rule someone has to remember.
_UPDATABLE = frozenset(
    {
        "auto_rebalance_enabled",
        "cash_rebalance_enabled",
        "invest_cadence_anchor",
        "invest_cadence_mode",
        "invest_cash_enabled",
        "invest_interval_days",
        "invest_interval_months",
        "min_drift_pct",
        "min_order_fiat",
        "next_invest_at",
        "next_rebalance_at",
        "paused",
        "rebalance_cadence_anchor",
        "rebalance_cadence_mode",
        "rebalance_interval_days",
        "rebalance_interval_months",
    }
)


@dataclass(frozen=True)
class DueUser:
    """A user the scheduler must evaluate, and which of the two cadences called for it.

    Both flags matter: which one is due decides whether the plan may contain sells.
    """

    user_id: uuid.UUID
    invest_due: bool
    rebalance_due: bool


def create_settings(session: Session, user_id: uuid.UUID, fiat: str) -> UserSettings:
    """Every default lives in the model, so a new user needs one argument: their fiat."""
    settings = UserSettings(user_id=user_id, fiat=fiat)
    session.add(settings)
    session.flush()
    return settings


def get_settings(session: Session, user_id: uuid.UUID) -> UserSettings | None:
    return session.get(UserSettings, user_id)


def update_settings(session: Session, user_id: uuid.UUID, **fields: object) -> UserSettings | None:
    """Change the named settings.

    A name outside the allowed set raises. `setattr` on a typo would otherwise succeed
    silently and the setting would simply never take effect.
    """
    unknown = sorted(set(fields) - _UPDATABLE)
    if unknown:
        raise ValueError(f"these settings cannot be updated: {', '.join(unknown)}")
    settings = session.get(UserSettings, user_id)
    if settings is None:
        return None
    for name, value in fields.items():
        setattr(settings, name, value)
    session.flush()
    return settings


def due_users(session: Session, now: datetime, limit: int) -> list[DueUser]:
    """The users to evaluate on this tick, most overdue first.

    `limit` has no default on purpose. After an outage every user is overdue at once, and
    an unbounded batch turns the recovery into a stampede at the worst possible moment.
    """
    stmt = (
        select(
            UserSettings.user_id,
            UserSettings.next_invest_at,
            UserSettings.next_rebalance_at,
        )
        .where(
            UserSettings.paused.is_(False),
            or_(UserSettings.next_invest_at <= now, UserSettings.next_rebalance_at <= now),
        )
        .order_by(
            func.least(
                func.coalesce(UserSettings.next_invest_at, _FAR_FUTURE),
                func.coalesce(UserSettings.next_rebalance_at, _FAR_FUTURE),
            )
        )
        .limit(limit)
    )
    return [
        DueUser(
            user_id=row.user_id,
            invest_due=row.next_invest_at is not None and row.next_invest_at <= now,
            rebalance_due=row.next_rebalance_at is not None and row.next_rebalance_at <= now,
        )
        for row in session.execute(stmt)
    ]


def upsert_asset(
    session: Session,
    user_id: uuid.UUID,
    asset: str,
    pair: str,
    target_pct: Decimal,
) -> AssetConfig:
    row = session.get(AssetConfig, (user_id, asset))
    if row is None:
        row = AssetConfig(user_id=user_id, asset=asset)
        session.add(row)
    row.pair = pair
    row.target_pct = target_pct
    session.flush()
    return row


def list_assets(session: Session, user_id: uuid.UUID) -> list[AssetConfig]:
    """Ordered by asset code, so a response never changes shape between two reads."""
    stmt = select(AssetConfig).where(AssetConfig.user_id == user_id).order_by(AssetConfig.asset)
    return list(session.execute(stmt).scalars())


def delete_asset(session: Session, user_id: uuid.UUID, asset: str) -> bool:
    """True when a row was removed, false when there was none to remove."""
    row = session.get(AssetConfig, (user_id, asset))
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def targets_for(session: Session, user_id: uuid.UUID) -> dict[str, Decimal]:
    """The `targets` argument `engine.reconcile` takes.

    A row with a target of zero is kept. It says *exit this position*, which is a
    different statement from having no row at all.
    """
    return {row.asset: row.target_pct for row in list_assets(session, user_id)}
