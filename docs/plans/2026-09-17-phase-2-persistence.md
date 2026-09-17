# Phase 2 — Persistence

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the schema that holds every tenant's state, the migrations that create it,
and the data access layer over a real PostgreSQL — with no user able to read or write
another user's rows.

**Architecture:** Eight tables, every one keyed by `user_id`. The data access layer is
split by domain under `core/db/`, and `core/database.py` is the facade that re-exports it.
Every DAL function takes an open `Session` as its first argument, so a caller decides the
transaction boundary and a test can roll one back. Nothing in this phase talks to Kraken,
holds a credential in plain text, or places an order.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, Alembic, psycopg 3, PostgreSQL 18, pytest.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.5, §5.2, §5.3, §6, §9.2, §10.1, §10.2, §12

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 2 of 8

## Global Constraints

- **Python 3.13.** `requires-python = ">=3.13"`. One version, not a range.
- **Money is `Decimal`, never `float`.** Every amount, price, weight and percentage is
  `decimal.Decimal`. A `float` in a monetary path is a defect.
- **Pin every dependency with `==`.** Resolve the exact version before adding one.
- **No test reads configuration from the environment.** See the refinement below — it is
  not the same as "no test may know where the database is".
- **Coverage gate is 80 %.**
- **`ruff check` and `ruff format --check` must pass.**
- **Percentages are 0–100, not 0–1.** `target_pct = Decimal("60")` means sixty percent.
- **Every table carries `user_id`. There are no singleton rows.**
- **`min_drift_pct` is `Numeric(4,1)`; `min_order_fiat` is `Numeric(10,1)`.**
- Commit messages follow Conventional Commits.

### The environment rule, refined

The rule bans **the code under test** from reading ambient settings, because such a test
passes on a machine holding a local `.env` and fails in CI as a mystery.

It does not ban a **fixture** from knowing which database to connect to. A database URL is
where the test runs, not an input to the behaviour being tested. The line is exact:

- A fixture reads `DATABASE_URL` and hands the resulting session to the test. **Allowed.**
- A DAL function reads `DATABASE_URL` for itself. **Forbidden** — that is why
  `core/db/session.py` takes the URL as an argument.
- A test asserts a default that came from the environment. **Forbidden** — state it.

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Pinned runtime dependencies |
| `.env.example` | The names of the settings, with no values that are secret |
| `docker-compose.dev.yml` | A local PostgreSQL for development and for the integration tests |
| `core/__init__.py` | Marks the package; exports nothing |
| `core/config.py` | The one module that reads the process environment |
| `core/db/__init__.py` | Marks the package; exports nothing |
| `core/db/types.py` | Column type aliases and the enumerations stored as strings |
| `core/db/models.py` | The declarative `Base` and the eight tables |
| `core/db/session.py` | Engine construction, the session factory and `session_scope` |
| `core/db/users.py` | `users` and `user_credentials` |
| `core/db/settings.py` | `user_settings` and `asset_config`, and the scheduler's due query |
| `core/db/orders.py` | `orders`, including the unresolved-attempt gate |
| `core/db/proposals.py` | `proposal` |
| `core/db/telemetry.py` | `portfolio_snapshots` and `sessions`, and session retention |
| `core/database.py` | The facade: re-exports every DAL function and `session_scope` |
| `alembic.ini` | Points Alembic at `scripts/migrations/` |
| `scripts/migrations/env.py` | Alembic environment; reads the URL from the process |
| `scripts/migrations/versions/` | The migrations themselves |
| `tests/integration/conftest.py` | The engine, the schema and the rolled-back session |
| `tests/integration/test_schema.py` | The migration applies from empty and the schema is right |
| `tests/integration/test_users.py` | Identity and credential storage |
| `tests/integration/test_settings.py` | Settings, assets and the due query |
| `tests/integration/test_orders.py` | The order ledger and the pending gate |
| `tests/integration/test_proposals.py` | The single live proposal per user |
| `tests/integration/test_telemetry.py` | Snapshots, evaluation sessions and retention |
| `tests/integration/test_tenant_isolation.py` | Its own category, per spec §12 |

The split is by domain, not by layer. A table and the queries over it change together, so
they live together. `core/database.py` exists so that a caller writes
`db.get_settings(session, user_id)` without needing to know which module owns it.

---

## What this phase deliberately leaves out

The spec asks for things that belong to a later phase, and leaving them out here is a
decision rather than an omission:

- **Encryption.** §5.3 owns the cipher and the master key. This phase stores opaque bytes
  and never learns what they mean, which is what lets the storage be tested with no
  master key anywhere near it. Phase 4 adds the cipher, and what it must put inside the
  ciphertext is already decided: `{"key": ..., "secret": ...}` encoded UTF-8, one payload
  under one nonce.
- **The credential tests of §12** — ciphertext differs from plaintext, no response schema
  carries a credential, no log line holds a secret. There is no cipher, no schema and no
  log here yet. What this phase can test, it does: the bytes go in and come back
  unchanged, and no user can read another user's record.
- **Cadence arithmetic and staggering** (§10.2). This phase stores `next_invest_at` and
  `next_rebalance_at`; phase 7 computes them.
- **Validating that target weights sum to 100 or less** (§3.1). The spec puts that in the
  application layer on purpose, so it is not a table constraint and not a DAL rule.

---

## Why the DAL takes a `Session` argument

A function that opens its own session cannot participate in a transaction with the next
one. This system needs that: recording an order attempt and marking a proposal as
executing belong to one unit of work.

It also makes every test cheap. The fixture opens one transaction, hands the session to
the test, and rolls back at the end. No test cleans up after itself, and no test can leak
a row into the next one.

---

### Task 1: A real database, reachable from a test

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `docker-compose.dev.yml`
- Create: `core/__init__.py`
- Create: `core/config.py`
- Create: `core/db/__init__.py`
- Create: `core/db/session.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_connection.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing from phase 1
- Produces:
  - `core.config.database_url() -> str` — raises `RuntimeError` when unset
  - `core.db.session.create_engine_from_url(url: str) -> Engine`
  - `core.db.session.configure(url: str) -> None`
  - `core.db.session.get_engine() -> Engine`
  - `core.db.session.session_scope() -> Iterator[Session]` — a context manager that
    commits on success and rolls back on an exception
  - a `db_session` pytest fixture that yields a `Session` inside a transaction which is
    always rolled back

- [ ] **Step 1: Write `requirements.txt`**

```
SQLAlchemy==2.0.54
alembic==1.20.0
psycopg[binary]==3.3.5
```

- [ ] **Step 2: Write `.env.example`**

This file is committed on purpose: `.gitignore` excludes `.env.*` but keeps
`!.env.example`. It names the settings and carries no value that is secret.

```
# The database the platform connects to.
DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot

# Set to true to run the integration tests. They need the database above.
RUN_DB_INTEGRATION=false
```

- [ ] **Step 3: Write `docker-compose.dev.yml`**

```yaml
# A PostgreSQL for development and for the integration tests. It holds no production
# data, so the credentials below are deliberately trivial and are not secret.
services:
  postgres:
    image: postgres:18.6
    environment:
      POSTGRES_USER: coinpilot
      POSTGRES_PASSWORD: coinpilot
      POSTGRES_DB: coinpilot
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U coinpilot"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

- [ ] **Step 4: Write `core/config.py`**

`core/__init__.py` and `core/db/__init__.py` are empty files.

This is the only module in the system that reads the process environment. Everything else
receives what it needs as an argument.

```python
"""The one module that reads the process environment.

Every other module receives what it needs as an argument. That is what lets a test state
its inputs instead of inheriting them from the machine it runs on.
"""

from __future__ import annotations

import os


def database_url() -> str:
    """The database the platform connects to.

    Raises rather than defaulting. A silent default would point a production process at a
    local database, and the failure would look like an empty account.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url
```

- [ ] **Step 5: Write `core/db/session.py`**

```python
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


def create_engine_from_url(url: str) -> Engine:
    """Build an engine.

    `pool_pre_ping` costs one round trip and survives a dropped connection, which a
    long-lived scheduler process will meet.
    """
    return create_engine(url, pool_pre_ping=True, future=True)


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
```

- [ ] **Step 6: Write the test fixture**

`tests/integration/__init__.py` is an empty file.

`tests/integration/conftest.py`:

```python
"""Fixtures for the tests that need a real PostgreSQL.

Every one of them is skipped unless RUN_DB_INTEGRATION is true, so a developer with no
database still runs the unit suite.

Reading DATABASE_URL here is deliberate, and it is not what the global rule forbids: it
says where the test runs, not what the code under test is given.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from core.db.session import create_engine_from_url


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
```

- [ ] **Step 7: Write the failing test**

`tests/integration/test_connection.py`:

```python
from sqlalchemy import text
from sqlalchemy.orm import Session


def test_the_session_reaches_a_real_database(db_session: Session):
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1


def test_the_database_is_postgresql(db_session: Session):
    """The schema uses JSONB and partial indexes, so the backend is not interchangeable."""
    version = db_session.execute(text("SELECT version()")).scalar_one()

    assert "PostgreSQL" in version
```

- [ ] **Step 8: Run it with no database to verify it skips**

Run: `PYTHONPATH=. pytest tests/integration -v --no-cov`

Expected: 2 skipped, with the reason `RUN_DB_INTEGRATION is not true`.

