"""Keeping `next_invest_at` and `next_rebalance_at` true to the settings (spec §10.2).

The scheduler owns both columns. It moves them forward after every run; they move here
when a setting they come from changes, and on start-up for a row that has none.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session

import core.database as db
from core.cadence import Cadence, next_slot
from core.config import SchedulerConfig
from core.db.models import UserSettings
from core.db.types import CadenceMode

INVEST = "invest"
REBALANCE = "rebalance"

# The settings each next run is computed from. A change to any of them recomputes it.
# `paused` too: the tick skips a paused user, so their runs fall behind, and lifting the
# pause must wait for the next slot rather than run what was missed at once.
SOURCES = {
    INVEST: frozenset(
        {
            "paused",
            "invest_cash_enabled",
            "invest_cadence_mode",
            "invest_interval_days",
            "invest_interval_months",
            "invest_cadence_anchor",
        }
    ),
    REBALANCE: frozenset(
        {
            "paused",
            "rebalance_cadence_mode",
            "rebalance_interval_days",
            "rebalance_interval_months",
            "rebalance_cadence_anchor",
        }
    ),
}
EVERY_SOURCE = SOURCES[INVEST] | SOURCES[REBALANCE]


def next_run(settings: UserSettings, prefix: str, now: datetime, config: SchedulerConfig) -> datetime | None:
    """When the `prefix` operation is next due, strictly after `now`.

    `None` for an investment switched off: nothing is due, so the tick's query never
    selects it. A rebalance is always looked for; whether it acts is the drift's call.
    """
    if prefix == INVEST and not settings.invest_cash_enabled:
        return None
    cadence = Cadence(
        mode=CadenceMode(getattr(settings, f"{prefix}_cadence_mode")),
        interval_days=getattr(settings, f"{prefix}_interval_days"),
        interval_months=getattr(settings, f"{prefix}_interval_months"),
        anchor=getattr(settings, f"{prefix}_cadence_anchor"),
    )
    return next_slot(cadence, settings.user_id, now, min_interval=config.min_cadence, window=config.window)


def rescheduled(
    settings: UserSettings, changed: Iterable[str], now: datetime, config: SchedulerConfig
) -> dict[str, datetime | None]:
    """The next runs that a change to the `changed` settings moves, as `update_settings` takes them."""
    names = set(changed)
    return {
        f"next_{prefix}_at": next_run(settings, prefix, now, config)
        for prefix, sources in SOURCES.items()
        if sources & names
    }


def backfill(session: Session, now: datetime, config: SchedulerConfig) -> int:
    """Give every settings row the next runs it lacks. Returns how many rows changed."""
    rows = db.unscheduled_settings(session)
    for settings in rows:
        moves: dict[str, datetime | None] = {}
        if settings.next_rebalance_at is None:
            moves["next_rebalance_at"] = next_run(settings, REBALANCE, now, config)
        if settings.invest_cash_enabled and settings.next_invest_at is None:
            moves["next_invest_at"] = next_run(settings, INVEST, now, config)
        db.update_settings(session, settings.user_id, **moves)
    return len(rows)
