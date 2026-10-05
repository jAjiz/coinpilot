# Phase 7 — The scheduler

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The platform runs on its own. Every minute a tick evaluates the users whose
cadence has come: it invests their free cash, and it proposes a rebalance, or, with
automatic rebalancing on, executes one. Every evaluation is recorded with what it was for
and who started it, so the session history can be read and trusted.

**Architecture:** `core/cadence.py` is pure: it computes a user's next slot from a
cadence, the user's id and the time. `core/schedule.py` keeps `next_invest_at` and
`next_rebalance_at` true to the settings. `core/public_market.py` is the public side of
Kraken as an evaluation reads it: names and pairs from the daily catalog, and, for a
tick, the prices of the whole batch in one call. `core/scheduler.py` holds the tick and
the thread that runs it: one tick at a time across processes, a bounded batch, a small
pool, one user's failure never stopping the next, and an edge-triggered failure streak.
The FastAPI lifespan starts and stops it.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, PostgreSQL, httpx. No new
dependency.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.4, §3.5, §4.1, §6, §8, §10, §14

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 7 of 8

## Global Constraints

- **Python 3.13.** One version, not a range.
- **Money is `Decimal`, never `float`.**
- **Pin every dependency with `==`.** This phase adds none. APScheduler is not added.
- **No test reads configuration from the environment.** `load_config` takes a mapping, and
  every test hands it a plain dict.
- **No test touches the network, and no test places a real order.** Kraken is answered by
  `httpx.MockTransport`.
- **No test starts a thread that ticks on a clock.** A test calls `Scheduler.tick(now)`
  with a fixed `now`. The one test that starts the thread holds the tick lock, so the
  thread does nothing.
- **Integration tests share the development database**, inside a transaction that is
  rolled back. Their clock (`FIXED_NOW`, 2026-09-29) is earlier than any real row's
  `next_*_at`, so a real user is never due in a test. No test asserts a count across
  every user.
- **No log line contains a credential** or anything read with one. A scheduler log line
  names the user by id, and nothing else about them.
- **Only `core/execution.py` places an order.** `tests/unit/core/test_layering.py`
  already fails if `add_order` appears anywhere else under `api/` or `core/`.
- **A rebalance executes without an approval only with `auto_rebalance_enabled` on**, and
  only from the scheduler.
- **Coverage gate is 80 %**, enforced by the CI command.
- **`ruff check` and `ruff format --check` must pass.** Lines are 110 characters. Some
  code blocks below run longer; run `ruff format` on every file before its commit.
- Commit messages follow Conventional Commits, and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Test command, used by every task (PostgreSQL from `docker-compose.dev.yml` running):

```bash
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests
```

## Review Focus

Each of these, if wrong, spends or sells something nobody asked for, or silently stops
the service. Each has a test in the task that owns it.

1. **The scheduler sells only with automatic rebalancing on.** With it off, a due
   rebalance is proposed and nothing is sent. → Task 7.
2. **The scheduler invests only with `invest_cash_enabled` on.** An investment switched
   off since it was scheduled is not run. → Tasks 6 and 7.
3. **A missed run is one evaluation, never several.** After each operation its next run
   moves to the first slot after now, whatever the outcome. → Tasks 2 and 7.
4. **One user's failure never stops the tick.** The next user is evaluated regardless. →
   Task 7.
5. **One tick at a time, across processes.** A second process that finds the tick taken
   does nothing. → Task 7.
6. **A busy user is not skipped until the next slot.** An evaluation already running for
   the user leaves the schedule as it is, and the next tick tries again. → Task 7.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/migrations/versions/c7a4e2d91f3b_scheduler_columns.py` | `user_settings.failure_streak`, `portfolio_snapshots.pinned`, `sessions.operation`, `sessions.trigger` |
| `core/db/types.py` | `Operation`, `Trigger` |
| `core/db/models.py` | The four new columns |
| `core/db/telemetry.py` | `keep_snapshot`, `pin_snapshot`; `start_evaluation` records operation and trigger |
| `core/db/settings.py` | `failure_streak` is updatable; `pairs_for`; `unscheduled_settings` |
| `core/database.py` | Exports the new DAL functions |
| `core/cadence.py` | Pure: `Cadence`, `offset_seconds`, `next_slot` |
| `core/config.py` | `SchedulerConfig`, read from the environment |
| `core/public_market.py` | `Market` (catalog names and pairs, live prices) and `TickMarket` (one tick's prices) |
| `core/catalog.py` | Docstring: names and pairs are now read from here by evaluations too |
| `core/execution.py` | Evaluations record operation and trigger; the snapshot is kept per day and pinned before the first order |
| `core/rebalance.py` | `propose` takes a trigger; `rebalance_now` executes without an approval |
| `core/schedule.py` | `next_run`, `rescheduled`, `backfill` |
| `core/scheduler.py` | `Scheduler`: `tick`, `start`, `stop`, `run`; `TickReport` |
| `core/db/locks.py` | `advisory_scheduler_lock` |
| `api/context.py` | `public_kraken()` returns a `Market`; `scheduler_lock` |
| `api/app.py` | The lifespan starts and stops the scheduler |
| `api/main.py` | Wires the scheduler lock, and logs `coinpilot.*` to stderr |
| `api/routes/config.py` | A change to a cadence or to `invest_cash_enabled` moves its next run |
| `api/routes/portfolio.py` | A refresh keeps the day's snapshot |
| `api/schemas.py` | `EvaluationOut.operation`, `EvaluationOut.trigger` |
| `.env.example` | The scheduler's variables |
| `tests/integration/conftest.py` | `FakeSchedulerLock`; `AppContext.scheduler_lock` |

---

## Decisions taken in this plan

The spec settles what to build. These settle how, where the spec leaves room or where
the user chose to depart from it while this plan was written.

- **Both cadences due: two evaluations, the investment first.** The spec asked for one
  balance read. The rebalance then planned on a balance the investment had already
  changed. Two evaluations each read what is true; the extra read costs nothing that
  matters. Spec §3.5 is updated.
- **A thread, not APScheduler.** One job every 60 seconds: a loop around `Event.wait`.
  The tick is a plain method a test calls with a fixed clock. Spec §4.1 and §14 are
  updated.
- **A pool of 4, run inline with 1.** `SCHEDULER_WORKERS` sizes a `ThreadPoolExecutor`.
  With 1 the batch runs in the tick's own thread, which is what the tests use: their
  database session is not thread-safe.
- **One tick at a time across processes.** The tick holds a PostgreSQL advisory lock
  keyed by two 32-bit integers, a key space PostgreSQL keeps apart from the 64-bit keys
  the user locks take.
- **One `Ticker` call per tick.** Every public call in the process shares one bucket at a
  call a second, so the pool cannot run public calls in parallel. A tick reads the prices
  of every pair its batch is configured with in one call, and a pair it missed once more.
  Names and pairs come from the daily catalog, for requests too.
- **Who decides.** With `auto_rebalance_enabled` on, a due rebalance executes and a live
  proposal is withdrawn first: what executes is today's plan, and leaving the proposal
  live would offer an approval of something already done. With it off, a due rebalance is
  proposed, with trigger `SCHEDULED`.
- **When a run moves forward.** After each operation, whatever its outcome, its
  `next_*_at` becomes the first slot after the tick's `now`. A user with no key or no fiat
  (`NotReady`) moves forward too. A user being evaluated already (`EvaluationBusy`) does
  not: the next tick tries again.
- **`next_invest_at` is null while `invest_cash_enabled` is off.** Nothing is due, so the
  tick's query never selects the user. `next_rebalance_at` is set whenever there are
  settings. Both are computed when the settings are created, when a setting they come from
  changes, and on start-up for any row that lacks them.
- **Cadence arithmetic.** The offset is `crc32(user_id.bytes)`, the same for both
  cadences. `MIN` falls at `epoch + k × min_cadence + offset mod min_cadence`. `INTERVAL`
  falls at `anchor + k × months + k × days + offset mod window`; months are calendar months
  counted from the anchor, never chained, so an anchor on the 31st falls on the 30th or
  the 28th and returns to the 31st.
- **The anchor is an instant in UTC.** A user who means 09:00 where clocks change runs an
  hour apart in summer and winter. Accepted: the window already spreads a run over an
  hour. A time zone per user is left out.
- **The failure streak.** `user_settings.failure_streak` counts scheduled operations that
  ended `ERROR` or `KRAKEN_UNAVAILABLE`, or raised. Any other outcome resets it;
  `NotReady` and `EvaluationBusy` do not touch it. One `WARNING` when it reaches
  `SCHEDULER_ALERT_STREAK`, one `INFO` when a user past it recovers. A log line is the
  alert until project 2 brings notifications.
- **Snapshots: one a day, plus one per operation.** An evaluation or a refresh overwrites
  the latest snapshot if it is unpinned and of the same UTC day, and adds one otherwise.
  The snapshot of an evaluation is pinned just before its first order is sent, and a
  pinned snapshot is never overwritten. `GET /portfolio` still shows the last read.
- **Sessions say what they were.** `operation` is `INVEST`, `PROPOSE`, `APPROVE` or
  `REBALANCE`; `trigger` is `API` or `SCHEDULER`. No check constraint, like `status`.
  Null on rows written before this phase.
- **Retention.** On the first tick of each UTC day, and so on the first tick after
  start-up: evaluations older than `SESSIONS_RETENTION_DAYS` and expired refresh tokens
  are deleted. Snapshots are not: the series cannot be rebuilt, and the daily overwrite
  already bounds it.

## What this phase deliberately leaves out

- **A notification channel.** The alert is a log line.
- **A time zone per user**, and so exact local times across a change of clocks.
- **`interval_hours`.** `MIN` is the system's 15 minutes; `INTERVAL` is a day or more.
- **Deployment**, and the log shipping that would turn the warning into a message —
  phase 8.

---

### Task 1: The columns, and what the DAL does with them

**Files:**
- Create: `scripts/migrations/versions/c7a4e2d91f3b_scheduler_columns.py`
- Modify: `core/db/types.py`, `core/db/models.py`, `core/db/telemetry.py`, `core/db/settings.py`, `core/database.py`, `api/schemas.py`
- Test: `tests/integration/test_telemetry.py`, `tests/integration/test_settings.py`, `tests/integration/test_schema.py`

**Interfaces:**
- Produces:
  - `core.db.types.Operation` (`INVEST`, `PROPOSE`, `APPROVE`, `REBALANCE`) and `Trigger` (`API`, `SCHEDULER`), both `StrEnum`.
  - `UserSettings.failure_streak: int`, `PortfolioSnapshot.pinned: bool`, `EvaluationSession.operation: str | None`, `EvaluationSession.trigger: str | None`.
  - `db.keep_snapshot(session, user_id, as_of, fiat, total_value, cash, holdings) -> PortfolioSnapshot`
  - `db.pin_snapshot(session, user_id, snapshot_id) -> None`
  - `db.record_snapshot(..., pinned: bool = False)`
  - `db.start_evaluation(session, user_id, started_at, *, operation: str | None = None, trigger: str | None = None)`
  - `db.update_settings(..., failure_streak=...)` is accepted.
  - `EvaluationOut.operation`, `EvaluationOut.trigger`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_telemetry.py` (add `keep_snapshot`, `pin_snapshot` to
the existing `from core.db.telemetry import (...)`, and the imports below):