A skip here is the correct outcome, not a pass to celebrate. Step 10 is where the test
must really run.

- [ ] **Step 9: Start the database**

```bash
docker compose -f docker-compose.dev.yml up -d
```

Then confirm it is ready:

```bash
docker compose -f docker-compose.dev.yml ps
```

Expected: the `postgres` service reports `running (healthy)`.

- [ ] **Step 10: Run the test against the real database**

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration -v --no-cov
```

Expected: 2 passed.

- [ ] **Step 11: Move the coverage gate out of `addopts`**

`pyproject.toml` currently fails any run that does not cover 80 % of the measured source.
That was right when `engine` was the only package and every test ran everywhere. It is
wrong now: a developer running only `tests/unit` would fail the gate on `core/db`, which
is covered by the tests they deliberately skipped.

The gate moves to the CI command, where the whole suite really runs.

Replace the `[tool.pytest.ini_options]` and `[tool.coverage.run]` blocks with:

```toml
[tool.pytest.ini_options]
minversion = "9.0"
testpaths = ["tests"]
addopts = "-ra --strict-markers --cov --cov-report=term-missing"
markers = [
    "unit: Unit tests with no network and no database.",
    "integration: Tests that need a real PostgreSQL.",
]

[tool.coverage.run]
source = ["engine", "core"]
```

- [ ] **Step 12: Give CI a database**

Replace the whole `jobs:` block of `.github/workflows/ci.yml` with:

```yaml
jobs:
  test:
    name: Lint and tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:18.6
        env:
          POSTGRES_USER: coinpilot
          POSTGRES_PASSWORD: coinpilot
          POSTGRES_DB: coinpilot
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U coinpilot"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      DATABASE_URL: postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot
      RUN_DB_INTEGRATION: "true"
      PYTHONPATH: .

    steps:
      - name: Checkout
        uses: actions/checkout@v6.0.2

      - name: Set up Python
        uses: actions/setup-python@v6.0.0
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: ruff check
        run: ruff check .

      - name: ruff format --check
        run: ruff format --check .

      - name: Tests
        run: pytest tests --cov-fail-under=80
```

The integration tests now really run in CI. A `skipped` result there would mean the gate
measures nothing, which is worse than a failure because it still looks green.

- [ ] **Step 13: Run lint and the whole suite**

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests --cov-fail-under=80
```

Expected: 36 passed — the 34 from phase 1 plus the 2 here.

- [ ] **Step 14: Commit**

```bash
git add requirements.txt .env.example docker-compose.dev.yml core tests/integration pyproject.toml .github/workflows/ci.yml
git commit -m "feat(db): a real PostgreSQL, reachable from a rolled-back test session"
```

---

### Task 2: The eight tables and the migration that creates them

**Files:**
- Create: `core/db/types.py`
- Create: `core/db/models.py`
- Create: `alembic.ini`
- Create: `scripts/migrations/env.py`
- Create: `scripts/migrations/versions/<generated>_initial_schema.py`
- Create: `tests/integration/test_schema.py`
- Modify: `tests/integration/conftest.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `engine.types.Side`, `core.db.session.create_engine_from_url`
- Produces:
  - `core.db.types` — `AMOUNT`, `PERCENT`, `DRIFT_PCT`, `ORDER_FIAT`, and the
    enumerations `UserStatus`, `CadenceMode`, `OrderReason`, `OrderStatus`,
    `ProposalStatus`, `ProposalTrigger`, plus `enum_check(column, values, name)`
  - `core.db.models` — `Base`, `User`, `UserCredentials`, `UserSettings`, `AssetConfig`,
    `Order`, `Proposal`, `PortfolioSnapshot`, `EvaluationSession`

**Rules this implements** (spec §5.3, §6, §9.2, §10.1):
- Every table carries `user_id`. There are no singleton rows.
- `users.id` is a UUID so a row count is not leaked.
- The key and the secret share one ciphertext under one nonce.
- The scheduler's due query is indexed, per §10.1.
- Resolving unresolved attempts is indexed, per §9.2.

- [ ] **Step 1: Write `core/db/types.py`**

```python
"""Column types, and the enumerations that are stored as short strings.

An enumeration is a string with a check constraint, not a PostgreSQL `ENUM` type. Adding
a value to a native enum is a migration with awkward transaction rules; a check
constraint is one `ALTER` and it reads plainly in `psql`.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Numeric

# Twelve decimal places cover the largest lot precision Kraken publishes, with room to
# spare. Twelve integer digits cover any portfolio this system will hold.
AMOUNT = Numeric(24, 12)

# A target weight, 0.00 to 100.00.
PERCENT = Numeric(5, 2)

# Both pinned by the spec.
DRIFT_PCT = Numeric(4, 1)
ORDER_FIAT = Numeric(10, 1)


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CadenceMode(StrEnum):
    """`MIN` is the system minimum cadence. `INTERVAL` uses the days, months and anchor."""

    MIN = "MIN"
    INTERVAL = "INTERVAL"


class OrderReason(StrEnum):
    """Which operation asked for the order. Approval is decided per operation, not per order."""

    INVEST = "INVEST"
    REBALANCE = "REBALANCE"


class OrderStatus(StrEnum):
    """`PENDING` is written before `AddOrder` is called and means the outcome is unknown."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    FAILED = "FAILED"


class ProposalStatus(StrEnum):
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    LIVE = "LIVE"
    WITHDRAWN = "WITHDRAWN"


class ProposalTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


def enum_check(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    """A check constraint listing exactly the members of `values`.

    Building the constraint from the enumeration is what keeps the two from drifting: a
    member added in Python changes the generated DDL, and the migration that follows
    carries it.
    """
    listed = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({listed})", name=name)
```

- [ ] **Step 2: Write `core/db/models.py`**

```python
"""The eight tables.

Every one of them carries `user_id`. There are no singleton rows, and no table holds
state that belongs to the system rather than to a tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.db.types import (
    AMOUNT,
    DRIFT_PCT,
    ORDER_FIAT,
    PERCENT,
    CadenceMode,
    OrderReason,
    OrderStatus,
    ProposalStatus,
    ProposalTrigger,
    UserStatus,
    enum_check,
)
from engine.types import Side


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    """An OAuth identity. The key is a UUID so that a row count is not leaked."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # Not unique: two providers can return the same address, and that is one person with
    # two identities until something links them.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE)

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_users_provider_subject"),
        enum_check("status", UserStatus, "ck_users_status"),
    )


class UserCredentials(TimestampMixin, Base):
    """The Kraken key and secret, encrypted together under one nonce.

    One ciphertext, not two, is deliberate. Two payloads under the same master key need
    two nonces, and a reused nonce breaks AES-GCM completely. One payload makes that
    mistake impossible rather than merely discouraged.

    Inside the ciphertext is `{"key": ..., "secret": ...}` encoded UTF-8, per the spec's
    §5.3. This table never sees that structure: it stores bytes and phase 4 owns the
    cipher.
    """

    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSettings(TimestampMixin, Base):
    """One row per user. `fiat` is immutable for now."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)

    invest_cash_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # True selects the engine's REDUCE_DRIFT cash policy; false selects PRORATA.
    cash_rebalance_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_rebalance_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    min_drift_pct: Mapped[Decimal] = mapped_column(DRIFT_PCT, nullable=False, default=Decimal("0"))
    min_order_fiat: Mapped[Decimal] = mapped_column(ORDER_FIAT, nullable=False, default=Decimal("0"))

    invest_cadence_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CadenceMode.MIN
    )
    invest_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invest_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invest_cadence_anchor: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rebalance_cadence_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CadenceMode.MIN
    )
    rebalance_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebalance_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebalance_cadence_anchor: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    next_invest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_rebalance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # One indexed query per tick, per §10.1. The partial predicate keeps a paused user out
    # of the index entirely rather than out of the result.
    __table_args__ = (
        enum_check("invest_cadence_mode", CadenceMode, "ck_user_settings_invest_cadence_mode"),
        enum_check(
            "rebalance_cadence_mode", CadenceMode, "ck_user_settings_rebalance_cadence_mode"
        ),
        Index(
            "ix_user_settings_next_invest_at",
            "next_invest_at",
            postgresql_where=text("paused = false"),
        ),
        Index(
            "ix_user_settings_next_rebalance_at",
            "next_rebalance_at",
            postgresql_where=text("paused = false"),
        ),
    )


class AssetConfig(TimestampMixin, Base):
    """One row per user and asset.

    A row with `target_pct = 0` says *exit this position*. No row at all says *this asset
    is not managed*. Two intentions, told apart by the presence of the row.
    """

    __tablename__ = "asset_config"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    target_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)

    # A per-row bound, not the sum rule. The spec puts "the weights sum to 100 or less" in
    # the application layer; this only says a single weight is a percentage.
    __table_args__ = (
        CheckConstraint("target_pct >= 0 AND target_pct <= 100", name="ck_asset_config_target_pct"),
    )


class Order(TimestampMixin, Base):
    """Every order attempted, written `PENDING` before `AddOrder` is called."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Unique across the whole table, not per user. Kraken requires uniqueness among open
    # orders, and a global rule is both stronger and simpler to reason about.
    cl_ord_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    txid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OrderStatus.PENDING)
    requested_fiat: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    executed_volume: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    executed_price: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)

    __table_args__ = (
        enum_check("side", Side, "ck_orders_side"),
        enum_check("reason", OrderReason, "ck_orders_reason"),
        enum_check("status", OrderStatus, "ck_orders_status"),
        Index("ix_orders_user_created_at", "user_id", "created_at"),
        # Every evaluation begins by asking whether this user has an unresolved attempt.
        # A partial index holds only the rows that answer yes, which is almost none.
        Index("ix_orders_user_pending", "user_id", postgresql_where=text("status = 'PENDING'")),
    )


