"""The scheduler: every tick, evaluate the users whose cadence has come (spec §10).

A tick runs one indexed query for the users due, reads the batch's prices once, and
evaluates each user on a small pool. One user's failure is recorded and the tick goes on
(§10.5). After each operation its next run moves to the first slot after now, whatever
the outcome: a missed run is one evaluation, never several (§10.2).
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import core.database as db
from core.config import AppConfig
from core.db.settings import DueUser
from core.db.types import Trigger
from core.execution import (
    EvaluationBusy,
    EvaluationResult,
    EvaluationStatus,
    ExecutionContext,
    NotReady,
    invest,
)
from core.public_market import TickMarket
from core.rebalance import propose, rebalance_now
from core.schedule import INVEST, REBALANCE, next_run

logger = logging.getLogger("coinpilot.scheduler")

# What counts towards a failure streak. `PARTIAL` is Kraken refusing an order, not the
# system failing. `UNRESOLVED` is a wait while an order is merely not listed yet, but a
# failure when Kraken did not answer the lookup (`lookup_failed`, spec §9.2). An operation
# that raises counts too.
FAILURES = frozenset({EvaluationStatus.ERROR, EvaluationStatus.KRAKEN_UNAVAILABLE})


def _failed(result: EvaluationResult) -> bool:
    if result.status in FAILURES:
        return True
    return result.status is EvaluationStatus.UNRESOLVED and result.lookup_failed


class SchedulerContext(ExecutionContext, Protocol):
    config: AppConfig
    scheduler_lock: Callable[[], AbstractContextManager[bool]]


@dataclass(frozen=True)
class TickReport:
    # False: another process held the tick, and nothing was done.
    ran: bool
    users: int = 0
    # Retention ran on this tick.
    swept: bool = False


class _TickContext:
    """The application's context, with the tick's shared prices as its public side."""

    def __init__(self, base: SchedulerContext, market: TickMarket) -> None:
        self._base = base
        self._market = market

    def __getattr__(self, name: str):
        return getattr(self._base, name)

    def public_kraken(self) -> TickMarket:
        return self._market


class Scheduler:
    def __init__(self, context: SchedulerContext) -> None:
        self._context = context
        self._config = context.config.scheduler
        self._swept_on: date | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime) -> TickReport:
        """One pass: the users due at `now`, a batch at most, most overdue first."""
        with self._context.scheduler_lock() as taken:
            if not taken:
                return TickReport(ran=False)
            swept = self._sweep(now)
            with self._context.sessions() as session:
                due = db.due_users(session, now, self._config.batch)
                pairs = db.pairs_for(session, [user.user_id for user in due])
            if due:
                market = TickMarket(self._context.public_kraken())
                market.preload(pairs)
                self._each(_TickContext(self._context, market), due, now)
            return TickReport(ran=True, users=len(due), swept=swept)

    def _each(self, context: _TickContext, due: list[DueUser], now: datetime) -> None:
        if self._config.workers == 1:
            for user in due:
                self._guarded(context, user, now)
            return
        with ThreadPoolExecutor(self._config.workers, thread_name_prefix="coinpilot-evaluation") as pool:
            for user in due:
                pool.submit(self._guarded, context, user, now)

    def _guarded(self, context: _TickContext, user: DueUser, now: datetime) -> None:
        """One user's operations, the investment first. Nothing raised here reaches the tick."""
        try:
            if user.invest_due:
                self._operate(context, user.user_id, INVEST, now)
            if user.rebalance_due:
                self._operate(context, user.user_id, REBALANCE, now)
        except Exception:
            # The id only: never anything read for the user.
            logger.exception("user %s: the scheduler could not finish its evaluation", user.user_id)

    def _operate(self, context: _TickContext, user_id: uuid.UUID, prefix: str, now: datetime) -> None:
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
            if settings is None:
                return
            wanted = prefix == REBALANCE or settings.invest_cash_enabled
            automatic = settings.auto_rebalance_enabled
        if not wanted:
            # Switched off since it was scheduled: nothing to run, and no next run.
            self._advance(context, user_id, prefix, now)
            return
        try:
            result = self._run(context, user_id, prefix, automatic)
        except EvaluationBusy:
            # A request is evaluating this user. Not moved: the next tick tries again.
            logger.info("user %s: an evaluation is already running; the next tick tries again", user_id)
            return
        except NotReady:
            # No key or no fiat yet. Not a failure of the system's.
            self._advance(context, user_id, prefix, now)
            return
        except Exception:
            logger.exception("user %s: the scheduled %s failed", user_id, prefix)
            failed = True
        else:
            failed = _failed(result)
        self._advance(context, user_id, prefix, now)
        self._count(context, user_id, failed=failed)

    def _run(
        self, context: _TickContext, user_id: uuid.UUID, prefix: str, automatic: bool
    ) -> EvaluationResult:
        if prefix == INVEST:
            return invest(context, user_id, trigger=Trigger.SCHEDULER)
        if automatic:
            return rebalance_now(context, user_id)
        return propose(context, user_id, trigger=Trigger.SCHEDULER).evaluation

    def _advance(self, context: _TickContext, user_id: uuid.UUID, prefix: str, now: datetime) -> None:
        """Forward to the first slot after `now`: a missed run is not caught up (spec §10.2)."""
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
            if settings is None:
                # Deleted during the tick: nothing left to schedule.
                return
            db.update_settings(
                session, user_id, **{f"next_{prefix}_at": next_run(settings, prefix, now, self._config)}
            )

    def _count(self, context: _TickContext, user_id: uuid.UUID, *, failed: bool) -> None:
        """Edge-triggered (spec §10.5): one warning when the streak reaches the threshold,
        one note when a user past it recovers, never one per failure."""
        threshold = self._config.alert_streak
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
            if settings is None:
                return
            before = settings.failure_streak
            after = before + 1 if failed else 0
            if after != before:
                db.update_settings(session, user_id, failure_streak=after)
        if failed and after == threshold:
            logger.warning("user %s: %d scheduled operations in a row have failed", user_id, after)
        if not failed and before >= threshold:
            logger.info("user %s: scheduled operations recovered after %d failures", user_id, before)

    def _sweep(self, now: datetime) -> bool:
        """Retention, on the first tick of each UTC day, and so on the first after start-up."""
        today = now.astimezone(UTC).date()
        if self._swept_on == today:
            return False
        with self._context.sessions() as session:
            evaluations = db.delete_evaluations_before(session, now - self._config.sessions_retention)
            tokens = db.delete_expired_refresh_tokens(session, now)
        logger.info("retention removed %d evaluations and %d refresh tokens", evaluations, tokens)
        self._swept_on = today
        return True