```python
from core.db.types import Operation, Trigger

DAY = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def _keep(session: Session, user_id, as_of: datetime, total: str = "100"):
    return keep_snapshot(
        session, user_id, as_of=as_of, fiat="EUR", total_value=D(total), cash=D("10"), holdings={}
    )


def _series(session: Session, user_id):
    return snapshots_since(session, user_id, DAY - timedelta(days=1))


def test_a_second_read_of_the_same_day_overwrites_the_days_point(db_session: Session, make_user):
    """A reader every 15 minutes would otherwise write 96 near-identical rows a day."""
    user = make_user()
    first = _keep(db_session, user.id, DAY, "100")

    second = _keep(db_session, user.id, DAY + timedelta(hours=6), "110")

    assert second.id == first.id
    assert len(_series(db_session, user.id)) == 1
    assert (second.as_of, second.total_value) == (DAY + timedelta(hours=6), D("110"))


def test_a_read_on_a_new_day_adds_a_point(db_session: Session, make_user):
    user = make_user()
    _keep(db_session, user.id, DAY)

    _keep(db_session, user.id, DAY + timedelta(days=1))

    assert len(_series(db_session, user.id)) == 2


def test_a_pinned_snapshot_is_never_overwritten(db_session: Session, make_user):
    user = make_user()
    pinned = _keep(db_session, user.id, DAY, "100")
    pin_snapshot(db_session, user.id, pinned.id)

    later = _keep(db_session, user.id, DAY + timedelta(hours=1), "120")
    again = _keep(db_session, user.id, DAY + timedelta(hours=2), "130")

    assert later.id != pinned.id
    assert again.id == later.id
    assert pinned.total_value == D("100")
    assert [snapshot.pinned for snapshot in _series(db_session, user.id)] == [True, False]


def test_a_snapshot_cannot_be_pinned_by_another_user(db_session: Session, make_user):
    alice, bob = make_user("alice@example.test"), make_user("bob@example.test")
    snapshot = _keep(db_session, alice.id, DAY)

    pin_snapshot(db_session, bob.id, snapshot.id)

    assert snapshot.pinned is False


def test_an_evaluation_records_what_it_was_for_and_who_started_it(db_session: Session, make_user):
    record = start_evaluation(
        db_session, make_user().id, started_at=NOW, operation=Operation.INVEST, trigger=Trigger.SCHEDULER
    )

    assert (record.operation, record.trigger) == ("INVEST", "SCHEDULER")
```

Append to `tests/integration/test_settings.py`:

```python
def test_the_failure_streak_starts_at_zero_and_can_be_set(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    assert get_settings(db_session, user.id).failure_streak == 0
    update_settings(db_session, user.id, failure_streak=2)
    assert get_settings(db_session, user.id).failure_streak == 2
```

Append to `tests/integration/test_schema.py`:

```python
def test_the_scheduler_columns_exist(db_session: Session):
    inspector = inspect(db_session.get_bind())

    def columns(table):
        return {column["name"] for column in inspector.get_columns(table)}

    assert "failure_streak" in columns("user_settings")
    assert "pinned" in columns("portfolio_snapshots")
    assert {"operation", "trigger"} <= columns("sessions")
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command with `tests/integration/test_telemetry.py tests/integration/test_settings.py tests/integration/test_schema.py`
Expected: FAIL — `ImportError` for `keep_snapshot` and `Operation`.

- [ ] **Step 3: The types**

Append to `core/db/types.py`, after `ProposalTrigger`:

```python
class Operation(StrEnum):
    """What an evaluation was for. Recorded in `sessions`, which carries no check constraint."""

    INVEST = "INVEST"
    PROPOSE = "PROPOSE"
    APPROVE = "APPROVE"
    REBALANCE = "REBALANCE"


class Trigger(StrEnum):
    """Who started an evaluation: a request, or the scheduler."""

    API = "API"
    SCHEDULER = "SCHEDULER"
```

- [ ] **Step 4: The models**

In `core/db/models.py`, in `UserSettings`, after `paused`:

```python
    # Scheduled operations that failed in a row. The alert fires on its edges (spec §10.5).
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
```

Replace `PortfolioSnapshot`'s docstring and add a column after `holdings`:

```python
class PortfolioSnapshot(Base):
    """A point in the value series.

    One a day, overwritten by each read of that day, and one kept before every operation
    that sent orders. Reading every 15 minutes would otherwise write 96 near-identical
    rows a day, and the series cannot be thinned afterwards without losing which rows
    mattered.
    """
```

```python
    # Taken before orders were sent: kept as it is. An unpinned point is the day's, and
    # the next read of the same day overwrites it.
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
```

In `EvaluationSession`, after `status`:

```python
    # What it was for and who started it: `Operation` and `Trigger`. No check constraint,
    # like `status`. Null on rows written before the scheduler.
    operation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

- [ ] **Step 5: The migration**

Create `scripts/migrations/versions/c7a4e2d91f3b_scheduler_columns.py`:

```python
"""scheduler columns

Revision ID: c7a4e2d91f3b
Revises: 8b8c04912293
Create Date: 2026-10-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a4e2d91f3b"
down_revision: str | Sequence[str] | None = "8b8c04912293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_settings",
        sa.Column("failure_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("sessions", sa.Column("operation", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("trigger", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "trigger")
    op.drop_column("sessions", "operation")
    op.drop_column("portfolio_snapshots", "pinned")
    op.drop_column("user_settings", "failure_streak")
```

- [ ] **Step 6: The DAL**

In `core/db/telemetry.py`, add `from datetime import UTC, date, datetime` (replacing the
`datetime` import). Give `record_snapshot` a `pinned: bool = False` parameter, passed to
`PortfolioSnapshot(..., pinned=pinned)`. After `record_snapshot`, add:

```python
def keep_snapshot(
    session: Session,
    user_id: uuid.UUID,
    as_of: datetime,
    fiat: str,
    total_value: Decimal,
    cash: Decimal,
    holdings: dict[str, object],
) -> PortfolioSnapshot:
    """The day's point: overwrite the latest snapshot if it is unpinned and of the same UTC
    day as `as_of`, and add one otherwise.

    One point a day is the resolution a performance chart needs, and the latest read is
    still what `GET /portfolio` shows.
    """
    latest = latest_snapshot(session, user_id)
    if latest is not None and not latest.pinned and _day(latest.as_of) == _day(as_of):
        latest.as_of = as_of
        latest.fiat = fiat
        latest.total_value = total_value
        latest.cash = cash
        latest.holdings = holdings
        session.flush()
        return latest
    return record_snapshot(session, user_id, as_of, fiat, total_value, cash, holdings)


def pin_snapshot(session: Session, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
    """Keep a snapshot as it is: orders are about to be sent from the account it shows."""
    snapshot = session.get(PortfolioSnapshot, snapshot_id)
    if snapshot is not None and snapshot.user_id == user_id:
        snapshot.pinned = True
        session.flush()


def _day(moment: datetime) -> date:
    return moment.astimezone(UTC).date()
```

Replace `start_evaluation` with:

```python
def start_evaluation(
    session: Session,
    user_id: uuid.UUID,
    started_at: datetime,
    *,
    operation: str | None = None,
    trigger: str | None = None,
) -> EvaluationSession:
    """Open the record before the work, so a process that dies still leaves a trace."""
    record = EvaluationSession(
        user_id=user_id, started_at=started_at, status=RUNNING, operation=operation, trigger=trigger
    )
    session.add(record)
    session.flush()
    return record
```

In `core/db/settings.py`, add `"failure_streak",` to `_UPDATABLE` (keep it sorted).

In `core/database.py`, add `keep_snapshot` and `pin_snapshot` to the import from
`core.db.telemetry` and to `__all__`.

In `api/schemas.py`, in `EvaluationOut`, after `status: str`:

```python
    operation: str | None
    trigger: str | None
```

- [ ] **Step 7: Run the tests**

Run: the test command.
Expected: PASS, every test.

- [ ] **Step 8: Commit**

```bash
git add scripts/migrations/versions/c7a4e2d91f3b_scheduler_columns.py core/db/types.py core/db/models.py core/db/telemetry.py core/db/settings.py core/database.py api/schemas.py tests/integration/test_telemetry.py tests/integration/test_settings.py tests/integration/test_schema.py
git commit -m "feat(db): a failure streak, a pinned snapshot, and what each evaluation was for"
```

---

### Task 2: When a cadence is next due

**Files:**
- Create: `core/cadence.py`
- Test: `tests/unit/core/test_cadence.py`

**Interfaces:**
- Consumes: `core.db.types.CadenceMode`.
- Produces:
  - `Cadence(mode: CadenceMode, interval_days: int | None = None, interval_months: int | None = None, anchor: datetime | None = None)`, frozen.
  - `offset_seconds(user_id: uuid.UUID, span_seconds: int) -> int`
  - `next_slot(cadence: Cadence, user_id: uuid.UUID, now: datetime, *, min_interval: timedelta, window: timedelta) -> datetime` — always strictly after `now`. Raises `ValueError` for an `INTERVAL` cadence without a length or an anchor.
  - `EPOCH`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/core/test_cadence.py`:

```python
import uuid
import zlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.cadence import EPOCH, Cadence, next_slot, offset_seconds
from core.db.types import CadenceMode

USER = uuid.UUID("12345678-1234-5678-1234-567812345678")
MIN = timedelta(minutes=15)
WINDOW = timedelta(hours=1)
SHIFT = timedelta(seconds=offset_seconds(USER, 3600))


def _at(*parts):
    return datetime(*parts, tzinfo=UTC)


def _slot(cadence, now):
    return next_slot(cadence, USER, now, min_interval=MIN, window=WINDOW)


MIN_CADENCE = Cadence(CadenceMode.MIN)
DAILY = Cadence(CadenceMode.INTERVAL, interval_days=1, anchor=_at(2026, 1, 1, 9, 0))
MONTHLY_31 = Cadence(CadenceMode.INTERVAL, interval_months=1, anchor=_at(2026, 1, 31, 9, 0))


def test_the_offset_is_the_ids_crc32_within_the_span():
    """CRC32, not `hash`: Python salts `hash` per process, and the slot must not move on a restart."""
    assert offset_seconds(USER, 900) == zlib.crc32(USER.bytes) % 900


def test_offsets_spread_users_across_the_span():
    offsets = [offset_seconds(uuid.uuid5(uuid.NAMESPACE_OID, str(n)), 3600) for n in range(500)]

    assert all(0 <= offset < 3600 for offset in offsets)
    assert len(set(offsets)) > 400


def test_the_shift_is_within_the_window():
    assert timedelta(0) <= SHIFT < WINDOW


def test_a_min_cadence_falls_on_the_users_offset_within_each_interval():
    now = _at(2026, 10, 5, 12, 7)

    slot = _slot(MIN_CADENCE, now)

    assert now < slot <= now + MIN
    assert (slot - EPOCH).total_seconds() % 900 == offset_seconds(USER, 900)


def test_a_min_cadence_never_returns_now_itself():
    now = _slot(MIN_CADENCE, _at(2026, 10, 5, 12, 0))

    assert _slot(MIN_CADENCE, now) == now + MIN


def test_a_daily_cadence_runs_at_the_anchors_time_plus_the_users_shift():
    assert _slot(DAILY, _at(2026, 10, 5, 12, 0)) == _at(2026, 10, 6, 9, 0) + SHIFT


def test_todays_slot_is_returned_while_it_is_still_ahead():
    today = _at(2026, 10, 5, 9, 0) + SHIFT

    assert _slot(DAILY, today - timedelta(seconds=1)) == today