class Proposal(TimestampMixin, Base):
    """At most one per user.

    Phase 6 owns the transitions between the statuses. This phase owns the row and the
    rule that there is only ever one.
    """

    __tablename__ = "proposal"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # JSONB, because the plan is read back as structure: to compare versions and to
    # execute. Text that is only ever fetched whole stays Text.
    plan: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ProposalStatus.LIVE)

    __table_args__ = (
        enum_check("trigger", ProposalTrigger, "ck_proposal_trigger"),
        enum_check("status", ProposalStatus, "ck_proposal_status"),
    )


class PortfolioSnapshot(Base):
    """A point in the value series. Rows are inserted and never updated."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    cash: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    # Holds the unmanaged assets too, each flagged, so the user sees their real account
    # rather than a partial view of it.
    holdings: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_portfolio_snapshots_user_as_of", "user_id", "as_of"),)


class EvaluationSession(Base):
    """One row per user evaluation, not per system tick.

    The class is not called `Session` because SQLAlchemy already owns that name in every
    module that touches the database.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # No check constraint, and that is the one deliberate exception. Telemetry gains
    # values over time, and a constraint here would make each one a migration while
    # protecting nothing that matters.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Text, not JSONB: fetched whole and never queried into.
    log_messages: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_sessions_user_started_at", "user_id", "started_at"),
        # Retention deletes across every user at once, so it needs the date on its own.
        Index("ix_sessions_started_at", "started_at"),
    )
```

- [ ] **Step 3: Initialise Alembic**

```bash
alembic init scripts/migrations
```

This writes `alembic.ini` at the repository root and a `scripts/migrations/` tree. Two of
the generated files are then replaced by the steps below; leave the rest untouched.

- [ ] **Step 4: Point `alembic.ini` at the right place and remove the URL**

In `alembic.ini`, set these two keys. The URL stays empty on purpose: it arrives from the
environment in `env.py`, so a connection string never sits in a committed file.

```ini
script_location = scripts/migrations
prepend_sys_path = .
sqlalchemy.url =
```

- [ ] **Step 5: Replace `scripts/migrations/env.py`**

```python
"""Alembic environment.

The URL arrives from the process environment through `core.config`, so the migrations and
the application agree on where the database is without a connection string living in a
committed file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import database_url
from core.db.models import Base

config = context.config

# A caller may set the URL itself — the test fixture does. Only fall back to the
# environment when nothing set one. The doubled percent signs escape configparser, which
# would otherwise read a percent in a password as an interpolation.
if not config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Generate the initial migration**

```bash
docker compose -f docker-compose.dev.yml up -d
DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. alembic revision --autogenerate -m "initial schema"
```

The migration is **generated, not written by hand**. A hand-written copy of the DDL is a
second description of the schema that drifts from the first one silently. The generated
file plus the assertions in step 9 are the safer contract: one description, and a test
that the database really carries it.

Open the generated file and confirm it creates eight tables. If it is empty, `env.py` did
not import `Base` — re-read step 5.

- [ ] **Step 7: Apply it, reverse it and apply it again**

```bash
export DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. alembic downgrade base
PYTHONPATH=. alembic upgrade head
```

Expected: three clean runs. The round trip is the real check — an upgrade that cannot be
reversed is a migration that cannot be rolled back in production either.

- [ ] **Step 8: Make the fixture build the schema**

Add to `tests/integration/conftest.py`, above the `engine` fixture:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config

_ROOT = Path(__file__).resolve().parents[2]


def _migrate(url: str) -> None:
    """Bring the test database to head. Running the real migrations rather than
    `create_all` means every test run also proves the migrations still apply."""
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "scripts" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
```

Then call it inside the `engine` fixture, immediately before `yield built`:

```python
    built = create_engine_from_url(url)
    _migrate(url)
    yield built
    built.dispose()
```

- [ ] **Step 9: Write the schema tests**

`tests/integration/test_schema.py`:

```python
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.types import UserStatus

EXPECTED_TABLES = frozenset(
    {
        "users",
        "user_credentials",
        "user_settings",
        "asset_config",
        "orders",
        "proposal",
        "portfolio_snapshots",
        "sessions",
    }
)


def test_the_migration_creates_every_table(db_session: Session):
    present = set(inspect(db_session.get_bind()).get_table_names())

    assert EXPECTED_TABLES <= present


def test_every_table_except_users_carries_a_user_id(db_session: Session):
    """The spec's first rule about the data model, asserted rather than trusted."""
    inspector = inspect(db_session.get_bind())

    for table in sorted(EXPECTED_TABLES - {"users"}):
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert "user_id" in columns, f"{table} has no user_id"


def test_the_scheduler_query_is_indexed(db_session: Session):
    """One indexed query per tick. Without these it is a sequential scan of every user."""
    names = {i["name"] for i in inspect(db_session.get_bind()).get_indexes("user_settings")}

    assert "ix_user_settings_next_invest_at" in names
    assert "ix_user_settings_next_rebalance_at" in names


def test_the_unresolved_attempt_lookup_is_indexed(db_session: Session):
    names = {i["name"] for i in inspect(db_session.get_bind()).get_indexes("orders")}

    assert "ix_orders_user_pending" in names


@pytest.mark.parametrize("status", [member.value for member in UserStatus])
def test_every_status_the_code_knows_is_accepted_by_the_database(db_session: Session, status: str):
    db_session.execute(
        text(
            "INSERT INTO users (id, provider, subject, email, status) "
            "VALUES (gen_random_uuid(), 'google', :subject, 'a@b.test', :status)"
        ),
        {"subject": f"subject-{status}", "status": status},
    )
    db_session.flush()


def test_a_status_the_code_does_not_know_is_refused(db_session: Session):
    """The enumeration and the check constraint must not drift apart."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO users (id, provider, subject, email, status) "
                "VALUES (gen_random_uuid(), 'google', 'drifted', 'a@b.test', 'NONSENSE')"
            )
        )
        db_session.flush()
```

- [ ] **Step 10: Run the schema tests**

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration -v --no-cov
```

Expected: 9 passed — the 2 from task 1, plus 7 here, where one is parametrised over the
two user statuses.

- [ ] **Step 11: Run lint and format**

```bash
ruff check . && ruff format .
```

`ruff format` without `--check` here: the models were typed to a width that the formatter
may join or split. Take whatever it produces, then confirm:

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 12: Commit**

```bash
git add core/db/types.py core/db/models.py alembic.ini scripts/migrations tests/integration
git commit -m "feat(db): the eight tables and the initial migration"
```

---

### Task 3: Identity and credential storage

**Files:**
- Create: `core/db/users.py`
- Create: `tests/integration/test_users.py`
- Modify: `tests/integration/conftest.py`

**Interfaces:**
- Consumes: `core.db.models.User`, `core.db.models.UserCredentials`, `core.db.types.UserStatus`
- Produces:
  - `create_user(session, provider, subject, email) -> User`
  - `get_user(session, user_id) -> User | None`
  - `get_user_by_identity(session, provider, subject) -> User | None`
  - `set_user_status(session, user_id, status) -> User | None`
  - `save_credentials(session, user_id, ciphertext, nonce, key_version, validated_at) -> UserCredentials`
  - `get_credentials(session, user_id) -> UserCredentials | None`
  - `delete_credentials(session, user_id) -> bool`
  - a `make_user` fixture that every later test file uses

- [ ] **Step 1: Add the user factory to the fixtures**

Append to `tests/integration/conftest.py`:

```python
from collections.abc import Callable

from core.db.models import User
from core.db.users import create_user


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    """Create a user with an identity nothing else will collide with.

    Every later test file builds its rows on top of this, because every table in the
    system needs a user before it can hold anything.
    """

    def _make(email: str = "someone@example.test") -> User:
        return create_user(
            db_session, provider="google", subject=str(uuid.uuid4()), email=email
        )

    return _make
```

Add `import uuid` to the imports at the top of the file.

- [ ] **Step 2: Write the failing tests**

`tests/integration/test_users.py`:

```python
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.types import UserStatus
from core.db.users import (
    create_user,
    delete_credentials,
    get_credentials,
    get_user,
    get_user_by_identity,
    save_credentials,
    set_user_status,
)

VALIDATED = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_a_new_user_gets_a_uuid_and_is_active(db_session: Session):
    user = create_user(db_session, provider="google", subject="s-1", email="a@b.test")

    assert isinstance(user.id, uuid.UUID)
    assert user.status == UserStatus.ACTIVE


def test_a_user_is_found_by_provider_and_subject(db_session: Session):
    created = create_user(db_session, provider="google", subject="s-2", email="a@b.test")

    assert get_user_by_identity(db_session, "google", "s-2").id == created.id


def test_the_same_subject_at_another_provider_is_another_person(db_session: Session):
    create_user(db_session, provider="google", subject="s-3", email="a@b.test")

    assert get_user_by_identity(db_session, "github", "s-3") is None


def test_two_identities_may_share_an_email(db_session: Session):
    """One human with two providers is two rows until something links them."""
    create_user(db_session, provider="google", subject="s-4", email="same@b.test")
    create_user(db_session, provider="github", subject="s-4", email="same@b.test")

    assert get_user_by_identity(db_session, "github", "s-4") is not None


def test_the_same_identity_twice_is_refused(db_session: Session):
    create_user(db_session, provider="google", subject="s-5", email="a@b.test")

    with pytest.raises(IntegrityError):
        create_user(db_session, provider="google", subject="s-5", email="other@b.test")


def test_an_unknown_user_id_returns_none(db_session: Session):
    assert get_user(db_session, uuid.uuid4()) is None


def test_a_user_can_be_disabled(db_session: Session, make_user):
    user = make_user()

    updated = set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert updated.status == UserStatus.DISABLED


def test_credentials_are_stored_and_read_back_unchanged(db_session: Session, make_user):
    user = make_user()

    save_credentials(
        db_session,
        user.id,
        ciphertext=b"\x01\x02opaque",
        nonce=b"\x03nonce",
        key_version=1,
        validated_at=VALIDATED,
    )

    stored = get_credentials(db_session, user.id)
    assert stored.ciphertext == b"\x01\x02opaque"
    assert stored.nonce == b"\x03nonce"
    assert stored.key_version == 1
    assert stored.validated_at == VALIDATED


def test_saving_again_replaces_rather_than_adding_a_second_record(db_session: Session, make_user):
    user = make_user()
    save_credentials(db_session, user.id, b"first", b"n1", 1, VALIDATED)

    save_credentials(db_session, user.id, b"second", b"n2", 2, VALIDATED)

    stored = get_credentials(db_session, user.id)
    assert stored.ciphertext == b"second"
    assert stored.key_version == 2


def test_deleting_credentials_says_whether_there_was_anything_to_delete(
    db_session: Session, make_user
):
    user = make_user()
    save_credentials(db_session, user.id, b"x", b"n", 1, VALIDATED)

    assert delete_credentials(db_session, user.id) is True
    assert delete_credentials(db_session, user.id) is False


def test_removing_a_user_removes_their_credentials(db_session: Session, make_user):
    """The cascade is what makes account deletion one statement instead of a checklist."""
    user = make_user()
    save_credentials(db_session, user.id, b"x", b"n", 1, VALIDATED)

    db_session.delete(get_user(db_session, user.id))
    db_session.flush()

    assert get_credentials(db_session, user.id) is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_users.py -v --no-cov
```

Expected: FAIL, `ModuleNotFoundError: No module named 'core.db.users'`

- [ ] **Step 4: Write `core/db/users.py`**

```python
"""Identity, and the record that holds the encrypted Kraken credentials.