def test_missed_slots_are_not_caught_up():
    """Down for a week: the next run is the next slot, once (spec §10.2)."""
    assert _slot(DAILY, _at(2026, 10, 12, 10, 30)) == _at(2026, 10, 13, 9, 0) + SHIFT


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_at(2026, 2, 10), _at(2026, 2, 28, 9, 0)),
        (_at(2026, 3, 1), _at(2026, 3, 31, 9, 0)),
        (_at(2026, 4, 1), _at(2026, 4, 30, 9, 0)),
        (_at(2026, 5, 1), _at(2026, 5, 31, 9, 0)),
    ],
)
def test_a_monthly_cadence_on_the_31st_returns_to_the_31st(now, expected):
    """Months are counted from the anchor, never chained: chained, it would stay on the 28th."""
    assert _slot(MONTHLY_31, now) == expected + SHIFT


def test_a_quarterly_cadence_counts_calendar_months_from_the_anchor():
    quarterly = Cadence(CadenceMode.INTERVAL, interval_months=3, anchor=_at(2026, 1, 15, 9, 0))

    assert _slot(quarterly, _at(2026, 5, 1)) == _at(2026, 7, 15, 9, 0) + SHIFT


def test_days_and_months_together_add_both_per_step():
    both = Cadence(CadenceMode.INTERVAL, interval_days=1, interval_months=1, anchor=_at(2026, 1, 1, 9, 0))

    assert _slot(both, _at(2026, 1, 10)) == _at(2026, 2, 2, 9, 0) + SHIFT


def test_an_anchor_in_the_future_is_the_first_slot():
    later = Cadence(CadenceMode.INTERVAL, interval_days=7, anchor=_at(2027, 1, 1, 9, 0))

    assert _slot(later, _at(2026, 10, 5)) == _at(2027, 1, 1, 9, 0) + SHIFT