Nothing here encrypts or decrypts anything. This layer stores opaque bytes and the phase
that owns the cipher decides what they mean. Keeping the two apart is what lets the
storage be tested with no master key anywhere near it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import User, UserCredentials
from core.db.types import UserStatus


def create_user(session: Session, provider: str, subject: str, email: str) -> User:
    user = User(provider=provider, subject=subject, email=email, status=UserStatus.ACTIVE)
    session.add(user)
    session.flush()
    return user


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def get_user_by_identity(session: Session, provider: str, subject: str) -> User | None:
    """The lookup the OAuth callback makes.

    On the provider and its subject, never on the email: an email can change hands and a
    subject cannot.
    """
    stmt = select(User).where(User.provider == provider, User.subject == subject)
    return session.execute(stmt).scalar_one_or_none()


def set_user_status(session: Session, user_id: uuid.UUID, status: UserStatus) -> User | None:
    user = session.get(User, user_id)
    if user is None:
        return None
    user.status = status
    session.flush()
    return user


def save_credentials(
    session: Session,
    user_id: uuid.UUID,
    ciphertext: bytes,
    nonce: bytes,
    key_version: int,
    validated_at: datetime,
) -> UserCredentials:
    """Insert or replace. There is one credential record per user, so this is an upsert."""
    record = session.get(UserCredentials, user_id)
    if record is None:
        record = UserCredentials(user_id=user_id)
        session.add(record)
    record.ciphertext = ciphertext
    record.nonce = nonce
    record.key_version = key_version
    record.validated_at = validated_at
    session.flush()
    return record


def get_credentials(session: Session, user_id: uuid.UUID) -> UserCredentials | None:
    return session.get(UserCredentials, user_id)


def delete_credentials(session: Session, user_id: uuid.UUID) -> bool:
    """True when a record was removed, false when there was none to remove."""
    record = session.get(UserCredentials, user_id)
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_users.py -v --no-cov
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add core/db/users.py tests/integration/test_users.py tests/integration/conftest.py
git commit -m "feat(db): identity and credential storage"
```

---

### Task 4: Settings, asset targets and the scheduler query

**Files:**
- Create: `core/db/settings.py`
- Create: `tests/integration/test_settings.py`

**Interfaces:**
- Consumes: `core.db.models.UserSettings`, `core.db.models.AssetConfig`
- Produces:
  - `DueUser(user_id: uuid.UUID, invest_due: bool, rebalance_due: bool)` — a frozen dataclass
  - `create_settings(session, user_id, fiat) -> UserSettings`
  - `get_settings(session, user_id) -> UserSettings | None`
  - `update_settings(session, user_id, **fields) -> UserSettings | None`
  - `due_users(session, now, limit) -> list[DueUser]`
  - `upsert_asset(session, user_id, asset, pair, target_pct) -> AssetConfig`
  - `list_assets(session, user_id) -> list[AssetConfig]`
  - `delete_asset(session, user_id, asset) -> bool`
  - `targets_for(session, user_id) -> dict[str, Decimal]`

**Rules this implements** (spec §3.1, §3.5, §10.1, §10.2):
- `fiat` is immutable for now, enforced by leaving it out of the updatable set.
- Which cadence is due decides whether the plan may contain sells, so `due_users` reports
  both flags rather than one.
- The batch is bounded. After an outage every user is overdue at once.
- `targets_for` returns exactly the mapping `engine.reconcile` takes for `targets`.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_settings.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from core.db.settings import (
    create_settings,
    delete_asset,
    due_users,
    get_settings,
    list_assets,
    targets_for,
    update_settings,
    upsert_asset,
)
from core.db.types import CadenceMode

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(minutes=30)
LATER = NOW + timedelta(minutes=30)


def test_a_new_settings_row_starts_with_the_stated_defaults(db_session: Session, make_user):
    settings = create_settings(db_session, make_user().id, fiat="EUR")

    assert settings.fiat == "EUR"
    assert settings.invest_cash_enabled is True
    assert settings.cash_rebalance_enabled is False
    assert settings.auto_rebalance_enabled is False
    assert settings.min_drift_pct == D("0")
    assert settings.min_order_fiat == D("0")
    assert settings.invest_cadence_mode == CadenceMode.MIN
    assert settings.rebalance_cadence_mode == CadenceMode.MIN
    assert settings.paused is False


def test_settings_for_an_unknown_user_are_none(db_session: Session):
    assert get_settings(db_session, uuid.uuid4()) is None


def test_a_setting_can_be_changed(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    update_settings(db_session, user.id, min_drift_pct=D("2.5"), auto_rebalance_enabled=True)

    settings = get_settings(db_session, user.id)
    assert settings.min_drift_pct == D("2.5")
    assert settings.auto_rebalance_enabled is True


def test_a_misspelled_field_is_refused_instead_of_silently_ignored(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(ValueError, match="min_drift"):
        update_settings(db_session, user.id, min_drift=D("2.5"))


def test_the_fiat_currency_cannot_be_changed(db_session: Session, make_user):
    """Immutable for now. Changing it would invalidate every stored pair and snapshot."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(ValueError, match="fiat"):
        update_settings(db_session, user.id, fiat="USD")


def test_a_user_whose_invest_time_has_passed_is_due(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, next_rebalance_at=LATER)

    due = due_users(db_session, NOW, limit=10)

    assert [d.user_id for d in due] == [user.id]
    assert due[0].invest_due is True
    assert due[0].rebalance_due is False


def test_a_user_due_for_both_reports_both(db_session: Session, make_user):
    """One balance read, two operations. The caller needs to know it is both."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, next_rebalance_at=EARLIER)

    due = due_users(db_session, NOW, limit=10)

    assert due[0].invest_due is True
    assert due[0].rebalance_due is True


def test_a_user_with_nothing_due_is_not_returned(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=LATER, next_rebalance_at=LATER)

    assert due_users(db_session, NOW, limit=10) == []


def test_a_paused_user_is_never_due(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, paused=True)

    assert due_users(db_session, NOW, limit=10) == []


def test_a_user_who_has_never_been_scheduled_is_not_due(db_session: Session, make_user):
    """Both times are null until something schedules them. Null is not overdue."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    assert due_users(db_session, NOW, limit=10) == []


def test_the_batch_is_bounded(db_session: Session, make_user):
    """After an outage every user is overdue at once. Without a cap that is a stampede."""
    for _ in range(3):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        update_settings(db_session, user.id, next_invest_at=EARLIER)

    assert len(due_users(db_session, NOW, limit=2)) == 2


def test_the_most_overdue_user_goes_first(db_session: Session, make_user):
    late = make_user()
    create_settings(db_session, late.id, fiat="EUR")
    update_settings(db_session, late.id, next_invest_at=NOW - timedelta(hours=5))

    recent = make_user()
    create_settings(db_session, recent.id, fiat="EUR")
    update_settings(db_session, recent.id, next_invest_at=NOW - timedelta(minutes=1))

    assert [d.user_id for d in due_users(db_session, NOW, limit=10)] == [late.id, recent.id]


def test_an_asset_is_inserted_then_updated_in_place(db_session: Session, make_user):
    user = make_user()

    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("40"))

    assets = list_assets(db_session, user.id)
    assert len(assets) == 1
    assert assets[0].target_pct == D("40")


def test_assets_come_back_in_a_stable_order(db_session: Session, make_user):
    user = make_user()
    upsert_asset(db_session, user.id, asset="ETH", pair="ETHEUR", target_pct=D("30"))
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert [a.asset for a in list_assets(db_session, user.id)] == ["BTC", "ETH"]


def test_deleting_an_asset_says_whether_there_was_one(db_session: Session, make_user):
    user = make_user()
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert delete_asset(db_session, user.id, "BTC") is True
    assert delete_asset(db_session, user.id, "BTC") is False


def test_targets_come_back_in_the_shape_the_engine_takes(db_session: Session, make_user):
    """`reconcile` takes `targets` as a mapping of asset code to percent. This is it."""
    user = make_user()
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))
    upsert_asset(db_session, user.id, asset="ETH", pair="ETHEUR", target_pct=D("30"))

    assert targets_for(db_session, user.id) == {"BTC": D("60.00"), "ETH": D("30.00")}


def test_a_target_of_zero_is_kept_because_it_means_exit(db_session: Session, make_user):
    """No row means unmanaged. A zero row means sell it. The engine needs to see the row."""
    user = make_user()
    upsert_asset(db_session, user.id, asset="DOGE", pair="DOGEEUR", target_pct=D("0"))

    assert targets_for(db_session, user.id) == {"DOGE": D("0.00")}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_settings.py -v --no-cov
```

Expected: FAIL, `ModuleNotFoundError: No module named 'core.db.settings'`

- [ ] **Step 3: Write `core/db/settings.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_settings.py -v --no-cov
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add core/db/settings.py tests/integration/test_settings.py
git commit -m "feat(db): settings, asset targets and the scheduler due query"
```

---

### Task 5: The order ledger and the unresolved-attempt gate

**Files:**
- Create: `core/db/orders.py`
- Create: `tests/integration/test_orders.py`

**Interfaces:**
- Consumes: `core.db.models.Order`, `core.db.types.OrderReason`, `core.db.types.OrderStatus`, `engine.types.Side`
- Produces:
  - `record_attempt(session, user_id, cl_ord_id, pair, asset, side, reason, requested_fiat) -> Order`
  - `get_by_cl_ord_id(session, cl_ord_id) -> Order | None`
  - `mark_filled(session, cl_ord_id, txid, executed_volume, executed_price, fee) -> Order | None`
  - `mark_failed(session, cl_ord_id) -> Order | None`
  - `pending_orders(session, user_id) -> list[Order]`
  - `has_unresolved(session, user_id) -> bool`
  - `list_orders(session, user_id, limit) -> list[Order]`

**Rules this implements** (spec §9.2, §9.3):
- The row is written `PENDING` **before** `AddOrder` is called.
- `mark_failed` is only ever called on a genuine absence. A lookup that itself failed
  leaves the row `PENDING`, because the two readings differ by a duplicate order.
- While anything is unresolved, that user is not evaluated.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_orders.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.orders import (
    get_by_cl_ord_id,
    has_unresolved,
    list_orders,
    mark_failed,
    mark_filled,
    pending_orders,
    record_attempt,
)
from core.db.types import OrderReason, OrderStatus
from engine.types import Side

D = Decimal


def _attempt(session: Session, user_id, cl_ord_id: str, **overrides):
    fields = {
        "pair": "XBTEUR",
        "asset": "BTC",
        "side": Side.BUY,
        "reason": OrderReason.INVEST,
        "requested_fiat": D("100"),
    }
    fields.update(overrides)
    return record_attempt(session, user_id, cl_ord_id, **fields)


def test_an_attempt_is_recorded_pending_with_nothing_from_kraken_yet(
    db_session: Session, make_user
):
    """The row describes the attempt before the attempt happens."""
    order = _attempt(db_session, make_user().id, "cl-1")

    assert order.status == OrderStatus.PENDING
    assert order.txid is None
    assert order.executed_volume is None
    assert order.requested_fiat == D("100.000000000000")


def test_the_same_client_id_cannot_be_used_twice(db_session: Session, make_user):
    """One id per attempt. Reusing one would make a lost response unresolvable."""
    _attempt(db_session, make_user().id, "cl-2")

    with pytest.raises(IntegrityError):
        _attempt(db_session, make_user().id, "cl-2")


def test_a_fill_records_the_txid_the_volume_and_the_fee(db_session: Session, make_user):
    _attempt(db_session, make_user().id, "cl-3")

    order = mark_filled(
        db_session,
        "cl-3",
        txid="OABCDE-12345-XYZ",
        executed_volume=D("0.0021"),
        executed_price=D("47000.5"),
        fee=D("0.4"),
    )

    assert order.status == OrderStatus.FILLED
    assert order.txid == "OABCDE-12345-XYZ"
    assert order.executed_volume == D("0.002100000000")
    assert order.fee == D("0.400000000000")


def test_a_genuine_absence_marks_the_attempt_failed(db_session: Session, make_user):
    """Only when both endpoints answered and neither had the id. The next plan retries."""
    _attempt(db_session, make_user().id, "cl-4")

    assert mark_failed(db_session, "cl-4").status == OrderStatus.FAILED


def test_an_unknown_client_id_resolves_to_nothing(db_session: Session):
    assert get_by_cl_ord_id(db_session, "never-minted") is None
    assert mark_filled(db_session, "never-minted", "t", D("1"), D("1"), D("0")) is None
    assert mark_failed(db_session, "never-minted") is None


def test_only_unresolved_attempts_are_listed(db_session: Session, make_user):
    user = make_user()
    _attempt(db_session, user.id, "cl-5")
    _attempt(db_session, user.id, "cl-6")
    mark_filled(db_session, "cl-6", "t", D("1"), D("1"), D("0"))

    assert [o.cl_ord_id for o in pending_orders(db_session, user.id)] == ["cl-5"]


def test_one_user_is_not_blocked_by_another_users_unresolved_attempt(
    db_session: Session, make_user
):
    blocked = make_user()
    clear = make_user()
    _attempt(db_session, blocked.id, "cl-7")

    assert has_unresolved(db_session, blocked.id) is True
    assert has_unresolved(db_session, clear.id) is False


def test_resolving_the_last_attempt_clears_the_gate(db_session: Session, make_user):
    user = make_user()
    _attempt(db_session, user.id, "cl-8")

    mark_failed(db_session, "cl-8")

    assert has_unresolved(db_session, user.id) is False


def test_history_is_ordered_and_bounded_even_within_one_transaction(
    db_session: Session, make_user
):
    """Every leg of one rebalance shares a `created_at`, because PostgreSQL's `now()` is
    the transaction timestamp. The page order must still be stable."""
    user = make_user()
    for n in range(3):
        _attempt(db_session, user.id, f"cl-9-{n}")

    listed = list_orders(db_session, user.id, limit=2)

    assert [o.cl_ord_id for o in listed] == ["cl-9-2", "cl-9-1"]


def test_unresolved_attempts_are_ordered_oldest_first(db_session: Session, make_user):
    user = make_user()
    for n in range(3):
        _attempt(db_session, user.id, f"cl-10-{n}")

    assert [o.cl_ord_id for o in pending_orders(db_session, user.id)] == [
        "cl-10-0",
        "cl-10-1",
        "cl-10-2",
    ]


@pytest.mark.parametrize("status", [member.value for member in OrderStatus])
def test_every_order_status_the_code_knows_is_accepted(db_session: Session, make_user, status):
    order = _attempt(db_session, make_user().id, f"cl-status-{status}")

    order.status = status
    db_session.flush()


@pytest.mark.parametrize("reason", [member.value for member in OrderReason])
def test_every_reason_the_code_knows_is_accepted(db_session: Session, make_user, reason):
    _attempt(db_session, make_user().id, f"cl-reason-{reason}", reason=reason)


@pytest.mark.parametrize("side", [member.value for member in Side])
def test_every_side_the_code_knows_is_accepted(db_session: Session, make_user, side):
    _attempt(db_session, make_user().id, f"cl-side-{side}", side=side)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_orders.py -v --no-cov