def test_an_anchor_given_in_another_zone_is_read_as_its_instant_in_utc():
    summer_in_madrid = datetime(2026, 7, 1, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    cadence = Cadence(CadenceMode.INTERVAL, interval_days=1, anchor=summer_in_madrid)

    assert _slot(cadence, _at(2026, 10, 5, 12, 0)) == _at(2026, 10, 6, 9, 0) + SHIFT


def test_an_interval_cadence_without_an_anchor_is_refused():
    with pytest.raises(ValueError):
        _slot(Cadence(CadenceMode.INTERVAL, interval_days=1), _at(2026, 10, 5))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_cadence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.cadence'`.

- [ ] **Step 3: Write the module**

Create `core/cadence.py`:

```python
"""When an operation is next due (spec §3.5, §10.2). Pure: no database, no clock.

Each user's slots are shifted by an offset taken from their id, so a thousand users on the
same cadence do not fall due in the same minute. The offset is a hash, not the clock: it
is uniform, and the same on every run, so an incident can be reproduced.
"""

from __future__ import annotations

import calendar
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.db.types import CadenceMode

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# The mean length of a calendar month, for a first guess only. The walk corrects it.
_MEAN_MONTH_DAYS = 30.436875


@dataclass(frozen=True)
class Cadence:
    mode: CadenceMode
    interval_days: int | None = None
    interval_months: int | None = None
    # An instant. Below a day it carries no meaning and is ignored.
    anchor: datetime | None = None


def offset_seconds(user_id: uuid.UUID, span_seconds: int) -> int:
    """Where in `span_seconds` this user's slots fall.

    CRC32 of the id, not `hash`: Python salts `hash` per process, and a user's slot must
    not move when the process restarts.
    """
    return zlib.crc32(user_id.bytes) % span_seconds


def next_slot(
    cadence: Cadence, user_id: uuid.UUID, now: datetime, *, min_interval: timedelta, window: timedelta
) -> datetime:
    """The first slot strictly after `now`.

    A slot missed while the system was down is not caught up: the next one is after `now`,
    so a user is evaluated once, never once per missed slot (spec §10.2).
    """
    if cadence.mode == CadenceMode.MIN:
        return _every(user_id, now, min_interval)
    return _anchored(cadence, user_id, now, window)


def _every(user_id: uuid.UUID, now: datetime, interval: timedelta) -> datetime:
    """`epoch + k × interval + offset`: below a day there is no anchor (spec §10.2)."""
    step = int(interval.total_seconds())
    offset = offset_seconds(user_id, step)
    elapsed = int((now - EPOCH).total_seconds()) - offset
    return EPOCH + timedelta(seconds=(elapsed // step + 1) * step + offset)


def _anchored(cadence: Cadence, user_id: uuid.UUID, now: datetime, window: timedelta) -> datetime:
    """`anchor + k × (months, days) + offset`, the offset inside `window`.

    The anchor fixes the date and the time; the offset spreads users over the hour after it.
    """
    days = cadence.interval_days or 0
    months = cadence.interval_months or 0
    if cadence.anchor is None or days + months == 0:
        raise ValueError("an INTERVAL cadence needs a length and an anchor")
    anchor = cadence.anchor.astimezone(UTC)
    shift = timedelta(seconds=offset_seconds(user_id, int(window.total_seconds())))

    # A guess from the mean length of a step, then a walk to the exact one.
    mean_step = timedelta(days=days + months * _MEAN_MONTH_DAYS)
    k = max(0, int((now - anchor) / mean_step))
    while k > 0 and _occurrence(anchor, k, months, days) + shift > now:
        k -= 1
    while _occurrence(anchor, k, months, days) + shift <= now:
        k += 1
    return _occurrence(anchor, k, months, days) + shift


def _occurrence(anchor: datetime, k: int, months: int, days: int) -> datetime:
    """The k-th step. Months are counted from the anchor each time, never chained: an anchor
    on the 31st falls on the 30th or the 28th, and returns to the 31st."""
    return _add_months(anchor, k * months) + timedelta(days=k * days)


def _add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_cadence.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/cadence.py tests/unit/core/test_cadence.py
git commit -m "feat(cadence): the next slot of a cadence, staggered by the user's id"
```

---

### Task 3: The scheduler's settings

**Files:**
- Modify: `core/config.py`, `.env.example`
- Test: `tests/unit/core/test_config.py`

**Interfaces:**
- Produces: `core.config.SchedulerConfig` (frozen) with `enabled: bool = False`,
  `tick: timedelta = 60 s`, `batch: int = 50`, `workers: int = 4`,
  `min_cadence: timedelta = 15 min`, `window: timedelta = 1 h`, `alert_streak: int = 3`,
  `sessions_retention: timedelta = 90 days`; `AppConfig.scheduler: SchedulerConfig`,
  defaulting to `SchedulerConfig()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/core/test_config.py` (add `SchedulerConfig` to the import from
`core.config`):

```python
def test_the_scheduler_is_on_with_the_specs_defaults():
    assert load_config(_env()).scheduler == SchedulerConfig(enabled=True)


def test_every_scheduler_setting_can_be_set():
    scheduler = load_config(
        _env(
            SCHEDULER_ENABLED="false",
            SCHEDULER_TICK_SECONDS="30",
            SCHEDULER_BATCH="10",
            SCHEDULER_WORKERS="2",
            SCHEDULER_MIN_CADENCE_MINUTES="5",
            SCHEDULER_WINDOW_SECONDS="600",
            SCHEDULER_ALERT_STREAK="5",
            SESSIONS_RETENTION_DAYS="30",
        )
    ).scheduler

    assert scheduler == SchedulerConfig(
        enabled=False,
        tick=timedelta(seconds=30),
        batch=10,
        workers=2,
        min_cadence=timedelta(minutes=5),
        window=timedelta(seconds=600),
        alert_streak=5,
        sessions_retention=timedelta(days=30),
    )


@pytest.mark.parametrize(
    "name",
    [
        "SCHEDULER_TICK_SECONDS",
        "SCHEDULER_BATCH",
        "SCHEDULER_WORKERS",
        "SCHEDULER_MIN_CADENCE_MINUTES",
        "SCHEDULER_WINDOW_SECONDS",
        "SCHEDULER_ALERT_STREAK",
        "SESSIONS_RETENTION_DAYS",
    ],
)
def test_a_scheduler_setting_must_be_a_positive_integer(name):
    with pytest.raises(ConfigError, match=name):
        load_config(_env(**{name: "0"}))


def test_a_config_built_by_hand_has_the_scheduler_off():
    """Tests build `AppConfig` directly. None of them may start a thread by accident."""
    assert SchedulerConfig().enabled is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'SchedulerConfig'`.

- [ ] **Step 3: Write the code**

In `core/config.py`, before `AppConfig`:

```python
@dataclass(frozen=True)
class SchedulerConfig:
    """The scheduler's settings (spec §10). The defaults are the spec's."""

    # Off unless the environment turns it on: a test that builds an `AppConfig` by hand
    # must not start a thread. `load_config` defaults it to on.
    enabled: bool = False
    tick: timedelta = timedelta(seconds=60)
    # Users per tick at most. After an outage every user is due at once (spec §10.2).
    batch: int = 50
    workers: int = 4
    # `MIN`: the system minimum cadence (spec §3.5).
    min_cadence: timedelta = timedelta(minutes=15)
    # How far after an `INTERVAL` anchor the users are spread (spec §10.2).
    window: timedelta = timedelta(hours=1)
    # Failures in a row before the one warning (spec §10.5).
    alert_streak: int = 3
    sessions_retention: timedelta = timedelta(days=90)
```

Add the last field to `AppConfig`, after `credential_key_version`:

```python
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
```

In `load_config`, add to the `AppConfig(...)` call, after `credential_key_version=version,`:

```python
        scheduler=_scheduler(environ),
```

and add after `load_config`:

```python
def _scheduler(environ: Mapping[str, str]) -> SchedulerConfig:
    defaults = SchedulerConfig()

    def seconds(name: str, default: timedelta) -> timedelta:
        return timedelta(seconds=_positive(environ, name, default=int(default.total_seconds())))

    return SchedulerConfig(
        enabled=_flag(environ, "SCHEDULER_ENABLED", default=True),
        tick=seconds("SCHEDULER_TICK_SECONDS", defaults.tick),
        batch=_positive(environ, "SCHEDULER_BATCH", default=defaults.batch),
        workers=_positive(environ, "SCHEDULER_WORKERS", default=defaults.workers),
        min_cadence=timedelta(
            minutes=_positive(
                environ,
                "SCHEDULER_MIN_CADENCE_MINUTES",
                default=int(defaults.min_cadence.total_seconds()) // 60,
            )
        ),
        window=seconds("SCHEDULER_WINDOW_SECONDS", defaults.window),
        alert_streak=_positive(environ, "SCHEDULER_ALERT_STREAK", default=defaults.alert_streak),
        sessions_retention=timedelta(
            days=_positive(environ, "SESSIONS_RETENTION_DAYS", default=defaults.sessions_retention.days)
        ),
    )
```

Append to `.env.example`:

```bash

# The scheduler (spec §10). Every value below is the default.
# false keeps the API up with nothing running on its own.
SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=60
# Users evaluated per tick at most.
SCHEDULER_BATCH=50
SCHEDULER_WORKERS=4
# The MIN cadence.
SCHEDULER_MIN_CADENCE_MINUTES=15
# How far after an INTERVAL anchor's time the users are spread.
SCHEDULER_WINDOW_SECONDS=3600
# Failed scheduled operations in a row before the one warning in the log.
SCHEDULER_ALERT_STREAK=3
SESSIONS_RETENTION_DAYS=90
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/config.py .env.example tests/unit/core/test_config.py
git commit -m "feat(config): the scheduler's settings, with the spec's defaults"
```

---

### Task 4: Names and pairs from the catalog, and one tick's prices

**Files:**
- Create: `core/public_market.py`
- Modify: `api/context.py`, `core/catalog.py` (module docstring only)
- Test: `tests/unit/core/test_public_market.py`, `tests/integration/test_api_portfolio.py`

**Interfaces:**
- Consumes: `core.catalog.MarketCatalog` (`asset_names()`, `pairs()`); a public client
  with `ticker(pairs: list[str]) -> dict[str, Decimal] | None`.
- Produces:
  - `Market(catalog, public)` with `assets()`, `asset_pairs()`, `ticker(pairs)` — the
    interface `core.reading.read_portfolio` reads.
  - `TickMarket(source)` with the same three, plus `preload(pairs: Iterable[str]) -> None`.
    `source` is any object with those three methods, a `Market` in practice.
  - `AppContext.public_kraken() -> Market`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/core/test_public_market.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from core.catalog import MarketCatalog
from core.public_market import Market, TickMarket

D = Decimal
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class FakeKraken:
    """The catalog's source and the public client at once, recording every call."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.prices = {"XXBTZEUR": D("50000"), "XETHZEUR": D("2500")}

    def assets(self):
        self.calls.append("Assets")
        return {"XXBT": "XBT", "ZEUR": "EUR"}

    def asset_decimals(self):
        self.calls.append("Assets")
        return {"EUR": 4}

    def asset_pairs(self):
        self.calls.append("AssetPairs")
        return {}

    def ticker(self, pairs):
        self.calls.append(("Ticker", tuple(pairs)))
        if self.down:
            return None
        return {pair: self.prices[pair] for pair in pairs if pair in self.prices}


def _market(kraken):
    return Market(MarketCatalog(kraken, lambda: NOW), kraken)


def _tickers(kraken):
    return [call[1] for call in kraken.calls if isinstance(call, tuple)]


def test_names_and_pairs_come_from_the_catalog_and_are_read_once():
    kraken = FakeKraken()
    market = _market(kraken)

    market.assets()
    names = market.assets()
    market.asset_pairs()
    market.asset_pairs()

    assert dict(names) == {"XXBT": "XBT", "ZEUR": "EUR"}
    assert kraken.calls == ["Assets", "AssetPairs"]


def test_a_market_reads_prices_live_on_every_call():
    kraken = FakeKraken()
    market = _market(kraken)

    market.ticker(["XXBTZEUR"])
    market.ticker(["XXBTZEUR"])

    assert _tickers(kraken) == [("XXBTZEUR",), ("XXBTZEUR",)]


def test_a_tick_reads_the_batchs_prices_in_one_call():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    tick.preload(["XXBTZEUR", "XETHZEUR", "XXBTZEUR"])

    assert tick.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("50000")}
    assert tick.ticker(["XETHZEUR", "XXBTZEUR"]) == {"XETHZEUR": D("2500"), "XXBTZEUR": D("50000")}
    assert _tickers(kraken) == [("XETHZEUR", "XXBTZEUR")]


def test_a_pair_the_preload_missed_is_read_once_and_kept():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))
    tick.preload(["XXBTZEUR"])

    tick.ticker(["XXBTZEUR", "XETHZEUR"])
    tick.ticker(["XETHZEUR"])

    assert _tickers(kraken) == [("XXBTZEUR",), ("XETHZEUR",)]


def test_a_failed_read_is_none_and_the_next_call_asks_again():
    kraken = FakeKraken()
    kraken.down = True
    tick = TickMarket(_market(kraken))
    tick.preload(["XXBTZEUR"])

    assert tick.ticker(["XXBTZEUR"]) is None
    kraken.down = False
    assert tick.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("50000")}
    assert len(_tickers(kraken)) == 3


def test_nothing_is_read_for_no_pairs():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    tick.preload([])

    assert tick.ticker([]) == {}
    assert _tickers(kraken) == []


def test_a_tick_reads_names_and_pairs_through_its_source():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    assert dict(tick.assets()) == {"XXBT": "XBT", "ZEUR": "EUR"}
    assert dict(tick.asset_pairs()) == {}
```

Append to `tests/integration/test_api_portfolio.py`:

```python
def test_a_refresh_reads_names_and_pairs_from_the_catalog(api, make_user, login, fake_kraken):
    """Every public call shares one bucket at a call a second. Names and pairs change when
    Kraken lists an asset, not on every refresh."""
    headers = login(make_user())
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100"}
    fake_kraken.calls.clear()

    api.post("/portfolio/refresh", headers=headers)
    api.post("/portfolio/refresh", headers=headers)

    assert "Assets" not in fake_kraken.calls
    assert "AssetPairs" not in fake_kraken.calls
    assert fake_kraken.calls.count("Balance") == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command with `tests/unit/core/test_public_market.py tests/integration/test_api_portfolio.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.public_market'`, and the
integration test finds `Assets` in the calls.

- [ ] **Step 3: Write the module**

Create `core/public_market.py`:

```python
"""Kraken's public side as an evaluation reads it (spec §10.1).

Every public call in the process shares one bucket, paced at a call a second, because
Kraken counts public calls per address. An evaluation that read `Assets` and `AssetPairs`
itself spent two of those seconds on data that changes only when Kraken lists an asset,
so `Market` reads them from the daily catalog. A tick goes further: `TickMarket` reads
the prices of its whole batch in one call and shares them.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Protocol

from core.catalog import MarketCatalog
from exchange.types import PairMeta


class PublicReads(Protocol):
    """What `core.reading.read_portfolio` reads from Kraken's public side."""

    def assets(self) -> Mapping[str, str] | None: ...

    def asset_pairs(self) -> Mapping[str, PairMeta] | None: ...

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None: ...


class Market:
    """Names and pairs from the catalog; prices from Kraken, on every call."""

    def __init__(self, catalog: MarketCatalog, public) -> None:
        self._catalog = catalog
        self._public = public

    def assets(self) -> Mapping[str, str] | None:
        return self._catalog.asset_names()

    def asset_pairs(self) -> Mapping[str, PairMeta] | None:
        return self._catalog.pairs()

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None:
        return self._public.ticker(pairs)


class TickMarket:
    """One tick's prices, read once and shared by every evaluation in it.

    A price is at most a tick old when it is used, and it only sizes the plan: the orders
    are market orders, and Kraken's minimum is computed from the same price, as before.
    """

    def __init__(self, source: PublicReads) -> None:
        self._source = source
        self._prices: dict[str, Decimal] = {}
        self._guard = threading.Lock()

    def assets(self) -> Mapping[str, str] | None:
        return self._source.assets()

    def asset_pairs(self) -> Mapping[str, PairMeta] | None:
        return self._source.asset_pairs()

    def preload(self, pairs: Iterable[str]) -> None:
        """One call for every pair the batch is configured with. A failure keeps nothing,
        and each evaluation then asks for its own pairs."""
        self.ticker(sorted(set(pairs)))

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None:
        # The guard is held across the call: two evaluations missing the same pair would
        # otherwise both ask, and the public bucket makes them wait in turn anyway.
        with self._guard:
            missing = [pair for pair in pairs if pair not in self._prices]
            if missing:
                fetched = self._source.ticker(missing)
                if fetched is None:
                    return None
                self._prices.update(fetched)
            return {pair: self._prices[pair] for pair in pairs if pair in self._prices}
```

In `api/context.py`, add `from core.public_market import Market` and replace
`public_kraken`:

```python
    def public_kraken(self) -> Market:
        """Kraken's public side: names and pairs from the catalog, prices live."""
        return Market(self.catalog, KrakenClient(self.kraken_http, self.limiter))
```

In `core/catalog.py`, replace the last paragraph of the module docstring:

```
A copy up to a day old is accepted: an asset Kraken lists today may be refused until the
next read. Nothing that values a portfolio or places an order reads from here; those read
Kraken live.
```

with:

```
A copy up to a day old is accepted: an asset Kraken lists today may be refused until the
next read. Evaluations read names and pairs from here too (`core.public_market`). Prices
are never kept here: they are read live, or once per scheduler tick.
```

- [ ] **Step 4: Run them to verify they pass**

Run: the test command.
Expected: PASS, every test. `test_api_assets.py` still sees `["Assets", "AssetPairs"]`:
`PUT /assets` reads the catalog, as before.

- [ ] **Step 5: Commit**

```bash
git add core/public_market.py core/catalog.py api/context.py tests/unit/core/test_public_market.py tests/integration/test_api_portfolio.py
git commit -m "feat(market): names and pairs from the catalog, and a tick's prices in one call"
```

---

### Task 5: Evaluations say what they were, keep the day's snapshot, and a rebalance can run unapproved

**Files:**
- Modify: `core/execution.py`, `core/rebalance.py`, `api/routes/portfolio.py`
- Test: `tests/integration/test_execution.py`, `tests/integration/test_rebalance.py`, `tests/integration/test_api_invest.py`, `tests/integration/test_api_portfolio.py`

**Interfaces:**
- Consumes: Task 1's `Operation`, `Trigger`, `db.keep_snapshot`, `db.pin_snapshot`,
  `db.start_evaluation(..., operation=, trigger=)`.
- Produces:
  - `invest(context, user_id, *, preview: bool = False, trigger: Trigger = Trigger.API) -> EvaluationResult`
  - `evaluate(context, user_id, *, allow_sells, reason, decide, operation: Operation, trigger: Trigger) -> EvaluationResult`
  - `propose(context, user_id, *, trigger: Trigger = Trigger.API) -> RebalanceResult` —
    the proposal's trigger is `SCHEDULED` when `trigger` is `SCHEDULER`, `MANUAL` otherwise.
  - `rebalance_now(context, user_id) -> EvaluationResult` — executes without an approval,
    withdrawing a live proposal first. Raises what `evaluate` raises.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_execution.py` (add `snapshots_since` to the import from
`core.db.telemetry`, and `from core.db.types import Trigger`):

```python
def test_the_snapshot_before_sent_orders_is_pinned(app_context, db_session, ready):
    user = ready()

    invest(app_context, user.id)

    assert latest_snapshot(db_session, user.id).pinned is True


def test_the_snapshot_is_pinned_before_the_first_order_leaves(app_context, db_session, fake_kraken, ready):
    """If the process dies mid-operation, the account before it is still on record."""
    user = ready()
    seen = []
    fake_kraken.on_add_order = lambda form: seen.append(latest_snapshot(db_session, user.id).pinned)

    invest(app_context, user.id)

    assert seen
    assert all(seen)


def test_reads_with_nothing_to_send_keep_one_point_for_the_day(app_context, db_session, fake_kraken, ready):
    user = ready()
    # 600 EUR of XBT and 400 EUR of ETH against 60/40, and no cash: nothing to invest.
    fake_kraken.balance = {"ZEUR": "0", "XXBT": "0.012", "XETH": "0.16"}

    first = invest(app_context, user.id)
    second = invest(app_context, user.id)

    assert (first.status, second.status) == (EvaluationStatus.NOTHING_TO_DO, EvaluationStatus.NOTHING_TO_DO)
    series = snapshots_since(db_session, user.id, app_context.now() - timedelta(days=1))
    assert [snapshot.pinned for snapshot in series] == [False]


def test_an_evaluation_records_its_operation_and_trigger(app_context, db_session, ready):
    user = ready()

    invest(app_context, user.id)
    invest(app_context, user.id, trigger=Trigger.SCHEDULER)

    assert sorted((e.operation, e.trigger) for e in list_evaluations(db_session, user.id)) == [
        ("INVEST", "API"),
        ("INVEST", "SCHEDULER"),
    ]
```

Append to `tests/integration/test_rebalance.py` (add `rebalance_now` to the import from
`core.rebalance`, and `from core.db.types import Trigger`):

```python
def test_a_scheduled_proposal_is_marked_scheduled(app_context, db_session, user):
    result = propose(app_context, user.id, trigger=Trigger.SCHEDULER)

    assert result.proposal.trigger == "SCHEDULED"
    record = list_evaluations(db_session, user.id)[0]
    assert (record.operation, record.trigger) == ("PROPOSE", "SCHEDULER")


def test_an_approval_is_recorded_as_one(app_context, db_session, user):
    propose(app_context, user.id)

    approve(app_context, user.id, 1)

    assert {(e.operation, e.trigger) for e in list_evaluations(db_session, user.id)} == {
        ("PROPOSE", "API"),
        ("APPROVE", "API"),
    }


def test_an_automatic_rebalance_executes_without_an_approval(app_context, db_session, fake_kraken, user):
    result = rebalance_now(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    assert {order.reason for order in list_orders(db_session, user.id)} == {OrderReason.REBALANCE}
    assert get_proposal(db_session, user.id) is None
    record = list_evaluations(db_session, user.id)[0]
    assert (record.operation, record.trigger) == ("REBALANCE", "SCHEDULER")


def test_an_automatic_rebalance_withdraws_the_live_proposal_first(app_context, db_session, fake_kraken, user):
    """What executes is today's plan. A proposal left live would offer an approval of
    something already done."""
    propose(app_context, user.id)

    result = rebalance_now(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert any("proposal version 1 was withdrawn" in message for message in result.messages)
```

Append to `tests/integration/test_api_invest.py`:

```python
def test_the_history_says_what_each_evaluation_was(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    api.post("/invest", headers=headers)

    [entry] = api.get("/sessions", headers=headers).json()
    assert (entry["operation"], entry["trigger"]) == ("INVEST", "API")
```

Append to `tests/integration/test_api_portfolio.py` (add `snapshots_since` to the import
from `core.db.telemetry`, and `timedelta` to the `datetime` import):

```python
def test_refreshes_of_the_same_day_keep_one_point(api, app_context, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100"}

    api.post("/portfolio/refresh", headers=headers)
    api.post("/portfolio/refresh", headers=headers)

    assert len(snapshots_since(db_session, user.id, app_context.now() - timedelta(days=1))) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command.
Expected: FAIL — `invest()` takes no `trigger`, `ImportError` for `rebalance_now`, and the
snapshot tests find unpinned or duplicate rows.

- [ ] **Step 3: The executor**

In `core/execution.py`:

1. Change the import `from core.db.types import OrderReason` to
   `from core.db.types import Operation, OrderReason, Trigger`.

2. In `ExecutionContext`'s docstring, replace `a scheduler will be another` with
   `the scheduler's tick is another`.

3. Replace `invest`:

```python
def invest(
    context: ExecutionContext,
    user_id: uuid.UUID,
    *,
    preview: bool = False,
    trigger: Trigger = Trigger.API,
) -> EvaluationResult:
    """Invest the user's free cash now or, with `preview`, say what that would do.

    Raises `NotReady` before anything is read, `EvaluationBusy` when another evaluation
    of the user holds the lock, and `CredentialsUnreadable` when the stored key does not
    open. Every other outcome is a status in the result.
    """
    if preview:
        account = _load(context, user_id, allow_sells=False)
        private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
        return _preview(context, user_id, account, private)
    return evaluate(
        context,
        user_id,
        allow_sells=False,
        reason=OrderReason.INVEST,
        decide=_send_it,
        operation=Operation.INVEST,
        trigger=trigger,
    )
```

4. Replace `evaluate` and `_run`:

```python
def evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    *,
    allow_sells: bool,
    reason: OrderReason,
    decide: Decision,
    operation: Operation,
    trigger: Trigger,
) -> EvaluationResult:
    """Lock, resolve, read and plan; then let `decide` judge, and send what it lets through.

    Raises as `invest` does. Every other outcome is a status in the result, and recorded
    with `operation` and `trigger`.
    """
    account = _load(context, user_id, allow_sells=allow_sells)
    private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
    with context.user_lock(user_id) as taken:
        if not taken:
            raise EvaluationBusy(str(user_id))
        return _run(context, user_id, account, private, reason, decide, operation, trigger)
```

```python
def _run(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    reason: OrderReason,
    decide: Decision,
    operation: Operation,
    trigger: Trigger,
) -> EvaluationResult:
    with context.sessions() as session:
        evaluation_id = db.start_evaluation(
            session, user_id, context.now(), operation=operation, trigger=trigger
        ).id
    log: list[str] = []
    legs: list[LegResult] = []
    status = EvaluationStatus.ERROR
    try:
        status = _evaluate(context, user_id, account, private, reason, decide, log, legs)
    except PortfolioUnavailable as exc:
        status = EvaluationStatus.KRAKEN_UNAVAILABLE
        log.append(f"kraken did not return {exc}; nothing was sent")
    finally:
        with context.sessions() as session:
            db.finish_evaluation(session, evaluation_id, status, context.now(), "\n".join(log) or None)
    return EvaluationResult(status=status, preview=False, legs=tuple(legs), messages=tuple(log))
```

5. In `_evaluate`, replace the snapshot block and the call to `_send_all`:

```python
    planned = _plan(context, account, private)
    with context.sessions() as session:
        snapshot_id = db.keep_snapshot(
            session,
            user_id,
            as_of=context.now(),
            fiat=account.fiat,
            total_value=planned.view.managed_value,
            cash=planned.view.cash,
            holdings=planned.view.snapshot_json(),
        ).id

    verdict = decide(planned, log)
    if verdict is not None:
        return verdict

    pin = _Pin(context, user_id, snapshot_id)
    stopped = _send_all(context, user_id, private, planned, reason, account.fiat, log, legs, pin)
```

(The rest of `_evaluate` is unchanged.)

6. Add the class after `UNRESOLVED_MESSAGE`:

```python
class _Pin:
    """Pins the evaluation's snapshot once, just before its first order is sent.

    Before, not after: a process that dies mid-operation still leaves the account as it was
    before the orders, and the day's next read cannot overwrite it.
    """

    def __init__(self, context: ExecutionContext, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
        self._context = context
        self._user_id = user_id
        self._snapshot_id = snapshot_id
        self._done = False

    def __call__(self) -> None:
        if self._done:
            return
        with self._context.sessions() as session:
            db.pin_snapshot(session, self._user_id, self._snapshot_id)
        self._done = True
```

7. Give `_send_all` a last parameter `pin: Callable[[], None]`, and pass it to both
   `_attempt` calls: `_attempt(context, user_id, private, leg, reason, stopped, pin)`.

8. Replace `_attempt`:

```python
def _attempt(
    context: ExecutionContext,
    user_id: uuid.UUID,
    private,
    leg: PlannedLeg,
    reason: OrderReason,
    stopped: bool,
    pin: Callable[[], None],
) -> tuple[LegResult, bool]:
    """Send one leg unless it is skipped or an earlier answer was lost. Returns `stopped`."""
    if leg.note is not None:
        return _skipped(leg, leg.note), stopped
    if stopped:
        return _skipped(leg, "not sent: an earlier order's answer is unknown"), True
    pin()
    result = _send(context, user_id, private, leg, reason)
    # An unknown answer leaves no txid. The balance is ambiguous until resolved.
    return result, result.status is LegStatus.PENDING and result.txid is None
```

- [ ] **Step 4: The rebalance**

In `core/rebalance.py`:

1. Replace the module docstring:

```python
"""The rebalance operation and its proposal (spec §3.4, §8).

A rebalance sells, and a sell cannot be undone. So a request to rebalance never sends
anything: `propose` computes the plan and keeps it as the user's one live proposal, and
`approve` executes it once the user has read it. The one exception is the user who turned
automatic rebalancing on, which is the authorisation: for them the scheduler calls
`rebalance_now`. The executor sends; this module decides whether there is anything to send.
"""
```

2. Change the imports: `from core.db.types import Operation, OrderReason, ProposalStatus, ProposalTrigger, Trigger`.

3. Replace `propose`:

```python
def propose(context: ExecutionContext, user_id: uuid.UUID, *, trigger: Trigger = Trigger.API) -> RebalanceResult:
    """Compute a rebalance and keep it as the live proposal. Never sends an order.

    The scheduler calls it too, with `Trigger.SCHEDULER`, for a user whose automatic
    rebalancing is off. Raises what `evaluate` raises.
    """
    proposal_trigger = ProposalTrigger.SCHEDULED if trigger is Trigger.SCHEDULER else ProposalTrigger.MANUAL

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus:
        document = plan_document(planned.view.fiat, planned.legs)
        with context.sessions() as session:
            _keep(session, user_id, document, proposal_trigger, log)
        return EvaluationStatus.PROPOSED if has_orders(document) else EvaluationStatus.NOTHING_TO_DO

    result = evaluate(
        context,
        user_id,
        allow_sells=True,
        reason=OrderReason.REBALANCE,
        decide=decide,
        operation=Operation.PROPOSE,
        trigger=trigger,
    )
    return RebalanceResult(result, current(context, user_id))
```

4. In `approve`, replace the `evaluate(...)` call inside the `try:` with:

```python
        result = evaluate(
            context,
            user_id,
            allow_sells=True,
            reason=OrderReason.REBALANCE,
            decide=decide,
            operation=Operation.APPROVE,
            trigger=Trigger.API,
        )
```

5. Add after `approve`:

```python
def rebalance_now(context: ExecutionContext, user_id: uuid.UUID) -> EvaluationResult:
    """Execute a rebalance without an approval. Only the scheduler calls this, and only for
    a user with automatic rebalancing on: enabling it was the authorisation (spec §3.4).

    A live proposal is withdrawn first. It was computed earlier, and what executes is
    today's plan; left live, it would offer an approval of something already done.
    """

    def decide(planned: Planned, log: list[str]) -> None:
        with context.sessions() as session:
            slot = db.get_live_proposal(session, user_id)
            if slot is not None:
                db.withdraw(session, user_id)
                log.append(f"automatic rebalancing is on; proposal version {slot.version} was withdrawn")
        return None

    return evaluate(
        context,
        user_id,
        allow_sells=True,
        reason=OrderReason.REBALANCE,
        decide=decide,
        operation=Operation.REBALANCE,
        trigger=Trigger.SCHEDULER,
    )
```

- [ ] **Step 5: A refresh keeps the day's point**

In `api/routes/portfolio.py`, in `refresh`, replace `db.record_snapshot(` with
`db.keep_snapshot(`. The arguments are the same.

- [ ] **Step 6: Run the tests**

Run: the test command.
Expected: PASS, every test.

- [ ] **Step 7: Commit**

```bash
git add core/execution.py core/rebalance.py api/routes/portfolio.py tests/integration/test_execution.py tests/integration/test_rebalance.py tests/integration/test_api_invest.py tests/integration/test_api_portfolio.py
git commit -m "feat(execution): evaluations say what they were, keep the day's snapshot, and a rebalance can run unapproved"
```

---

### Task 6: The next run follows the settings

**Files:**
- Create: `core/schedule.py`
- Modify: `core/db/settings.py`, `core/database.py`, `api/routes/config.py`
- Test: `tests/integration/test_schedule.py`, `tests/integration/test_api_config.py`

**Interfaces:**
- Consumes: Task 2's `Cadence`, `next_slot`; Task 3's `SchedulerConfig`.
- Produces:
  - `core.schedule.INVEST = "invest"`, `REBALANCE = "rebalance"` — the prefixes of the settings columns.
  - `next_run(settings: UserSettings, prefix: str, now: datetime, config: SchedulerConfig) -> datetime | None`
  - `rescheduled(settings, changed: Iterable[str], now, config) -> dict[str, datetime | None]` — keyword arguments for `update_settings`.
  - `backfill(session, now, config) -> int`
  - `db.unscheduled_settings(session) -> list[UserSettings]`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_schedule.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from core.config import SchedulerConfig
from core.db.settings import create_settings, get_settings, update_settings
from core.schedule import INVEST, REBALANCE, backfill, next_run

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
CONFIG = SchedulerConfig()


def test_an_investment_switched_off_has_no_next_run(db_session: Session, make_user):
    user = make_user()
    settings = create_settings(db_session, user.id, fiat="EUR")

    assert next_run(settings, INVEST, NOW, CONFIG) is None
    assert NOW < next_run(settings, REBALANCE, NOW, CONFIG) <= NOW + CONFIG.min_cadence


def test_settings_written_before_the_scheduler_get_their_next_runs(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, invest_cash_enabled=True)

    backfill(db_session, NOW, CONFIG)

    settings = get_settings(db_session, user.id)
    assert NOW < settings.next_invest_at <= NOW + CONFIG.min_cadence
    assert NOW < settings.next_rebalance_at <= NOW + CONFIG.min_cadence


def test_backfill_leaves_a_scheduled_user_and_an_idle_investment_alone(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    planned = NOW + timedelta(days=3)
    update_settings(db_session, user.id, next_rebalance_at=planned)

    backfill(db_session, NOW, CONFIG)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at == planned
    assert settings.next_invest_at is None
```

Append to `tests/integration/test_api_config.py` (add the imports):

```python
from datetime import UTC, datetime, timedelta

from core.cadence import offset_seconds
from core.db.settings import update_settings


def test_new_settings_look_for_drift_on_the_minimum_cadence_and_do_not_invest(
    api, app_context, db_session, make_user, login
):
    user = make_user()

    api.patch("/config", json={"fiat": "EUR"}, headers=login(user))

    settings = get_settings(db_session, user.id)
    assert settings.next_invest_at is None
    assert app_context.now() < settings.next_rebalance_at <= app_context.now() + timedelta(minutes=15)


def test_turning_investment_on_schedules_it_and_off_clears_it(api, app_context, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    api.patch("/config", json={"invest_cash_enabled": True}, headers=headers)
    assert app_context.now() < get_settings(db_session, user.id).next_invest_at

    api.patch("/config", json={"invest_cash_enabled": False}, headers=headers)
    assert get_settings(db_session, user.id).next_invest_at is None


def test_a_new_cadence_moves_its_next_run(api, db_session, make_user, login):
    """The clock is 2026-09-29 12:00: monthly from 1 January at 09:00 is next on 1 October."""
    user = make_user()
    headers = login(user)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    api.patch(
        "/config",
        json={
            "rebalance_cadence_mode": "INTERVAL",
            "rebalance_interval_months": 1,
            "rebalance_cadence_anchor": "2026-01-01T09:00:00Z",
        },
        headers=headers,
    )

    shift = timedelta(seconds=offset_seconds(user.id, 3600))
    assert get_settings(db_session, user.id).next_rebalance_at == datetime(2026, 10, 1, 9, 0, tzinfo=UTC) + shift


def test_a_change_to_anything_else_leaves_the_schedule_alone(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    planned = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    update_settings(db_session, user.id, next_rebalance_at=planned)

    api.patch("/config", json={"min_drift_pct": "5"}, headers=headers)

    assert get_settings(db_session, user.id).next_rebalance_at == planned
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command with `tests/integration/test_schedule.py tests/integration/test_api_config.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.schedule'`, and the API tests
find `next_rebalance_at` null.

- [ ] **Step 3: The DAL**

Append to `core/db/settings.py` (add `and_` to the `sqlalchemy` import):

```python
def unscheduled_settings(session: Session) -> list[UserSettings]:
    """Settings missing a next run they should have: written before the scheduler existed.

    Across every user, like the retention sweeps. It runs once, at start-up.
    """
    stmt = select(UserSettings).where(
        or_(
            UserSettings.next_rebalance_at.is_(None),
            and_(UserSettings.invest_cash_enabled.is_(True), UserSettings.next_invest_at.is_(None)),
        )
    )
    return list(session.execute(stmt).scalars())
```

Add `unscheduled_settings` to `core/database.py`'s import from `core.db.settings` and to
`__all__`.

- [ ] **Step 4: The module**

Create `core/schedule.py`:

```python
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
SOURCES = {
    INVEST: frozenset(
        {
            "invest_cash_enabled",
            "invest_cadence_mode",
            "invest_interval_days",
            "invest_interval_months",
            "invest_cadence_anchor",
        }
    ),
    REBALANCE: frozenset(
        {
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
```

- [ ] **Step 5: The route**

Replace `patch_config` in `api/routes/config.py` (import `Ctx` from `api.deps`, and
`from core.schedule import EVERY_SOURCE, rescheduled`):

```python
@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch, user: CurrentUser, session: Db, context: Ctx) -> UserSettings:
    changes = body.model_dump(exclude_unset=True)
    fiat = changes.pop("fiat", None)
    fiat = fiat.strip().upper() if isinstance(fiat, str) else None

    settings = db.lock_settings(session, user.id)
    created = settings is None
    if created:
        if fiat is None:
            raise HTTPException(409, "the first PATCH /config must choose a fiat")
        if fiat not in SUPPORTED_FIATS:
            raise HTTPException(422, f"supported fiats are {', '.join(SUPPORTED_FIATS)}")
        settings = db.create_settings(session, user.id, fiat=fiat)
    elif fiat is not None and fiat != settings.fiat:
        raise HTTPException(422, "the fiat cannot be changed")

    merged = _merged(settings, changes)
    for prefix in _CADENCES:
        problem = _cadence_problem(prefix, merged)
        if problem is not None:
            raise HTTPException(422, problem)

    if changes:
        settings = db.update_settings(session, user.id, **changes)
    # The scheduler's next runs follow the settings they come from (spec §10.2).
    moves = rescheduled(settings, EVERY_SOURCE if created else changes, context.now(), context.config.scheduler)
    if moves:
        settings = db.update_settings(session, user.id, **moves)
    return settings
```

- [ ] **Step 6: Run the tests**

Run: the test command.
Expected: PASS, every test.

- [ ] **Step 7: Commit**

```bash
git add core/schedule.py core/db/settings.py core/database.py api/routes/config.py tests/integration/test_schedule.py tests/integration/test_api_config.py
git commit -m "feat(schedule): the next runs follow the settings, and rows without them are filled"
```

---

### Task 7: The tick

**Files:**
- Create: `core/scheduler.py`
- Modify: `core/db/locks.py`, `core/db/settings.py`, `core/database.py`, `api/context.py`, `api/main.py`, `tests/integration/conftest.py`, `tests/unit/api/test_database_errors.py`
- Test: `tests/integration/test_scheduler.py`, `tests/integration/test_locks.py`, `tests/integration/test_settings.py`

**Interfaces:**
- Consumes: Task 4's `TickMarket`; Task 5's `invest(..., trigger=)`, `propose(..., trigger=)`,
  `rebalance_now`; Task 6's `next_run`, `INVEST`, `REBALANCE`; `db.due_users`,
  `db.delete_evaluations_before`, `db.delete_expired_refresh_tokens`.
- Produces:
  - `advisory_scheduler_lock(engine, key: tuple[int, int] = SCHEDULER_LOCK) -> ContextManager[bool]`
  - `db.pairs_for(session, user_ids) -> set[str]`
  - `AppContext.scheduler_lock: Callable[[], AbstractContextManager[bool]]`
  - `Scheduler(context)` with `tick(now: datetime) -> TickReport`
  - `TickReport(ran: bool, users: int = 0, swept: bool = False)`, frozen
  - `FAILURES`
  - In `tests/integration/conftest.py`: `FakeSchedulerLock` (attribute `held: bool`) and
    the fixture `scheduler_lock`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_locks.py` (add
`from core.db.locks import advisory_scheduler_lock` to the imports):

```python
# A key of the tests' own, so a running API's tick never makes these flaky.
TEST_KEY = (0x74657374, 7)


def test_only_one_process_runs_a_tick(engine):
    with advisory_scheduler_lock(engine, TEST_KEY) as first, advisory_scheduler_lock(engine, TEST_KEY) as second:
        assert first is True
        assert second is False


def test_the_tick_lock_is_released(engine):
    with advisory_scheduler_lock(engine, TEST_KEY):
        pass

    with advisory_scheduler_lock(engine, TEST_KEY) as again:
        assert again is True


def test_the_tick_lock_and_a_user_lock_do_not_collide(engine):
    with advisory_scheduler_lock(engine, TEST_KEY) as tick, advisory_user_lock(engine, uuid.uuid4()) as user:
        assert tick is True
        assert user is True
```

Append to `tests/integration/test_settings.py` (add `pairs_for` to the import from
`core.db.settings`):

```python
def test_the_pairs_of_a_batch_are_read_together(db_session: Session, make_user):
    alice, bob, carol = make_user(), make_user(), make_user()
    for person in (alice, bob, carol):
        create_settings(db_session, person.id, fiat="EUR")
    upsert_asset(db_session, alice.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
    upsert_asset(db_session, bob.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
    upsert_asset(db_session, bob.id, asset="ETH", pair="XETHZEUR", target_pct=D("50"))
    upsert_asset(db_session, carol.id, asset="SOL", pair="SOLEUR", target_pct=D("50"))

    assert pairs_for(db_session, [alice.id, bob.id]) == {"XXBTZEUR", "XETHZEUR"}
    assert pairs_for(db_session, []) == set()
```

Create `tests/integration/test_scheduler.py`:

```python
import base64
import logging
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

import core.scheduler as scheduler_module
from core.config import SchedulerConfig
from core.db.proposals import get_proposal
from core.db.settings import create_settings, get_settings, update_settings, upsert_asset
from core.db.telemetry import list_evaluations, start_evaluation
from core.db.types import ProposalStatus
from core.db.users import save_credentials
from core.rebalance import propose
from core.schedule import INVEST, next_run
from core.scheduler import Scheduler, TickReport
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
# 700 EUR of XBT and 300 EUR of ETH against 50/50: sell 200 of XBT, buy 200 of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}
MINUTE = timedelta(minutes=1)


def _with(context, **changes):
    """The context with scheduler settings changed. One worker: the test's session is not thread-safe."""
    settings = replace(SchedulerConfig(workers=1), **changes)
    return replace(context, config=replace(context.config, scheduler=settings))


@pytest.fixture
def context(app_context):
    return _with(app_context)


@pytest.fixture
def scheduler(context):
    return Scheduler(context)


@pytest.fixture
def now(app_context):
    return app_context.now()


@pytest.fixture
def account(app_context, db_session, make_user, fake_kraken):
    """A user ready to be evaluated: EUR, XBT and ETH at 50 % each, and a sealed key.

    `key_owner` seals the key for another id, so it does not open for this user.
    """

    def _account(balance=DRIFTED, key_owner=None, **settings):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        upsert_asset(db_session, user.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
        upsert_asset(db_session, user.id, asset="ETH", pair="XETHZEUR", target_pct=D("50"))
        sealed = app_context.cipher.seal(key_owner or user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(
            db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
        )
        if settings:
            update_settings(db_session, user.id, **settings)
        fake_kraken.balance = dict(balance)
        return user

    return _account


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_a_due_investment_is_sent_and_its_next_run_moves_forward(
    scheduler, context, db_session, fake_kraken, account, now
):
    user = account(balance={"ZEUR": "1000"}, invest_cash_enabled=True, next_invest_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report == TickReport(ran=True, users=1, swept=True)
    assert {form["type"] for form in _sent(fake_kraken)} == {"buy"}
    record = list_evaluations(db_session, user.id)[0]
    assert (record.status, record.operation, record.trigger) == ("DONE", "INVEST", "SCHEDULER")
    settings = get_settings(db_session, user.id)
    assert settings.next_invest_at > now
    assert settings.next_invest_at == next_run(settings, INVEST, now, context.config.scheduler)


def test_a_user_not_yet_due_is_left_alone(scheduler, fake_kraken, account, now):
    account(next_rebalance_at=now + MINUTE)

    report = scheduler.tick(now)

    assert report.users == 0
    assert "Balance" not in fake_kraken.calls


def test_a_scheduled_rebalance_only_proposes_while_automatic_rebalancing_is_off(
    scheduler, db_session, fake_kraken, account, now
):
    user = account(next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert _sent(fake_kraken) == []
    proposal = get_proposal(db_session, user.id)
    assert (proposal.status, proposal.trigger, proposal.version) == ("LIVE", "SCHEDULED", 1)
    assert list_evaluations(db_session, user.id)[0].operation == "PROPOSE"


def test_automatic_rebalancing_executes_and_withdraws_the_live_proposal(
    app_context, scheduler, db_session, fake_kraken, account, now
):
    user = account()
    propose(app_context, user.id)
    update_settings(db_session, user.id, auto_rebalance_enabled=True, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert {e.operation for e in list_evaluations(db_session, user.id)} == {"PROPOSE", "REBALANCE"}


def test_when_both_are_due_the_investment_runs_first(scheduler, monkeypatch, account, now):
    order = []
    real_invest, real_propose = scheduler_module.invest, scheduler_module.propose
    monkeypatch.setattr(
        "core.scheduler.invest", lambda *args, **kwargs: order.append("invest") or real_invest(*args, **kwargs)
    )
    monkeypatch.setattr(
        "core.scheduler.propose", lambda *args, **kwargs: order.append("propose") or real_propose(*args, **kwargs)
    )
    account(invest_cash_enabled=True, next_invest_at=now - MINUTE, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert order == ["invest", "propose"]


def test_one_users_failure_does_not_stop_the_next(scheduler, db_session, account, now, caplog):
    broken = account(key_owner=uuid.uuid4(), next_rebalance_at=now - timedelta(hours=1))
    healthy = account(next_rebalance_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report.users == 2
    assert list_evaluations(db_session, healthy.id)[0].status == "PROPOSED"
    settings = get_settings(db_session, broken.id)
    assert settings.failure_streak == 1
    assert settings.next_rebalance_at > now
    assert any(str(broken.id) in record.getMessage() for record in caplog.records)


def test_failures_warn_once_at_the_threshold_and_the_recovery_is_noted(
    scheduler, db_session, fake_kraken, account, now, caplog
):
    caplog.set_level(logging.INFO, logger="coinpilot.scheduler")
    user = account()
    fake_kraken.down.add("Balance")

    for _ in range(4):
        update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)
        scheduler.tick(now)

    assert get_settings(db_session, user.id).failure_streak == 4
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()

    fake_kraken.down.clear()
    update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)
    scheduler.tick(now)

    assert get_settings(db_session, user.id).failure_streak == 0
    assert any("recovered" in record.getMessage() for record in caplog.records)


def test_a_busy_user_is_tried_again_on_the_next_tick(scheduler, user_locks, db_session, account, now):
    due = now - MINUTE
    user = account(next_rebalance_at=due)
    user_locks.held.add(user.id)

    scheduler.tick(now)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at == due
    assert settings.failure_streak == 0
    assert list_evaluations(db_session, user.id) == []


def test_a_user_without_a_key_moves_forward_without_counting_a_failure(scheduler, db_session, make_user, now):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at > now
    assert settings.failure_streak == 0
    assert list_evaluations(db_session, user.id) == []


def test_an_investment_switched_off_is_not_run_and_leaves_no_next_run(
    scheduler, db_session, fake_kraken, account, now
):
    user = account(balance={"ZEUR": "1000"}, next_invest_at=now - MINUTE)

    scheduler.tick(now)

    assert _sent(fake_kraken) == []
    assert get_settings(db_session, user.id).next_invest_at is None


def test_a_tick_another_process_holds_does_nothing(scheduler, scheduler_lock, db_session, fake_kraken, account, now):
    due = now - MINUTE
    user = account(next_rebalance_at=due)
    scheduler_lock.held = True

    assert scheduler.tick(now) == TickReport(ran=False)
    assert fake_kraken.calls == []
    assert get_settings(db_session, user.id).next_rebalance_at == due


def test_the_batch_is_bounded_and_the_most_overdue_goes_first(app_context, db_session, account, now):
    scheduler = Scheduler(_with(app_context, batch=1))
    late = account(next_rebalance_at=now - timedelta(hours=1))
    recent = account(next_rebalance_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report.users == 1
    assert len(list_evaluations(db_session, late.id)) == 1
    assert list_evaluations(db_session, recent.id) == []


def test_one_ticker_call_serves_the_whole_batch(scheduler, fake_kraken, account, now):
    account(next_rebalance_at=now - 2 * MINUTE)
    account(next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert fake_kraken.calls.count("Balance") == 2
    assert fake_kraken.calls.count("Ticker") == 1
    assert fake_kraken.calls.count("AssetPairs") == 1


def test_retention_runs_on_the_first_tick_of_each_day(scheduler, db_session, make_user, now):
    user = make_user()
    start_evaluation(db_session, user.id, started_at=now - timedelta(days=400))

    assert scheduler.tick(now).swept is True
    assert list_evaluations(db_session, user.id) == []
    assert scheduler.tick(now + timedelta(hours=1)).swept is False
    assert scheduler.tick(now + timedelta(days=1)).swept is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command with `tests/integration/test_scheduler.py tests/integration/test_locks.py tests/integration/test_settings.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.scheduler'`, and
`ImportError` for `advisory_scheduler_lock` and `pairs_for`.

- [ ] **Step 3: The lock**

Append to `core/db/locks.py`:

```python
# The scheduler's tick, across processes. Two 32-bit keys: PostgreSQL keeps that key space
# apart from the single 64-bit keys the user locks take, so the two never collide.
SCHEDULER_LOCK = (0x636F696E, 1)


@contextmanager
def advisory_scheduler_lock(engine: Engine, key: tuple[int, int] = SCHEDULER_LOCK) -> Iterator[bool]:
    """Yields whether this process may run the tick. It never waits: a second process,
    or a second worker of the same one, skips the tick instead of queueing for it."""
    first, second = key
    with engine.connect() as connection:
        taken = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:first, :second)"), {"first": first, "second": second}
            ).scalar_one()
        )
        connection.commit()
        try:
            yield taken
        finally:
            if taken:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:first, :second)"), {"first": first, "second": second}
                )
                connection.commit()
```

- [ ] **Step 4: The pairs of a batch**

Append to `core/db/settings.py` (add `from collections.abc import Collection`):

```python
def pairs_for(session: Session, user_ids: Collection[uuid.UUID]) -> set[str]:
    """The pairs these users are configured with: what a tick reads prices for, in one call."""
    if not user_ids:
        return set()
    stmt = select(AssetConfig.pair).where(AssetConfig.user_id.in_(user_ids)).distinct()
    return set(session.execute(stmt).scalars())
```

Add `pairs_for` to `core/database.py`'s import from `core.db.settings` and to `__all__`.

- [ ] **Step 5: The context**

In `api/context.py`, add a field to `AppContext`, after `user_lock`:

```python
    # One scheduler tick at a time, across processes. Yields whether it was taken.
    scheduler_lock: Callable[[], AbstractContextManager[bool]]
```

In `api/main.py`, import `advisory_scheduler_lock` beside `advisory_user_lock`, and add
to the `AppContext(...)` call, after `user_lock=...`:

```python
        scheduler_lock=partial(advisory_scheduler_lock, get_engine()),
```

In `tests/integration/conftest.py`, after `FakeLocks` and its fixture:

```python
class FakeSchedulerLock:
    """The tick lock, without a second connection. `held` stands for another process
    running the tick."""

    def __init__(self):
        self.held = False

    @contextmanager
    def __call__(self):
        if self.held:
            yield False
            return
        self.held = True
        try:
            yield True
        finally:
            self.held = False


@pytest.fixture
def scheduler_lock() -> FakeSchedulerLock:
    return FakeSchedulerLock()
```

Give `app_context` the parameter `scheduler_lock: FakeSchedulerLock` and pass
`scheduler_lock=scheduler_lock,` to `AppContext(...)`, after `user_lock=user_locks,`.

`tests/unit/api/test_database_errors.py` builds an `AppContext` too: add
`scheduler_lock=lambda: nullcontext(False),` after its `user_lock=...` line.

- [ ] **Step 6: The scheduler**

Create `core/scheduler.py`:

```python
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

# What counts towards a failure streak. `UNRESOLVED` is a wait, and `PARTIAL` is Kraken
# refusing an order: neither is the system failing. An operation that raises counts too.
FAILURES = frozenset({EvaluationStatus.ERROR, EvaluationStatus.KRAKEN_UNAVAILABLE})


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
            failed = result.status in FAILURES
        self._advance(context, user_id, prefix, now)
        self._count(context, user_id, failed=failed)

    def _run(self, context: _TickContext, user_id: uuid.UUID, prefix: str, automatic: bool) -> EvaluationResult:
        if prefix == INVEST:
            return invest(context, user_id, trigger=Trigger.SCHEDULER)
        if automatic:
            return rebalance_now(context, user_id)
        return propose(context, user_id, trigger=Trigger.SCHEDULER).evaluation

    def _advance(self, context: _TickContext, user_id: uuid.UUID, prefix: str, now: datetime) -> None:
        """Forward to the first slot after `now`: a missed run is not caught up (spec §10.2)."""
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
            db.update_settings(session, user_id, **{f"next_{prefix}_at": next_run(settings, prefix, now, self._config)})

    def _count(self, context: _TickContext, user_id: uuid.UUID, *, failed: bool) -> None:
        """Edge-triggered (spec §10.5): one warning when the streak reaches the threshold,
        one note when a user past it recovers, never one per failure."""
        threshold = self._config.alert_streak
        with context.sessions() as session:
            before = db.get_settings(session, user_id).failure_streak
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
```

`start`, `stop` and `run`, which use `_stop` and `_thread`, come in Task 8 with the
backfill on start-up.

- [ ] **Step 7: Run the tests**

Run: the test command.
Expected: PASS, every test.

- [ ] **Step 8: Commit**

```bash
git add core/scheduler.py core/db/locks.py core/db/settings.py core/database.py api/context.py api/main.py tests/integration/conftest.py tests/unit/api/test_database_errors.py tests/integration/test_scheduler.py tests/integration/test_locks.py tests/integration/test_settings.py
git commit -m "feat(scheduler): a tick evaluates the users due, one failure never stopping the next"
```

---

### Task 8: The thread, and the application that starts it

**Files:**
- Modify: `core/scheduler.py`, `api/app.py`, `api/main.py`
- Test: `tests/integration/test_scheduler.py`

**Interfaces:**
- Consumes: Task 6's `backfill`; Task 7's `Scheduler`.
- Produces: `Scheduler.start() -> None`, `Scheduler.stop() -> None`,
  `Scheduler.run() -> None`, `Scheduler.running: bool`; `app.state.scheduler`
  (`Scheduler | None`) while the application runs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_scheduler.py` (add
`from fastapi.testclient import TestClient` and `from api.app import create_app`):

```python
def test_a_tick_that_raises_does_not_end_the_loop(app_context, monkeypatch):
    scheduler = Scheduler(_with(app_context, tick=timedelta(0)))
    calls = []

    def tick(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        scheduler.stop()

    monkeypatch.setattr(scheduler, "tick", tick)

    scheduler.run()

    assert len(calls) == 2


def test_the_application_starts_and_stops_the_scheduler(app_context, scheduler_lock):
    # Every tick finds the tick taken, so the thread touches nothing while the test runs.
    scheduler_lock.held = True
    app = create_app(_with(app_context, enabled=True, tick=timedelta(hours=1)))

    with TestClient(app):
        scheduler = app.state.scheduler
        assert scheduler.running

    assert not scheduler.running


def test_the_application_starts_no_scheduler_when_it_is_off(app_context):
    app = create_app(app_context)

    with TestClient(app):
        assert app.state.scheduler is None


def test_starting_fills_the_next_runs_that_are_missing(app_context, db_session, scheduler_lock, make_user, now):
    scheduler_lock.held = True
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    scheduler = Scheduler(_with(app_context, tick=timedelta(hours=1)))

    scheduler.start()
    scheduler.stop()

    assert get_settings(db_session, user.id).next_rebalance_at > now
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command with `tests/integration/test_scheduler.py`
Expected: FAIL — `Scheduler` has no `run`, `start` or `stop`, and `app.state` has no
`scheduler`.

- [ ] **Step 3: The loop**

Add `backfill` to the import from `core.schedule` in `core/scheduler.py`, and add to
`Scheduler`, after `__init__`:

```python
    def start(self) -> None:
        """Fill any missing next run, then tick on a thread of its own until `stop`."""
        with self._context.sessions() as session:
            filled = backfill(session, self._context.now(), self._config)
        if filled:
            logger.info("scheduled %d users that had no next run", filled)
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="coinpilot-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """End the loop and wait for it. A tick under way finishes first: cutting an
        evaluation short between an order and its answer is what §9.2 guards against, and
        there is no reason to cause one."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        """Tick, wait, repeat until `stop`. A tick that raises is logged, and the loop goes on."""
        while not self._stop.is_set():
            try:
                self.tick(self._context.now())
            except Exception:
                logger.exception("a scheduler tick failed")
            self._stop.wait(self._config.tick.total_seconds())
```

- [ ] **Step 4: The lifespan**

In `api/app.py`, add the imports:

```python
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.scheduler import Scheduler
```

Add before `create_app`:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The scheduler lives as long as the application: one process, both jobs (spec §4.1)."""
    context: AppContext = app.state.context
    scheduler = Scheduler(context) if context.config.scheduler.enabled else None
    app.state.scheduler = scheduler
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            # Off the event loop: stopping waits for a tick under way.
            await asyncio.to_thread(scheduler.stop)
```

In `create_app`, replace `app = FastAPI(title="CoinPilot", version="0.1.0")` with:

```python
    app = FastAPI(title="CoinPilot", version="0.1.0", lifespan=_lifespan)
```

- [ ] **Step 5: The log reaches the console**

In `api/main.py`, add `import logging`, and before `build`:

```python
def _log_to_stderr() -> None:
    """`coinpilot.*` at INFO, so the scheduler's alerts and recoveries are seen. Uvicorn
    configures only its own loggers."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("coinpilot")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
```

and call `_log_to_stderr()` as the first line of `build`.

- [ ] **Step 6: Run the tests**

Run: the test command.
Expected: PASS, every test.

- [ ] **Step 7: Commit**

```bash
git add core/scheduler.py api/app.py api/main.py tests/integration/test_scheduler.py
git commit -m "feat(scheduler): the application starts the scheduler's thread and stops it cleanly"
```

---

### Task 9: The spec, the README, and the phase gate

**Files:**
- Modify: `docs/specs/2026-09-17-platform-design.md` (§3.5, §4.1, §6, §8, §10.1, §10.5, §14)
- Modify: `README.md`

- [ ] **Step 1: Spec §3.5**

After the paragraph that ends `§10.2 covers how it coexists with staggering.`, insert:

```markdown
The anchor is an instant, stored in UTC. A user who means 09:00 where clocks change for
summer runs an hour apart in summer and in winter. The stagger already spreads a run over
an hour; a time zone per user is deferred.
```

Replace:

```markdown
If both cadences fall due on the same tick, there is one balance read and two
operations: the invest operation executes, and the rebalance operation is proposed or
executed according to the switch.
```

with:

```markdown
If both cadences fall due on the same tick, there are two evaluations, the invest
operation first: it executes, and the rebalance operation then reads the balance it left
and is proposed or executed according to the switch. One shared read would plan the
rebalance on a balance the investment had already changed.
```

- [ ] **Step 2: Spec §4.1**

Replace `| `platform` | FastAPI + APScheduler: engine, REST API and scheduler in one process |`
with `| `platform` | FastAPI and a scheduler thread: engine, REST API and scheduler in one process |`.

Replace `**Language and stack: Python 3.13**, with FastAPI, SQLAlchemy, Alembic and APScheduler.`
with `**Language and stack: Python 3.13**, with FastAPI, SQLAlchemy and Alembic.`

- [ ] **Step 3: Spec §6**

In the table, replace the three rows:

```markdown
| `user_settings` | One row per user: `fiat`, `invest_cash_enabled`, `cash_rebalance_enabled`, `auto_rebalance_enabled`, `min_drift_pct`, `min_order_fiat`, both cadences, `next_invest_at`, `next_rebalance_at`, `paused`. |
```

```markdown
| `user_settings` | One row per user: `fiat`, `invest_cash_enabled`, `cash_rebalance_enabled`, `auto_rebalance_enabled`, `min_drift_pct`, `min_order_fiat`, both cadences, `next_invest_at`, `next_rebalance_at`, `paused`, `failure_streak`. |
```

```markdown
| `portfolio_snapshots` | Time series of portfolio value. |
```

```markdown
| `portfolio_snapshots` | Time series of portfolio value: one point a day, overwritten by each read of that day, and one kept (`pinned`) before every operation that sent orders. |
```

```markdown
| `sessions` | One row per user evaluation: status, duration, captured log lines. |
```

```markdown
| `sessions` | One row per user evaluation: what it was for (`operation`), who started it (`trigger`), status, duration, captured log lines. |
```

- [ ] **Step 4: Spec §8**

Replace:

```markdown
A proposal always represents a **rebalance operation**. Invest operations never produce
one, and neither does a rebalance while automatic rebalancing is enabled: that executes
directly.
```

with:

```markdown
A proposal always represents a **rebalance operation**. Invest operations never produce
one, and neither does a rebalance while automatic rebalancing is enabled: that executes
directly, and withdraws a live proposal first, since what executes is today's plan.
```

- [ ] **Step 5: Spec §10.1 and §10.5**

After the paragraph that ends `those calls do not contend.`, insert:

```markdown
A tick reads the prices of every pair its batch is configured with in one `Ticker` call,
and a pair it missed — an unmanaged holding — once more, kept for the rest of the tick.
Asset names and pairs come from the daily catalog, never from a call per evaluation:
every public call in the process shares one bucket.
```

After the paragraph that ends `never one per failure.`, insert:

```markdown
A failure is a scheduled operation that ends `ERROR` or `KRAKEN_UNAVAILABLE`, or raises.
An unresolved order is a wait and a refused order is Kraken's answer; neither counts, and
a user without a key yet is skipped without counting. The streak is
`user_settings.failure_streak`, so a restart does not reset it. The alert is a log line
until project 2 brings notifications.
```

- [ ] **Step 6: Spec §14**

After the bullet that begins `- **Cadence is the load regulator`, insert:

```markdown
- **A thread, not APScheduler.** The scheduler is one job every 60 seconds. A loop around
  an event's wait does that, and the tick is a plain method a test calls with a fixed
  clock. A scheduling library would add a dependency and a job store for nothing used.
```

- [ ] **Step 7: README**

In `README.md`, replace:

```markdown
> **Status: in development.** Phase 6 of 8: free cash is invested on request with
> `POST /invest`, and a rebalance is proposed with `POST /rebalance` and executed once
> approved with `POST /proposal/approve`. Nothing runs on its own yet.
```

with:

```markdown
> **Status: in development.** Phase 7 of 8: free cash is invested, and drift is looked
> for, on each user's cadence. A rebalance found by the scheduler is proposed, or
> executed when the user turned automatic rebalancing on. Everything also runs on
> request: `POST /invest`, `POST /rebalance`, `POST /proposal/approve`.
```

- [ ] **Step 8: Run the whole gate**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests --cov-fail-under=80
```

Expected: each passes.

- [ ] **Step 9: Commit**

```bash
git add docs/specs/2026-09-17-platform-design.md README.md
git commit -m "docs: the spec describes the scheduler as built; the README describes phase 7"
```

---

## What you verify before phase 8

Phase 7 is the first phase that acts without a request. Start where it cannot spend.

### 1. Start from a state that cannot spend

1. Apply the migration:

   ```bash
   DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. .venv/Scripts/alembic upgrade head
   ```

2. Before restarting, make sure nothing can be sent: `PATCH /config` with
   `{"invest_cash_enabled": false, "auto_rebalance_enabled": false}`. The rebalance
   cadence stays `MIN`.
3. Restart the API. The log shows `retention removed …`, and possibly
   `scheduled 1 users that had no next run`.
4. `GET /config`: `next_rebalance_at` is set, within the next 15 minutes;
   `next_invest_at` is `null`.

### 2. Leave it running

Leave it a few hours. Then:

- `GET /sessions`: one row every 15 minutes with `operation` `PROPOSE` and `trigger`
  `SCHEDULER`, always at the same minute and second within the quarter hour — your
  offset.
- `GET /proposal`: if your drift is above `min_drift_pct`, a live proposal with `trigger`
  `SCHEDULED`; otherwise `404`. Either way, Kraken's order history is unchanged.
- The snapshots:

  ```bash
  docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "select as_of::date, pinned, count(*) from portfolio_snapshots group by 1, 2 order by 1"
  ```

  Today has one unpinned row, however many evaluations ran.

### 3. A daily investment (optional)

`PATCH /config` with `{"invest_cash_enabled": true, "invest_cadence_mode": "INTERVAL",
"invest_interval_days": 1, "invest_cadence_anchor": "<tomorrow>T07:00:00Z"}`.
`next_invest_at` is that time plus up to an hour. When it comes, `GET /sessions` shows an
`INVEST` / `SCHEDULER` row, and the snapshot of that evaluation is pinned if it sent
orders. Keep free cash small.

### 4. Report

Report what the three checks showed. Anything that differs goes into the departures
below and, where it is a fact about the platform, into the spec.

---

## Departures taken during execution

The code blocks above are the plan as written. Where the repository differs, trust the
repository.

| Where | What changed | Why |
|---|---|---|
| Task 7, `rebalance_now` | Re-reads `auto_rebalance_enabled` under the user lock before any order and sends nothing (`NOTHING_TO_DO`) if it is off. | The switch may have been turned off since the evaluation was scheduled. |
| Task 7, failure streak | A failed PENDING lookup counts toward the failure streak, via `EvaluationResult.lookup_failed`. | Spec §9.2 is binding; an order merely not listed yet still does not count. |
| Task 3, `record_snapshot` | It did not gain a `pinned` parameter; pinning goes only through `pin_snapshot`. | One way to pin keeps the one-point-a-day rule in one place. |
| Task 9, README | The stack line drops APScheduler. | APScheduler is not used. |