```

Expected: FAIL, `ModuleNotFoundError: No module named 'core.db.orders'`

- [ ] **Step 3: Write `core/db/orders.py`**

```python
"""The order ledger.

The row exists before the order does. `record_attempt` runs before `AddOrder`, so the
persisted state describes the attempt before the attempt happens and a lost response
leaves evidence rather than a gap.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Order
from core.db.types import OrderReason, OrderStatus
from engine.types import Side


def record_attempt(
    session: Session,
    user_id: uuid.UUID,
    cl_ord_id: str,
    pair: str,
    asset: str,
    side: Side,
    reason: OrderReason,
    requested_fiat: Decimal,
) -> Order:
    """Write the attempt down first. Nothing here talks to Kraken."""
    order = Order(
        user_id=user_id,
        cl_ord_id=cl_ord_id,
        pair=pair,
        asset=asset,
        side=side,
        reason=reason,
        status=OrderStatus.PENDING,
        requested_fiat=requested_fiat,
    )
    session.add(order)
    session.flush()
    return order


def get_by_cl_ord_id(session: Session, cl_ord_id: str) -> Order | None:
    return session.execute(select(Order).where(Order.cl_ord_id == cl_ord_id)).scalar_one_or_none()


def mark_filled(
    session: Session,
    cl_ord_id: str,
    txid: str,
    executed_volume: Decimal,
    executed_price: Decimal,
    fee: Decimal,
) -> Order | None:
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.txid = txid
    order.executed_volume = executed_volume
    order.executed_price = executed_price
    order.fee = fee
    order.status = OrderStatus.FILLED
    session.flush()
    return order


def mark_failed(session: Session, cl_ord_id: str) -> Order | None:
    """Only for a genuine absence: both endpoints answered and neither had the id.

    A lookup that itself failed is still unknown, and its row must stay `PENDING`. The
    two readings differ by a duplicate order.
    """
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.status = OrderStatus.FAILED
    session.flush()
    return order


def pending_orders(session: Session, user_id: uuid.UUID) -> list[Order]:
    """The attempts to resolve before this user can be evaluated, oldest first."""
    stmt = (
        select(Order)
        .where(Order.user_id == user_id, Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at, Order.cl_ord_id)
    )
    return list(session.execute(stmt).scalars())


def has_unresolved(session: Session, user_id: uuid.UUID) -> bool:
    """While anything is unresolved, this user is not evaluated.

    A plan computed on an ambiguous balance is a wrong plan, and doing nothing for one
    round is safe here.
    """
    stmt = (
        select(Order.id)
        .where(Order.user_id == user_id, Order.status == OrderStatus.PENDING)
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def list_orders(session: Session, user_id: uuid.UUID, limit: int = 50) -> list[Order]:
    # `created_at` alone is not enough. PostgreSQL's `now()` is the transaction
    # timestamp, so every leg of one rebalance carries the same value and the order of
    # the page would be arbitrary. The client id breaks the tie.
    stmt = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.cl_ord_id.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_orders.py -v --no-cov
```

Expected: 17 passed — 10 plain tests plus 7 parametrised cases across the three
enumerations.

- [ ] **Step 5: Commit**

```bash
git add core/db/orders.py tests/integration/test_orders.py
git commit -m "feat(db): the order ledger and the unresolved-attempt gate"
```

---

### Task 6: The single live proposal

**Files:**
- Create: `core/db/proposals.py`
- Create: `tests/integration/test_proposals.py`

**Interfaces:**
- Consumes: `core.db.models.Proposal`, `core.db.types.ProposalStatus`, `core.db.types.ProposalTrigger`
- Produces:
  - `save_proposal(session, user_id, plan, trigger, version) -> Proposal`
  - `get_proposal(session, user_id) -> Proposal | None`
  - `get_live_proposal(session, user_id) -> Proposal | None`
  - `set_status(session, user_id, status) -> Proposal | None`
  - `withdraw(session, user_id) -> bool`

**Rules this implements** (spec §8):
- At most one proposal per user, enforced by a unique constraint and not by convention.
- The version is decided by the caller. Phase 6 owns "what counts as a material change";
  this layer only stores the number that phase 6 arrived at.
- A withdrawn proposal keeps its row. That is what lets a reader tell *there was one and
  it went away* from *there was never one*.

> **The plan column holds JSON, and JSON has no decimal type.**
> Every amount must already be a string by the time it reaches this layer. A `float`
> would lose money silently, which is the one failure this system cannot tolerate. The
> test below pins that contract.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_proposals.py`:

```python
import uuid

import pytest
from sqlalchemy.orm import Session

from core.db.proposals import (
    get_live_proposal,
    get_proposal,
    save_proposal,
    set_status,
    withdraw,
)
from core.db.types import ProposalStatus, ProposalTrigger

PLAN = {"legs": [{"asset": "BTC", "side": "sell", "amount_fiat": "100.00"}]}


def test_a_saved_proposal_is_live_at_the_version_the_caller_chose(db_session: Session, make_user):
    proposal = save_proposal(
        db_session, make_user().id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=3
    )

    assert proposal.status == ProposalStatus.LIVE
    assert proposal.version == 3
    assert proposal.trigger == ProposalTrigger.SCHEDULED


def test_saving_again_replaces_the_one_slot_rather_than_adding_a_second(
    db_session: Session, make_user
):
    user = make_user()
    first = save_proposal(
        db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1
    )

    second = save_proposal(
        db_session, user.id, plan=PLAN, trigger=ProposalTrigger.MANUAL, version=2
    )

    assert second.id == first.id
    assert second.version == 2
    assert second.trigger == ProposalTrigger.MANUAL


def test_the_plan_comes_back_exactly_as_it_went_in(db_session: Session, make_user):
    """Amounts are strings. JSON has no decimal type and a float would lose money."""
    saved = save_proposal(
        db_session, make_user().id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1
    )
    db_session.expire(saved)

    assert saved.plan == PLAN
    assert saved.plan["legs"][0]["amount_fiat"] == "100.00"


def test_a_withdrawn_proposal_is_no_longer_live_but_the_row_remains(
    db_session: Session, make_user
):
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)

    withdraw(db_session, user.id)

    assert get_live_proposal(db_session, user.id) is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN


def test_withdrawing_says_whether_there_was_a_proposal(db_session: Session, make_user):
    user = make_user()

    assert withdraw(db_session, user.id) is False

    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)
    assert withdraw(db_session, user.id) is True


def test_a_new_proposal_revives_a_withdrawn_slot(db_session: Session, make_user):
    """Drift came back. The slot is reused rather than a second row being created."""
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)
    withdraw(db_session, user.id)

    revived = save_proposal(
        db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=2
    )

    assert revived.status == ProposalStatus.LIVE


def test_the_status_moves_through_execution(db_session: Session, make_user):
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.MANUAL, version=1)

    set_status(db_session, user.id, ProposalStatus.EXECUTING)
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTING

    set_status(db_session, user.id, ProposalStatus.EXECUTED)
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTED


def test_a_user_with_no_proposal_has_none(db_session: Session, make_user):
    user = make_user()

    assert get_proposal(db_session, user.id) is None
    assert get_live_proposal(db_session, user.id) is None
    assert set_status(db_session, user.id, ProposalStatus.EXECUTED) is None


def test_an_unknown_user_has_no_proposal(db_session: Session):
    assert get_proposal(db_session, uuid.uuid4()) is None


@pytest.mark.parametrize("status", [member.value for member in ProposalStatus])
def test_every_proposal_status_the_code_knows_is_accepted(db_session: Session, make_user, status):
    user = make_user()
    proposal = save_proposal(
        db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1
    )

    proposal.status = status
    db_session.flush()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_proposals.py -v --no-cov
```

Expected: FAIL, `ModuleNotFoundError: No module named 'core.db.proposals'`

- [ ] **Step 3: Write `core/db/proposals.py`**

```python
"""The live proposal.

One row per user, and the status says what is in the slot. A withdrawn proposal keeps its
row so a reader can tell *there was one and it went away* from *there was never one*.

The `plan` column is JSON, and JSON has no decimal type. Every amount must already be a
string when it arrives here. A float would lose money silently.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Proposal
from core.db.types import ProposalStatus, ProposalTrigger


def get_proposal(session: Session, user_id: uuid.UUID) -> Proposal | None:
    """Whatever is in this user's slot, whatever its status."""
    stmt = select(Proposal).where(Proposal.user_id == user_id)
    return session.execute(stmt).scalar_one_or_none()


def get_live_proposal(session: Session, user_id: uuid.UUID) -> Proposal | None:
    """The proposal only while it is live. A withdrawn or executed one is not offered."""
    proposal = get_proposal(session, user_id)
    if proposal is None or proposal.status != ProposalStatus.LIVE:
        return None
    return proposal


def save_proposal(
    session: Session,
    user_id: uuid.UUID,
    plan: dict[str, object],
    trigger: ProposalTrigger,
    version: int,
) -> Proposal:
    """Write this user's proposal, reusing the slot if one is already there.

    The version arrives decided. What counts as a material change is the caller's
    judgement, and this layer only stores the number it arrived at.
    """
    proposal = get_proposal(session, user_id)
    if proposal is None:
        proposal = Proposal(user_id=user_id)
        session.add(proposal)
    proposal.plan = plan
    proposal.trigger = trigger
    proposal.version = version
    proposal.status = ProposalStatus.LIVE
    session.flush()
    return proposal


def set_status(session: Session, user_id: uuid.UUID, status: ProposalStatus) -> Proposal | None:
    proposal = get_proposal(session, user_id)
    if proposal is None:
        return None
    proposal.status = status
    session.flush()
    return proposal


def withdraw(session: Session, user_id: uuid.UUID) -> bool:
    """True when there was a proposal to withdraw, false when there was none."""
    return set_status(session, user_id, ProposalStatus.WITHDRAWN) is not None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_proposals.py -v --no-cov
```

Expected: 13 passed — 9 plain tests plus 4 parametrised statuses.

- [ ] **Step 5: Commit**

```bash
git add core/db/proposals.py tests/integration/test_proposals.py
git commit -m "feat(db): the single live proposal per user"
```

---

### Task 7: Snapshots, evaluation records and retention

**Files:**
- Create: `core/db/telemetry.py`
- Create: `tests/integration/test_telemetry.py`

**Interfaces:**
- Consumes: `core.db.models.PortfolioSnapshot`, `core.db.models.EvaluationSession`
- Produces:
  - `record_snapshot(session, user_id, as_of, fiat, total_value, cash, holdings) -> PortfolioSnapshot`
  - `latest_snapshot(session, user_id) -> PortfolioSnapshot | None`
  - `snapshots_since(session, user_id, since, limit) -> list[PortfolioSnapshot]`
  - `start_evaluation(session, user_id, started_at) -> EvaluationSession`
  - `finish_evaluation(session, evaluation_id, status, finished_at, log_messages) -> EvaluationSession | None`
  - `list_evaluations(session, user_id, limit) -> list[EvaluationSession]`
  - `delete_evaluations_before(session, cutoff) -> int`

**Rules this implements** (spec §6, §10.3, §10.4):
- The value series cannot be reconstructed afterwards, so it is written from day one.
- `holdings` carries the unmanaged assets too, each flagged, so the user sees their real
  account rather than a partial view of it.
- Every evaluation records its duration, so the host ceiling shows up on a chart instead
  of being reconstructed during an incident.
- Retention is part of the initial schema, not a later patch.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_telemetry.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.telemetry import (
    delete_evaluations_before,
    finish_evaluation,
    latest_snapshot,
    list_evaluations,
    record_snapshot,
    snapshots_since,
    start_evaluation,
)

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
HOLDINGS = {
    "BTC": {"amount": "0.5", "value": "24000.00", "managed": True},
    "DOGE": {"amount": "1000", "value": "80.00", "managed": False},
}


def _snapshot(session: Session, user_id, as_of: datetime, total: str = "30000"):
    return record_snapshot(
        session,
        user_id,
        as_of=as_of,
        fiat="EUR",
        total_value=D(total),
        cash=D("6000"),
        holdings=HOLDINGS,
    )


def test_a_snapshot_keeps_its_amounts_as_decimals(db_session: Session, make_user):
    snapshot = _snapshot(db_session, make_user().id, NOW)

    assert snapshot.total_value == D("30000.000000000000")
    assert snapshot.cash == D("6000.000000000000")
    assert isinstance(snapshot.total_value, Decimal)


def test_a_snapshot_records_the_unmanaged_holdings_too(db_session: Session, make_user):
    """The user sees their real Kraken account, not a partial view of it."""
    snapshot = _snapshot(db_session, make_user().id, NOW)

    assert snapshot.holdings["DOGE"]["managed"] is False


def test_the_latest_snapshot_is_the_newest_by_as_of(db_session: Session, make_user):
    user = make_user()
    _snapshot(db_session, user.id, NOW - timedelta(days=1), total="10")
    _snapshot(db_session, user.id, NOW, total="20")
    _snapshot(db_session, user.id, NOW - timedelta(hours=1), total="30")

    assert latest_snapshot(db_session, user.id).total_value == D("20.000000000000")


def test_a_user_with_no_snapshot_has_none(db_session: Session, make_user):
    assert latest_snapshot(db_session, make_user().id) is None


def test_the_series_is_returned_oldest_first_from_a_start_point(db_session: Session, make_user):
    user = make_user()
    _snapshot(db_session, user.id, NOW - timedelta(days=3), total="10")
    _snapshot(db_session, user.id, NOW - timedelta(days=1), total="20")
    _snapshot(db_session, user.id, NOW, total="30")

    series = snapshots_since(db_session, user.id, since=NOW - timedelta(days=2), limit=100)

    assert [s.total_value for s in series] == [D("20.000000000000"), D("30.000000000000")]


def test_an_evaluation_starts_open(db_session: Session, make_user):
    record = start_evaluation(db_session, make_user().id, started_at=NOW)

    assert record.started_at == NOW
    assert record.finished_at is None
    assert record.duration_ms is None
    assert record.status == "RUNNING"


def test_finishing_an_evaluation_records_how_long_it_took(db_session: Session, make_user):
    """The host ceiling shows up on a chart rather than during an incident."""
    record = start_evaluation(db_session, make_user().id, started_at=NOW)

    finished = finish_evaluation(
        db_session,
        record.id,
        status="COMPLETED",
        finished_at=NOW + timedelta(milliseconds=1500),
        log_messages='["evaluated"]',
    )

    assert finished.status == "COMPLETED"
    assert finished.duration_ms == 1500
    assert finished.log_messages == '["evaluated"]'


def test_finishing_an_evaluation_that_does_not_exist_returns_none(db_session: Session):
    assert (
        finish_evaluation(db_session, uuid.uuid4(), status="FAILED", finished_at=NOW) is None
    )


def test_evaluations_come_back_newest_first_and_bounded(db_session: Session, make_user):
    user = make_user()
    for n in range(3):
        start_evaluation(db_session, user.id, started_at=NOW - timedelta(hours=n))

    listed = list_evaluations(db_session, user.id, limit=2)

    assert len(listed) == 2
    assert listed[0].started_at == NOW


def test_retention_removes_the_old_and_keeps_the_recent(db_session: Session, make_user):
    user = make_user()
    start_evaluation(db_session, user.id, started_at=NOW - timedelta(days=400))
    start_evaluation(db_session, user.id, started_at=NOW - timedelta(days=10))

    removed = delete_evaluations_before(db_session, cutoff=NOW - timedelta(days=365))

    assert removed == 1
    assert len(list_evaluations(db_session, user.id, limit=10)) == 1


def test_retention_sweeps_every_user_at_once(db_session: Session, make_user):
    """It is a system-wide sweep, not something a user asks for."""
    for _ in range(2):
        start_evaluation(db_session, make_user().id, started_at=NOW - timedelta(days=400))

    assert delete_evaluations_before(db_session, cutoff=NOW - timedelta(days=365)) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_telemetry.py -v --no-cov
```

Expected: FAIL, `ModuleNotFoundError: No module named 'core.db.telemetry'`

- [ ] **Step 3: Write `core/db/telemetry.py`**

```python
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


def start_evaluation(
    session: Session, user_id: uuid.UUID, started_at: datetime
) -> EvaluationSession:
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


def list_evaluations(
    session: Session, user_id: uuid.UUID, limit: int = 50
) -> list[EvaluationSession]:
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
    result = session.execute(
        delete(EvaluationSession).where(EvaluationSession.started_at < cutoff)
    )
    session.flush()
    return result.rowcount
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_telemetry.py -v --no-cov
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add core/db/telemetry.py tests/integration/test_telemetry.py
git commit -m "feat(db): the value series, evaluation records and retention"
```

---

### Task 8: The facade, tenant isolation and the phase gate

**Files:**
- Create: `core/database.py`
- Create: `tests/integration/test_tenant_isolation.py`
- Create: `tests/unit/core/__init__.py`
- Create: `tests/unit/core/test_layering.py`
- Create: `tests/unit/core/test_config.py`

**Interfaces:**
- Consumes: every module from tasks 1 to 7
- Produces: `core.database`, which re-exports every DAL function and `session_scope`.
  Later phases import this one module and never reach into `core/db/` directly.

> **One function in the ledger is not scoped by `user_id`, on purpose.**
> `mark_filled` and `mark_failed` take a `cl_ord_id` alone. That identifier is minted by
> the system and never supplied by a caller, so it carries no tenant question — and
> `cl_ord_id` is unique across the whole table, so it resolves to exactly one row. **No
> endpoint may ever accept a `cl_ord_id` from a client.** The read path, which is what an
> endpoint does reach, is scoped, and the tests below pin that.
>
> `delete_evaluations_before` is the other exception: retention is a system-wide sweep,
> not something a tenant asks for.

- [ ] **Step 1: Write `core/database.py`**

```python
"""The facade over `core/db/`.

A call site imports this one module and writes `db.get_settings(session, user_id)`, so a
query that moves from one domain module to another does not touch any caller.

The direction is one way. The domain modules never import this file, and a unit test
holds them to it — a cycle here would make the import order load-bearing.
"""

from __future__ import annotations

from core.db.orders import (
    get_by_cl_ord_id,
    has_unresolved,
    list_orders,
    mark_failed,
    mark_filled,
    pending_orders,
    record_attempt,
)
from core.db.proposals import (
    get_live_proposal,
    get_proposal,
    save_proposal,
    set_status,
    withdraw,
)
from core.db.session import configure, get_engine, session_scope
from core.db.settings import (
    DueUser,
    create_settings,
    delete_asset,
    due_users,
    get_settings,
    list_assets,
    targets_for,
    update_settings,
    upsert_asset,
)
from core.db.telemetry import (
    delete_evaluations_before,
    finish_evaluation,
    latest_snapshot,
    list_evaluations,
    record_snapshot,
    snapshots_since,
    start_evaluation,
)
from core.db.users import (
    create_user,
    delete_credentials,
    get_credentials,
    get_user,
    get_user_by_identity,
    save_credentials,
    set_user_status,
)

__all__ = [
    "DueUser",
    "configure",
    "create_settings",
    "create_user",
    "delete_asset",
    "delete_credentials",
    "delete_evaluations_before",
    "due_users",
    "finish_evaluation",
    "get_by_cl_ord_id",
    "get_credentials",
    "get_engine",
    "get_live_proposal",
    "get_proposal",
    "get_settings",
    "get_user",
    "get_user_by_identity",
    "has_unresolved",
    "latest_snapshot",
    "list_assets",
    "list_evaluations",
    "list_orders",
    "mark_failed",
    "mark_filled",
    "pending_orders",
    "record_attempt",
    "record_snapshot",
    "save_credentials",
    "save_proposal",
    "session_scope",
    "set_status",
    "set_user_status",
    "snapshots_since",
    "start_evaluation",
    "targets_for",
    "update_settings",
    "upsert_asset",
    "withdraw",
]
```

- [ ] **Step 2: Write the tenant isolation tests**

`tests/integration/test_tenant_isolation.py`:

```python
"""User A must never read or change user B's rows.

This is its own file because it is its own class of bug. It cannot exist until a system
is multi-tenant, and no test that uses a single user will ever find it.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

import core.database as db
from core.db.types import OrderReason, ProposalTrigger
from engine.types import Side

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
PLAN = {"legs": [{"asset": "BTC", "side": "sell", "amount_fiat": "100.00"}]}


@pytest.fixture
def alice(make_user):
    return make_user(email="alice@example.test")


@pytest.fixture
def bob(make_user):
    return make_user(email="bob@example.test")


def test_settings_are_not_shared(db_session: Session, alice, bob):
    db.create_settings(db_session, alice.id, fiat="EUR")

    assert db.get_settings(db_session, bob.id) is None


def test_changing_one_users_settings_leaves_the_other_alone(db_session: Session, alice, bob):
    db.create_settings(db_session, alice.id, fiat="EUR")
    db.create_settings(db_session, bob.id, fiat="EUR")

    db.update_settings(db_session, alice.id, min_drift_pct=D("5.0"))

    assert db.get_settings(db_session, bob.id).min_drift_pct == D("0")


def test_one_users_assets_never_appear_in_anothers(db_session: Session, alice, bob):
    db.upsert_asset(db_session, alice.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert db.list_assets(db_session, bob.id) == []
    assert db.targets_for(db_session, bob.id) == {}


def test_deleting_an_asset_only_reaches_your_own(db_session: Session, alice, bob):
    db.upsert_asset(db_session, alice.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert db.delete_asset(db_session, bob.id, "BTC") is False
    assert db.targets_for(db_session, alice.id) == {"BTC": D("60.00")}


def test_credentials_cannot_be_read_across_users(db_session: Session, alice, bob):
    db.save_credentials(db_session, alice.id, b"secret", b"nonce", 1, NOW)

    assert db.get_credentials(db_session, bob.id) is None
    assert db.delete_credentials(db_session, bob.id) is False


def test_the_order_history_is_scoped(db_session: Session, alice, bob):
    db.record_attempt(
        db_session,
        alice.id,
        "cl-iso-1",
        pair="XBTEUR",
        asset="BTC",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
    )

    assert db.list_orders(db_session, bob.id, limit=10) == []
    assert db.pending_orders(db_session, bob.id) == []


def test_one_users_unresolved_attempt_does_not_block_another(db_session: Session, alice, bob):
    """The gate stops one tenant, never the whole population."""
    db.record_attempt(
        db_session,
        alice.id,
        "cl-iso-2",
        pair="XBTEUR",
        asset="BTC",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
    )

    assert db.has_unresolved(db_session, alice.id) is True
    assert db.has_unresolved(db_session, bob.id) is False


def test_a_proposal_belongs_to_exactly_one_user(db_session: Session, alice, bob):
    db.save_proposal(
        db_session, alice.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1
    )

    assert db.get_proposal(db_session, bob.id) is None
    assert db.withdraw(db_session, bob.id) is False
    assert db.get_live_proposal(db_session, alice.id) is not None


def test_snapshots_and_evaluations_are_scoped(db_session: Session, alice, bob):
    db.record_snapshot(
        db_session,
        alice.id,
        as_of=NOW,
        fiat="EUR",
        total_value=D("100"),
        cash=D("10"),
        holdings={},
    )
    db.start_evaluation(db_session, alice.id, started_at=NOW)

    assert db.latest_snapshot(db_session, bob.id) is None
    assert db.list_evaluations(db_session, bob.id, limit=10) == []


def test_removing_one_user_leaves_the_other_untouched(db_session: Session, alice, bob):
    """The cascade must reach everything of theirs and nothing of anybody else's."""
    for user in (alice, bob):
        db.create_settings(db_session, user.id, fiat="EUR")
        db.save_credentials(db_session, user.id, b"secret", b"nonce", 1, NOW)
        db.upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    db_session.delete(db.get_user(db_session, alice.id))
    db_session.flush()

    assert db.get_settings(db_session, alice.id) is None
    assert db.get_credentials(db_session, alice.id) is None
    assert db.targets_for(db_session, alice.id) == {}
    assert db.get_settings(db_session, bob.id) is not None
    assert db.get_credentials(db_session, bob.id) is not None
    assert db.targets_for(db_session, bob.id) == {"BTC": D("60.00")}
```

- [ ] **Step 3: Write the unit tests that need no database**

`tests/unit/core/__init__.py` is an empty file.

`tests/unit/core/test_layering.py`:

```python
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[3] / "core" / "db"


def test_no_domain_module_imports_the_facade():
    """The facade points at the domains, never the other way.

    A cycle here would make the import order load-bearing, and the failure would appear
    as an unrelated ImportError much later.
    """
    offenders = [
        path.name
        for path in sorted(DOMAIN_DIR.glob("*.py"))
        if "core.database" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
```

`tests/unit/core/test_config.py`:

```python
import pytest

from core.config import database_url


def test_a_missing_database_url_raises_rather_than_defaulting(monkeypatch):
    """A silent default would point production at a local database, and the failure would
    look like an empty account."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_the_url_that_is_set_is_the_one_returned(monkeypatch):
    """This test sets the environment because the reader is what is under test. Every
    other test states its inputs instead."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db")

    assert database_url() == "postgresql+psycopg://u:p@host:5432/db"
```

- [ ] **Step 4: Run the new tests**

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests/integration/test_tenant_isolation.py tests/unit/core -v --no-cov
```

Expected: 13 passed — 10 isolation tests and 3 unit tests.

- [ ] **Step 5: Run the whole suite with the gate**

```bash
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests --cov-fail-under=80
```

Expected: 125 passed, and `Required test coverage of 80% reached`.

If coverage falls below 80 %, read the missing lines in the report and add the test to
the file that owns that module. Do not lower the gate.

- [ ] **Step 6: Prove the unit suite still stands alone**

```bash
PYTHONPATH=. pytest tests/unit --no-cov
```

Expected: 37 passed — the 34 from phase 1 plus the 3 new unit tests. No database is
running for this command, and nothing skips, because nothing in `tests/unit` needs one.

- [ ] **Step 7: Run lint and format**

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 8: Commit and push**

```bash
git add core/database.py tests/integration/test_tenant_isolation.py tests/unit/core
git commit -m "feat(db): the facade, and tenant isolation as its own test category"
git push -u origin feat/phase-2-persistence
```

- [ ] **Step 9: Open the pull request and confirm CI is green**

```bash
gh pr create --base main --title "Phase 2: persistence" --body "Schema, migrations and the DAL over a real PostgreSQL."
gh pr checks --watch
```

Expected: `pass`. Then read the CI log and confirm the integration tests really **ran**
rather than skipping:

```bash
gh run view --log | grep -E "passed|skipped"
```

Expected: `125 passed`, and no skips. A skipped integration suite in CI means the gate is
measuring nothing, which is worse than a failure because it still looks green.

---

## What you verify before phase 3

Phase 2 touches no money, no credential and no network. Nothing here can place an order,
because nothing here knows how to reach Kraken. Verification is reading, running and
looking at the schema by hand.

1. **The migration applies from empty.** Drop the volume and bring it back from nothing:

   ```bash
   docker compose -f docker-compose.dev.yml down -v && docker compose -f docker-compose.dev.yml up -d
   ```

   Then `PYTHONPATH=. alembic upgrade head` with `DATABASE_URL` set. This is the path a
   new production database will take, and it is the one least often tested.

2. **Look at the schema yourself.**

   ```bash
   docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -d coinpilot -c "\d+ user_settings"
   ```

   Check the column types against what you expect. `min_drift_pct` should be
   `numeric(4,1)` and `min_order_fiat` `numeric(10,1)`.

3. **The suite is green and CI agrees**, with the integration tests really running there.

4. **Three decisions deserve a deliberate look.** They are choices, not consequences, and
   this is the cheap moment to change any of them:

   - **The key and the secret share one ciphertext under one nonce.** It removes a class
     of mistake rather than documenting it. The cost is that they cannot be rotated
     separately, which nothing needs.
   - **A withdrawn proposal keeps its row.** The alternative is deleting it, which loses
     the difference between *there was one* and *there was never one*.
   - **`sessions.status` carries no check constraint** while every other status column
     does. Telemetry gains values, and a constraint there would turn each new one into a
     migration.

5. **The tenant boundary holds.** Read `tests/integration/test_tenant_isolation.py`. Every
   read path is scoped by `user_id`. Two functions are not, and both are named in task 8
   with the reason. If you disagree with either, now is when it is cheap.

6. **The facade stays one-directional.**

   ```bash
   grep -rl "core.database" core/db/
   ```

   Expected: no output. A unit test asserts the same thing, so this is a second pair of
   eyes rather than the only check.
