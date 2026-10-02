# Phase 5 — Execution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person invests their free cash with `POST /invest`. They can preview first: the
preview has Kraken validate every order without executing it. Every order is written down
before it is sent, and every answer that cannot be read is resolved before anything else
is computed.

**Architecture:** `exchange/` learns to place a market buy in fiat and to tell a refusal
apart from an unknown answer. It also learns to read an order by its txid. `core/settlement.py`
turns what Kraken says about an order into the ledger's status, and resolves what is
still unknown. `core/execution.py` is the only module that places an order: it holds a
per-user advisory lock, resolves first, plans with the engine, and sends each leg in
short transactions of its own. `api/routes/invest.py` is a thin layer over it.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, PostgreSQL advisory locks, httpx.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.4, §6, §7.3, §9, §11, §12, §14

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 5 of 8

## Global Constraints

- **Python 3.13.** One version, not a range.
- **Money is `Decimal`, never `float`.** A JSON response carries every amount as a string,
  written without padding (`core.portfolio.plain_amount`).
- **Pin every dependency with `==`.** This phase adds none.
- **No test reads configuration from the environment.** `load_config` takes a mapping, and
  every test hands it a plain dict.
- **No test touches the network, and no test places a real order.** Kraken is answered by
  `httpx.MockTransport`. Against the real Kraken, `validate=true` only.
- **No endpoint returns a Kraken credential**, not even in an error. No log line contains one.
- **Every endpoint is scoped to the authenticated user.** No route takes a user id.
- **Only `core/execution.py` places an order.** A test fails if `add_order` appears
  anywhere else under `api/` or `core/`.
- **This phase only buys.** Sells arrive with the rebalance in phase 6. Kraken accepts an
  amount in fiat (`viqc`) on buys only.
- **Coverage gate is 80 %**, enforced by the CI command.
- **`ruff check` and `ruff format --check` must pass.**
- Commit messages follow Conventional Commits.

## Review Focus

Each of these, if wrong, spends someone's money. Each has a test in the task that owns it.

1. **The attempt is committed before the order is sent.** A row that is still inside an
   open transaction does not survive the process. → Task 7.
2. **Unknown is never read as failed.** Only a closed list of Kraken codes means *refused*.
   A code nobody has seen, a 5xx and a timeout all mean *unknown*. → Task 3.
3. **An absence read too soon is not an absence.** Kraken may not list an order it has
   just accepted, so a lookup seconds after a lost answer can read absence that is not
   real. An absence counts only once the attempt is older than `ABSENCE_GRACE`. → Task 6.
4. **Two evaluations of one user never run at once.** They would spend the same cash
   twice. → Tasks 5 and 7.
5. **A preview writes nothing.** No order row, no evaluation row, no snapshot. → Task 7.
6. **After an unknown answer, no further leg is sent.** The balance is ambiguous until the
   next evaluation resolves it. → Task 7.

---

## What Kraken says

Every fact below was read from Kraken's documentation while writing this plan. The last
two rows are what the documentation leaves open. The manual check settles them.

| Fact | Source |
|---|---|
| `AddOrder` answers `{"descr": {...}, "txid": ["OU22CG-KLAF2-FWUDD7"]}` | [AddOrder](https://docs.kraken.com/api-reference/trading/add-order) |
| `oflags`: `viqc` is "order volume expressed in quote currency. This option is supported only for buy market orders". `fcib` is "prefer fee in base currency (default if selling)" | [AddOrder](https://docs.kraken.com/api-reference/trading/add-order) |
| `validate`: "the order will be validated only, it will not trade in the matching engine" | [AddOrder](https://docs.kraken.com/api-reference/trading/add-order) |
| `QueryOrders` takes `txid`, "comma delimited list of up to 50 ids". Each order carries `status` (`pending`, `open`, `closed`, `canceled`, `expired`), `vol`, `vol_exec`, `cost`, `fee`, `price` (average), `oflags`, `cl_ord_id` | [QueryOrders](https://docs.kraken.com/api/docs/rest-api/get-orders-info) |
| `AssetPairs` carries `cost_decimals`, "Number of decimal places for cost of trades in pair (quote asset terms)", beside `ordermin` (base currency) and `costmin` (quote currency) | [AssetPairs](https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs) |
| A pair's `status` is one of `online`, `cancel_only`, `post_only`, `limit_only`, `reduce_only`; only `online` takes a market order | [AssetPairs](https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs) |
| **Open:** whether `viqc` changes the unit of `vol`, `vol_exec` and `cost` in `QueryOrders` (the description of `cost` reads "quote currency unless" and stops) | Verified on the first real order |
| **Open:** whether the `fee` of an `fcib` order is reported in base or quote | Verified on the first real order |

The ledger therefore stores what Kraken returns, **unconverted**. No status decision
depends on the unit: a fill is `FILLED` when `vol_exec` is above zero, in whatever unit.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/db/models.py` | `invest_cash_enabled` defaults to `false`; `orders` gains `attempted_at`, `cost`, `error` |
| `scripts/migrations/versions/<rev>_order_cost_error_and_attempt_time.py` | The three columns, autogenerated |
| `core/db/orders.py` | `record_attempt(attempted_at=)`, `mark_sent`, `mark_filled(cost=)`, `mark_failed(error=)` |
| `core/db/locks.py` | `advisory_user_lock` — one evaluation per user at a time |
| `exchange/types.py` | `PairMeta.cost_decimals`, `OrderLookup.cost`, `Placement`, `PlacementOutcome` |
| `exchange/precision.py` | `round_cost`, `minimum_fiat` |
| `exchange/orders.py` | `DEFINITIVE_REFUSALS`, `is_definitive_refusal`, `find_order_by_txid` |
| `exchange/client.py` | `add_order` returns a `Placement`; `query_orders` |
| `core/settlement.py` | `settle`, `resolve_pending`, `ABSENCE_GRACE` |
| `core/execution.py` | `invest` — the only caller of `add_order` |
| `api/context.py`, `api/main.py` | `AppContext.user_lock` |
| `api/schemas.py` | `LegOut`, `InvestOut`; `AssetOut.kraken_min_fiat`; `OrderOut.cost`, `OrderOut.error` |
| `api/routes/invest.py` | `POST /invest` |
| `api/routes/assets.py` | `GET /assets` shows Kraken's current minimum |
| `tests/integration/conftest.py` | `FakeKraken` answers `AddOrder`, `QueryOrders`, `OpenOrders`, `ClosedOrders`; `FakeLocks` |

---

## Decisions taken in this plan

The spec settles what to build. These settle how, where the spec leaves room.

- **A grace period before an absence is believed.** `ABSENCE_GRACE` is two minutes,
  counted from `attempted_at`, which the executor writes from its own clock. A lookup that
  reads *absent* sooner leaves the row `PENDING`. The cost is that an investment run
  within two minutes of a lost answer is refused as unresolved. Spec §9.2 says so.
- **An order is read by its txid as soon as it is sent.** A market order normally fills
  within the same second. If Kraken still reports it `open` or `pending`, the row stays
  `PENDING` with its txid, and the next evaluation reads it again.
- **The lock is a session-level advisory lock on a connection of its own**, held for the
  whole evaluation and released in a `finally`. If the process dies, its connection closes
  and the lock goes with it.
- **A preview takes no lock and resolves nothing.** It reads, plans and asks Kraken to
  validate. If anything is unresolved, it says so and stops: resolving would write.
- **The request's own transaction stays open, idle, during `POST /invest`.** The signed-in
  user is read through it. It holds no lock, only a connection, and the executor never
  writes through it. Accepted.
- **The executor applies both minimums, and the engine neither.** An invest plan is
  computed with `min_order_fiat` at zero, and the executor drops each leg below the larger
  of Kraken's minimum and the user's floor. The result is the same; the difference is that
  every dropped leg is logged with its reason. Spec §7.3 says so.
- **Leg amounts are rounded down to the pair's `cost_decimals`.** Down, for the reason a
  volume is rounded down: up would spend more than the plan allocated.
- **An evaluation's status is a string in `sessions`**: `DONE`, `NOTHING_TO_DO`,
  `STOPPED`, `UNRESOLVED`, `KRAKEN_UNAVAILABLE`, or `ERROR` when the executor raised.

## What this phase deliberately leaves out

- **Sells**, the proposal lifecycle and `POST /rebalance` — phase 6.
- **The scheduler.** Nothing invests on a cadence yet; `invest_cash_enabled` only changes
  its default here.
- **`paused`.** Not consulted by `POST /invest` in this phase. The user's choice.
- **Converting the fee** into one currency. Stored as Kraken reports it, until the manual
  check says which currency that is.
- **Retrying a refused order.** A refused leg is `FAILED`; the next investment plans from
  the real balance and asks again if the cash is still there.

---

### Task 1: The ledger and the defaults

**Files:**
- Modify: `core/db/models.py` (`UserSettings.invest_cash_enabled`, `Order`)
- Create: `scripts/migrations/versions/<rev>_order_cost_error_and_attempt_time.py` (autogenerated)
- Modify: `core/db/orders.py`
- Modify: `core/database.py`
- Modify: `api/schemas.py` (`OrderOut`)
- Test: `tests/integration/test_orders.py`, `tests/integration/test_settings.py`, `tests/integration/test_api_config.py`

**Interfaces:**
- Produces:
  - `record_attempt(session, user_id, cl_ord_id, pair, asset, side, reason, requested_fiat, attempted_at: datetime | None = None) -> Order`
  - `mark_sent(session, cl_ord_id: str, txid: str) -> Order | None` (row stays `PENDING`)
  - `mark_filled(session, cl_ord_id, txid, executed_volume, executed_price, fee, cost: Decimal | None = None) -> Order | None`
  - `mark_failed(session, cl_ord_id, error: str | None = None) -> Order | None` (error cut to 64 characters)
  - `Order.attempted_at: datetime`, `Order.cost: Decimal | None`, `Order.error: str | None`

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_settings.py`, in `test_a_new_settings_row_starts_with_the_stated_defaults`, replace:

```python
    assert settings.invest_cash_enabled is True
```

with:

```python
    # Investing on a cadence is opted into (spec §3.4).
    assert settings.invest_cash_enabled is False
```

In `tests/integration/test_api_config.py`, in `test_the_first_patch_creates_the_settings_with_their_defaults`, replace:

```python
    assert body["invest_cash_enabled"] is True
```

with:

```python
    assert body["invest_cash_enabled"] is False
```

In `tests/integration/test_orders.py`, add `from datetime import UTC, datetime` to the imports, add `mark_sent` to the import from `core.db.orders`, and append:

```python
def test_an_attempt_carries_the_time_the_executor_gives_it(db_session: Session, make_user):
    """Written from the executor's clock, so the grace before an absence is counted on it."""
    at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    order = _attempt(db_session, make_user().id, "cl-10", attempted_at=at)

    assert order.attempted_at == at


def test_an_attempt_without_a_time_gets_the_databases(db_session: Session, make_user):
    assert _attempt(db_session, make_user().id, "cl-11").attempted_at is not None


def test_a_sent_order_keeps_its_txid_and_stays_unresolved(db_session: Session, make_user):
    """Kraken accepted it. How it filled is not known yet."""
    user = make_user()
    _attempt(db_session, user.id, "cl-12")

    order = mark_sent(db_session, "cl-12", "OTX001-AAAAA-BBBBBB")

    assert order.txid == "OTX001-AAAAA-BBBBBB"
    assert order.status == OrderStatus.PENDING
    assert has_unresolved(db_session, user.id) is True


def test_a_fill_records_what_it_cost(db_session: Session, make_user):
    _attempt(db_session, make_user().id, "cl-13")

    order = mark_filled(
        db_session,
        "cl-13",
        txid="OTX002-AAAAA-BBBBBB",
        executed_volume=D("0.001"),
        executed_price=D("50000"),
        fee=D("0.000004"),
        cost=D("50"),
    )

    assert order.cost == D("50")


def test_a_refusal_keeps_krakens_code(db_session: Session, make_user):
    _attempt(db_session, make_user().id, "cl-14")

    order = mark_failed(db_session, "cl-14", error="EOrder:Insufficient funds")

    assert order.error == "EOrder:Insufficient funds"


def test_an_error_longer_than_its_column_is_cut_not_refused(db_session: Session, make_user):
    """A refusal must always be recordable. A row that cannot be written stays PENDING."""
    _attempt(db_session, make_user().id, "cl-15")

    assert len(mark_failed(db_session, "cl-15", error="E" * 200).error) == 64


def test_an_unknown_client_id_cannot_be_marked_sent(db_session: Session):
    assert mark_sent(db_session, "never-minted", "OTX") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_orders.py tests/integration/test_settings.py tests/integration/test_api_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'mark_sent'`, then the two default assertions.

- [ ] **Step 3: Change the models**

In `core/db/models.py`, in `UserSettings`, replace:

```python
    invest_cash_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

with:

```python
    # Off: configuring weights to look at a portfolio must not start spending (spec §3.4).
    invest_cash_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

In `Order`, after `fee`, add:

```python
    # What Kraken reports the order cost, unconverted. With a buy in fiat it should equal
    # `requested_fiat`, and storing it is how that is checked rather than assumed.
    cost: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    # Kraken's code, when it refused the order. A `FAILED` row with no code was an absence.
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The executor's clock, not `created_at`: the grace before an absence is believed is
    # counted on it (core/settlement.py).
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Generate the migration**

The development database must be at head first.

Run:

```bash
DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. .venv/Scripts/alembic revision --autogenerate -m "order cost, error and attempt time"
```

Open the generated file. Its `upgrade` must contain exactly these three operations, in any
order, and `downgrade` the three matching `drop_column` calls:

```python
    op.add_column("orders", sa.Column("cost", sa.Numeric(precision=24, scale=12), nullable=True))
    op.add_column("orders", sa.Column("error", sa.String(length=64), nullable=True))
    op.add_column(
        "orders",
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
```

The change of default for `invest_cash_enabled` is applied by the model, not the database,
so it produces no operation. Existing rows keep their value.

- [ ] **Step 5: Change the ledger**

In `core/db/orders.py`, add `from datetime import datetime` to the imports, and replace
`record_attempt`, `mark_filled` and `mark_failed` with:

```python
ERROR_CHARS = 64


def record_attempt(
    session: Session,
    user_id: uuid.UUID,
    cl_ord_id: str,
    pair: str,
    asset: str,
    side: Side,
    reason: OrderReason,
    requested_fiat: Decimal,
    attempted_at: datetime | None = None,
) -> Order:
    """Write the attempt down first. Nothing here talks to Kraken.

    `attempted_at` is the executor's clock. Without it the database's `now()` is used.
    """
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
    if attempted_at is not None:
        order.attempted_at = attempted_at
    session.add(order)
    session.flush()
    return order


def get_by_cl_ord_id(session: Session, cl_ord_id: str) -> Order | None:
    return session.execute(select(Order).where(Order.cl_ord_id == cl_ord_id)).scalar_one_or_none()


def mark_sent(session: Session, cl_ord_id: str, txid: str) -> Order | None:
    """Kraken accepted the order and named it. It stays `PENDING` until its fill is read."""
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.txid = txid
    session.flush()
    return order


def mark_filled(
    session: Session,
    cl_ord_id: str,
    txid: str,
    executed_volume: Decimal,
    executed_price: Decimal,
    fee: Decimal,
    cost: Decimal | None = None,
) -> Order | None:
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.txid = txid
    order.executed_volume = executed_volume
    order.executed_price = executed_price
    order.fee = fee
    order.cost = cost
    order.status = OrderStatus.FILLED
    session.flush()
    return order


def mark_failed(session: Session, cl_ord_id: str, error: str | None = None) -> Order | None:
    """For a definitive refusal, with Kraken's code, or a genuine absence, with none.

    A lookup that itself failed is still unknown, and its row must stay `PENDING`. The
    two readings differ by a duplicate order. The code is cut to fit its column: a
    refusal that cannot be written would leave the row `PENDING`.
    """
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.status = OrderStatus.FAILED
    order.error = None if error is None else error[:ERROR_CHARS]
    session.flush()
    return order
```

Delete the old `get_by_cl_ord_id` definition further up, so there is one.

In `core/database.py`, add `mark_sent` to the import from `core.db.orders` and to `__all__`,
in alphabetical position.

In `api/schemas.py`, in `OrderOut`, after `fee`, add:

```python
    cost: Decimal | None
    error: str | None
```

- [ ] **Step 6: Apply the migration and run the tests**

Run:

```bash
DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. .venv/Scripts/alembic upgrade head
RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q
```

Expected: PASS, every test.

- [ ] **Step 7: Commit**

```bash
git add core/db/models.py core/db/orders.py core/database.py api/schemas.py scripts/migrations/versions tests/integration
git commit -m "feat(core): the ledger records cost, Kraken's code and the attempt time; investing is opted into"
```

---

### Task 2: A pair's cost precision, and its minimum in fiat

**Files:**
- Modify: `exchange/types.py` (`PairMeta`)
- Modify: `exchange/client.py` (`asset_pairs`)
- Modify: `exchange/precision.py`
- Modify every test that builds a `PairMeta` or an `AssetPairs` answer: `tests/unit/exchange/test_precision.py`, `tests/unit/exchange/test_client.py`, `tests/unit/core/test_catalog.py`, `tests/unit/core/test_markets.py`, `tests/unit/core/test_reading.py`, `tests/integration/conftest.py`

**Interfaces:**
- Produces:
  - `PairMeta.cost_decimals: int` (last field)
  - `round_cost(meta: PairMeta, amount: Decimal) -> Decimal` — down, to `cost_decimals`
  - `minimum_fiat(meta: PairMeta, price: Decimal) -> Decimal` — `max(cost_min, order_min × price)`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/exchange/test_precision.py`, add `cost_decimals=5,` as the last argument of
the three `PairMeta(...)` calls (`BTC`, `CHEAP`, `frozen`), add `minimum_fiat` and
`round_cost` to the import from `exchange.precision`, and append:

```python
def test_a_fiat_amount_is_rounded_down_to_the_pairs_cost_precision():
    """Down, like a volume: up would spend more than the plan allocated."""
    assert round_cost(BTC, D("33.333333333333")) == D("33.33333")


def test_an_amount_already_within_the_precision_is_unchanged():
    assert round_cost(BTC, D("600")) == D("600")


def test_the_minimum_is_the_cost_minimum_when_the_volume_minimum_is_cheaper():
    # 0.00005 BTC at 50 000 is 2.5, under the 5 cost minimum.
    assert minimum_fiat(BTC, D("50000")) == D("5")


def test_the_minimum_follows_the_price_when_the_volume_minimum_is_dearer():
    # 0.00005 BTC at 200 000 is 10.
    assert minimum_fiat(BTC, D("200000")) == D("10")
```

In `tests/unit/exchange/test_client.py`, add `"cost_decimals": 5,` to the `XXBTZEUR` entry
of `ASSET_PAIRS`, and append:

```python
def test_a_pair_carries_its_cost_precision():
    client = _client(lambda request: _ok(ASSET_PAIRS))

    assert client.asset_pairs()["XXBTZEUR"].cost_decimals == 5
```

In `tests/unit/core/test_catalog.py` and `tests/unit/core/test_markets.py`, add
`cost_decimals=5,` as the last argument of the `PairMeta(...)` call in `_pair`.

In `tests/unit/core/test_reading.py`, replace:

```python
    return PairMeta(name, name, base, quote, 1, 8, D("0.0001"), D("0.5"), "online")
```

with:

```python
    return PairMeta(name, name, base, quote, 1, 8, D("0.0001"), D("0.5"), "online", 5)
```

In `tests/integration/conftest.py`, in `_raw_pair`, add `"cost_decimals": 5,` after
`"costmin": "0.5",`.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit -q`
Expected: FAIL — `TypeError: PairMeta.__init__() got an unexpected keyword argument 'cost_decimals'` and `ImportError: cannot import name 'minimum_fiat'`.

- [ ] **Step 3: Implement**

In `exchange/types.py`, in `PairMeta`, after `status: str`, add:

```python
    # Decimal places of an amount in the quote currency. A buy in fiat is rounded to it.
    cost_decimals: int
```

In `exchange/client.py`, in `asset_pairs`, add to the `PairMeta(...)` call, after `status=`:

```python
                    cost_decimals=int(entry["cost_decimals"]),
```

In `exchange/precision.py`, append:

```python
def round_cost(meta: PairMeta, amount: Decimal) -> Decimal:
    """A fiat amount to the pair's cost precision, always down.

    Down for the reason a volume is rounded down: up would spend more than the plan
    allocated, and the last leg of an investment can be every cent there is.
    """
    return amount.quantize(_quantum(meta.cost_decimals), rounding=ROUND_DOWN)


def minimum_fiat(meta: PairMeta, price: Decimal) -> Decimal:
    """The smallest order Kraken takes on this pair, in fiat, at this price.

    `costmin` is in the quote currency; `ordermin` is in the base asset, so its fiat value
    moves with the price. That is why this is computed when an order is about to be
    placed, never validated when a setting is saved (spec §7.3).
    """
    return max(meta.cost_min, meta.order_min * price)
```

- [ ] **Step 4: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test.

- [ ] **Step 5: Commit**

```bash
git add exchange tests
git commit -m "feat(exchange): a pair's cost precision, and its minimum order in fiat"
```

---

### Task 3: Placing an order, and telling a refusal from an unknown answer

**Files:**
- Modify: `exchange/types.py`
- Modify: `exchange/orders.py`
- Modify: `exchange/client.py`
- Test: `tests/unit/exchange/test_client.py`, `tests/unit/exchange/test_find_order.py`

**Interfaces:**
- Produces:
  - `PlacementOutcome(StrEnum)`: `SENT`, `VALIDATED`, `REFUSED`, `UNKNOWN`
  - `Placement(outcome: PlacementOutcome, txid: str | None = None, error: str | None = None)`
  - `DEFINITIVE_REFUSALS: tuple[str, ...]`, `is_definitive_refusal(errors: Sequence[str]) -> bool`
  - `KrakenClient.add_order(pair, side, volume, cl_ord_id, *, in_quote=False, validate=False) -> Placement` — never `None`
  - `SecretUnreadable(Exception)` in `exchange/client.py`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/exchange/test_find_order.py`, add `is_definitive_refusal` to the import from
`exchange.orders`, and append:

```python
@pytest.mark.parametrize(
    "errors",
    [
        ["EOrder:Insufficient funds"],
        ["EOrder:Order minimum not met"],
        ["EGeneral:Invalid arguments:volume"],
        ["EGeneral:Permission denied"],
        ["EAPI:Invalid nonce"],
        ["EService:Market in cancel_only mode"],
        ["EService:Market in post_only mode"],
        ["EService:Market in limit_only mode"],
    ],
)
def test_a_listed_code_is_a_definitive_refusal(errors):
    assert is_definitive_refusal(errors) is True


@pytest.mark.parametrize(
    "errors",
    [
        [],
        ["EService:Unavailable"],
        ["EService:Busy"],
        ["EGeneral:Internal error"],
        ["EBrandNew:A code nobody has seen"],
        # One ambiguous code is enough to make the whole answer unknown.
        ["EOrder:Insufficient funds", "EService:Busy"],
    ],
)
def test_anything_else_is_not(errors):
    """The list is closed. Reading a new code as a refusal is how a duplicate happens."""
    assert is_definitive_refusal(errors) is False
```

Add `import pytest` at the top of that file if it is not there.

In `tests/unit/exchange/test_client.py`, add `from urllib.parse import parse_qs` to the
imports, add `Placement` and `PlacementOutcome` to the import from `exchange.types`, then
replace the three existing order tests:

```python
def test_an_order_is_a_market_order_and_carries_its_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"txid": ["OABCDE-12345-XYZ"]})

    result = _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("0.00212765"), cl_ord_id="abc123"
    )

    assert "ordertype=market" in seen["body"]
    assert "type=buy" in seen["body"]
    assert "volume=0.00212765" in seen["body"]
    assert "cl_ord_id=abc123" in seen["body"]
    assert "price=" not in seen["body"]
    assert "oflags=" not in seen["body"]
    assert result == Placement(PlacementOutcome.SENT, txid="OABCDE-12345-XYZ")


def test_a_tiny_volume_is_sent_in_full_not_in_scientific_notation():
    """`str(Decimal("0.00000001"))` is "1E-8", which Kraken refuses."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"txid": ["X"]})

    _client(handler).add_order(pair="XXBTZEUR", side="sell", volume=D("0.00000001"), cl_ord_id="abc123")

    assert "volume=0.00000001" in seen["body"]


def test_a_validate_only_order_says_so_and_is_never_sent():
    """No integration test places a real order. This is how that rule is kept."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"descr": {"order": "buy 100 XBTEUR @ market"}})

    result = _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("1"), cl_ord_id="abc123", validate=True
    )

    assert "validate=true" in seen["body"]
    assert result == Placement(PlacementOutcome.VALIDATED)
```

and append:

```python
def _order_with(answer):
    return _client(lambda request: answer).add_order(
        pair="XXBTZEUR", side="buy", volume=D("100"), cl_ord_id="abc123", in_quote=True
    )


def test_a_buy_in_fiat_names_its_amount_in_the_quote_currency_and_its_fee_in_the_base():
    seen = {}

    def handler(request):
        seen["form"] = parse_qs(request.content.decode())
        return _ok({"txid": ["OTX"]})

    _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("100.00000"), cl_ord_id="abc123", in_quote=True
    )

    assert seen["form"]["oflags"] == ["viqc,fcib"]
    assert seen["form"]["volume"] == ["100.00000"]


def test_kraken_takes_an_amount_in_fiat_for_buys_only():
    with pytest.raises(ValueError):
        _client(lambda request: _ok({})).add_order(
            pair="XXBTZEUR", side="sell", volume=D("1"), cl_ord_id="abc123", in_quote=True
        )


@pytest.mark.parametrize(
    "error",
    ["EOrder:Insufficient funds", "EGeneral:Invalid arguments:volume", "EService:Market in cancel_only mode"],
)
def test_a_definitive_refusal_is_refused_with_krakens_code(error):
    result = _order_with(httpx.Response(200, json={"error": [error], "result": {}}))

    assert result == Placement(PlacementOutcome.REFUSED, error=error)


@pytest.mark.parametrize(
    "errors",
    [["EService:Unavailable"], ["EService:Busy"], ["EGeneral:Internal error"], ["EBrandNew:Never seen"]],
)
def test_any_other_code_is_unknown(errors):
    result = _order_with(httpx.Response(200, json={"error": errors, "result": {}}))

    assert result == Placement(PlacementOutcome.UNKNOWN)


def test_a_server_error_is_unknown():
    assert _order_with(httpx.Response(502)).outcome is PlacementOutcome.UNKNOWN


def test_a_timeout_is_unknown():
    def handler(request):
        raise httpx.ReadTimeout("timed out")

    result = _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("100"), cl_ord_id="abc123", in_quote=True
    )

    assert result.outcome is PlacementOutcome.UNKNOWN


def test_an_answer_that_is_not_json_is_unknown():
    assert _order_with(httpx.Response(200, content=b"<html>")).outcome is PlacementOutcome.UNKNOWN


def test_an_answer_with_no_txid_is_unknown():
    """Kraken said nothing went wrong and named no order. That is not evidence of absence."""
    assert _order_with(_ok({"descr": {}})).outcome is PlacementOutcome.UNKNOWN


def test_a_secret_that_does_not_decode_sends_nothing_and_is_refused():
    calls = []

    def handler(request):
        calls.append(request)
        return _ok({"txid": ["OTX"]})

    client = _client(handler, credentials=Credentials(api_key="K", api_secret="not base64 at all!"))
    result = client.add_order(pair="XXBTZEUR", side="buy", volume=D("100"), cl_ord_id="abc123", in_quote=True)

    assert calls == []
    assert result.outcome is PlacementOutcome.REFUSED


def test_an_order_on_a_client_with_no_key_is_a_programming_error():
    client = _client(lambda request: _ok({}), credentials=None)

    with pytest.raises(MissingCredentials):
        client.add_order(pair="XXBTZEUR", side="buy", volume=D("100"), cl_ord_id="abc123")


def test_a_refused_order_is_logged_without_the_key(caplog):
    with caplog.at_level(logging.DEBUG, logger="coinpilot.exchange"):
        _order_with(httpx.Response(200, json={"error": ["EOrder:Insufficient funds"], "result": {}}))

    assert "Insufficient funds" in caplog.text
    assert CREDENTIALS.api_key not in caplog.text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/exchange -q`
Expected: FAIL — `ImportError: cannot import name 'is_definitive_refusal'` and `ImportError: cannot import name 'Placement'`.

- [ ] **Step 3: Add the value objects**

In `exchange/types.py`, append:

```python
class PlacementOutcome(StrEnum):
    """What one `AddOrder` call achieved (spec §9.4).

    `UNKNOWN` is the lost answer of spec §9.2: the order may exist. `REFUSED` is Kraken
    saying it does not.
    """

    SENT = "sent"
    VALIDATED = "validated"
    REFUSED = "refused"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Placement:
    outcome: PlacementOutcome
    txid: str | None = None
    # Kraken's first error code, on a refusal only.
    error: str | None = None
```

- [ ] **Step 4: Add the refusal list**

In `exchange/orders.py`, change `from collections.abc import Callable` to
`from collections.abc import Callable, Sequence`, and append:

```python
# Spec §9.4. Closed on purpose: a code not listed here, including one Kraken adds later,
# reads as unknown. Reading a new code as a refusal is how a duplicate order happens.
DEFINITIVE_REFUSALS = (
    "EOrder:",
    "EGeneral:Invalid arguments",
    "EGeneral:Permission denied",
    "EAPI:",
    "EService:Market in cancel_only mode",
    "EService:Market in post_only mode",
    "EService:Market in limit_only mode",
)


def is_definitive_refusal(errors: Sequence[str]) -> bool:
    """Every code Kraken returned says the order was not accepted.

    One code that does not is enough to make the answer unknown, and so is no code at all.
    """
    return bool(errors) and all(str(error).startswith(DEFINITIVE_REFUSALS) for error in errors)
```

- [ ] **Step 5: Split the private call, and place an order**

In `exchange/client.py`:

1. Add `from exchange.orders import is_definitive_refusal` to the imports, and change the
   import from `exchange.types` to
   `from exchange.types import Credentials, PairMeta, Placement, PlacementOutcome`.
2. After `class KeyLockedOut`, add:

```python
class SecretUnreadable(Exception):
    """The secret is not base64, so no request could be signed, and none was sent."""
```

3. Replace `_private` with `_call_private` and a new `_private`:

```python
    def _call_private(self, endpoint: str, payload: Mapping[str, str] | None = None) -> dict:
        """One signed call. Raises on every failure; the callers decide what each means."""
        credentials = self._credentials
        if credentials is None:
            raise MissingCredentials(endpoint)
        path = f"/0/private/{endpoint}"
        self._limiter.wait_turn(credentials.api_key)
        nonce = self._limiter.next_nonce(credentials.api_key)
        body = encode_body({"nonce": nonce, **dict(payload or {})})
        try:
            signature = sign(path, nonce, body, credentials.api_secret)
        except ValueError:
            # Kraken issues base64 secrets, so one that does not decode was mistyped.
            raise SecretUnreadable(endpoint) from None
        headers = {
            "API-Key": credentials.api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._http.post(path, content=body, headers=headers)
        response.raise_for_status()
        return self._unwrap(response.json())

    def _private(
        self,
        endpoint: str,
        payload: Mapping[str, str] | None = None,
        *,
        refusals: bool = False,
    ) -> dict | None:
        if self._credentials is None:
            raise MissingCredentials(endpoint)
        return self._safely(lambda: self._call_private(endpoint, payload), endpoint, refusals=refusals)
```

4. In `_safely`, replace the `except KeyRefused:` branch with:

```python
        except SecretUnreadable:
            if refusals:
                logger.warning("kraken %s refused the key", endpoint)
                raise KeyRefused(endpoint) from None
            logger.warning("kraken %s failed: the secret does not decode", endpoint)
            return None
```

5. Replace `add_order` with:

```python
    def add_order(
        self,
        pair: str,
        side: str,
        volume: Decimal,
        cl_ord_id: str,
        *,
        in_quote: bool = False,
        validate: bool = False,
    ) -> Placement:
        """A market order, always, and what became of the request.

        `in_quote=True` makes `volume` an amount of the quote currency and takes the fee
        in the asset bought (`viqc`, `fcib`), so the order spends exactly that amount
        (spec §9.1). Kraken accepts it on buys only. `validate=True` has Kraken check the
        order and never trade it.

        Never `None`. This is the one call where *Kraken refused* and *nobody knows* must be
        told apart: the first leaves nothing at Kraken, the second may have bought (§9.4).
        """
        if in_quote and side != "buy":
            raise ValueError("kraken takes an amount in the quote currency for buys only")
        payload = {
            "pair": pair,
            "type": side,
            "ordertype": "market",
            "volume": format_decimal(volume),
            "cl_ord_id": cl_ord_id,
        }
        if in_quote:
            payload["oflags"] = "viqc,fcib"
        if validate:
            payload["validate"] = "true"

        try:
            result = self._call_private("AddOrder", payload)
        except MissingCredentials:
            raise
        except SecretUnreadable:
            logger.warning("kraken AddOrder not sent: the secret does not decode")
            return Placement(PlacementOutcome.REFUSED, error="the secret does not decode")
        except KrakenError as exc:
            if is_definitive_refusal(exc.errors):
                logger.warning("kraken AddOrder refused: %s", self._redact(", ".join(exc.errors)))
                return Placement(PlacementOutcome.REFUSED, error=str(exc.errors[0]))
            logger.warning("kraken AddOrder answer unknown: %s", self._redact(str(exc)))
            return Placement(PlacementOutcome.UNKNOWN)
        except Exception as exc:
            logger.warning("kraken AddOrder answer unknown: %s", self._redact(str(exc)))
            return Placement(PlacementOutcome.UNKNOWN)

        if validate:
            return Placement(PlacementOutcome.VALIDATED)
        txids = result.get("txid") if isinstance(result, dict) else None
        if isinstance(txids, list) and txids:
            return Placement(PlacementOutcome.SENT, txid=str(txids[0]))
        logger.warning("kraken AddOrder answered with no txid")
        return Placement(PlacementOutcome.UNKNOWN)
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit -q`
Expected: PASS, every test, including the phase 3 and 4 key tests that go through `_private`.

- [ ] **Step 7: Commit**

```bash
git add exchange tests/unit/exchange
git commit -m "feat(exchange): place a buy in fiat, and tell a refusal from an unknown answer"
```

---

### Task 4: Reading an order by its txid

**Files:**
- Modify: `exchange/types.py` (`OrderLookup`)
- Modify: `exchange/orders.py`
- Modify: `exchange/client.py`
- Test: `tests/unit/exchange/test_find_order.py`, `tests/unit/exchange/test_client.py`

**Interfaces:**
- Consumes: `OrderLookup`, `ABSENT`, `_match` (phase 3).
- Produces:
  - `OrderLookup.cost: Decimal` (last field)
  - `KrakenClient.query_orders(txid: str) -> dict[str, dict] | None`
  - `find_order_by_txid(client, txid: str) -> OrderLookup | None` — `None` when unread, never `ABSENT`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/exchange/test_find_order.py`, add `"cost": "100.0",` to the dict `_order`
returns, add `find_order_by_txid` to the import from `exchange.orders`, and append:

```python
class FakeQuery:
    def __init__(self, answer):
        self._answer = answer
        self.asked = []

    def query_orders(self, txid):
        self.asked.append(txid)
        return self._answer


def test_an_order_is_read_by_its_txid_with_what_it_cost():
    client = FakeQuery({"OTX-1": _order("closed")})

    found = find_order_by_txid(client, "OTX-1")

    assert client.asked == ["OTX-1"]
    assert found.txid == "OTX-1"
    assert found.status == ExchangeOrderStatus.CLOSED
    assert found.cost == D("100.0")
    assert found.volume_executed == D("0.00212765")


def test_a_txid_that_could_not_be_read_is_unknown():
    assert find_order_by_txid(FakeQuery(None), "OTX-1") is None


def test_an_answer_without_the_txid_is_unknown_not_absent():
    """Kraken named this order. An answer that leaves it out proves nothing."""
    assert find_order_by_txid(FakeQuery({}), "OTX-1") is None


def test_a_lookup_by_client_id_carries_the_cost_too():
    found = find_order_by_cl_ord_id(FakeClient({}, {"OTX-2": _order("closed")}), CL_ORD_ID)

    assert found.cost == D("100.0")
```

In `tests/unit/exchange/test_client.py`, append:

```python
def test_an_order_is_queried_by_its_txid():
    seen = {}

    def handler(request):
        seen["form"] = parse_qs(request.content.decode())
        return _ok({"OTX-1": {"status": "closed", "cl_ord_id": "abc123"}})

    orders = _client(handler).query_orders("OTX-1")

    assert seen["form"]["txid"] == ["OTX-1"]
    assert orders["OTX-1"]["status"] == "closed"


def test_a_query_that_fails_is_none():
    assert _client(lambda request: httpx.Response(502)).query_orders("OTX-1") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/exchange -q`
Expected: FAIL — `ImportError: cannot import name 'find_order_by_txid'`.

- [ ] **Step 3: Implement**

In `exchange/types.py`, in `OrderLookup`, after `fee: Decimal`, add:

```python
    # As Kraken reports it. Whether a buy in fiat reports it in the quote currency is
    # verified on the first real order (phase 5 plan).
    cost: Decimal
```

In `exchange/orders.py`, replace `_match` and `ABSENT` with:

```python
def _lookup(txid: str, order: dict) -> OrderLookup:
    return OrderLookup(
        txid=txid,
        status=map_order_status(order.get("status")),
        volume=_as_decimal(order.get("vol")),
        volume_executed=_as_decimal(order.get("vol_exec")),
        price=_as_decimal(order.get("price")),
        fee=_as_decimal(order.get("fee")),
        cost=_as_decimal(order.get("cost")),
    )


def _match(orders: dict[str, dict], cl_ord_id: str) -> OrderLookup | None:
    """The first order that echoes the id we asked for, as a value object."""
    for txid, order in orders.items():
        if order.get("cl_ord_id") == cl_ord_id:
            return _lookup(txid, order)
    return None


ABSENT = OrderLookup(
    txid=None, status=None, volume=ZERO, volume_executed=ZERO, price=ZERO, fee=ZERO, cost=ZERO
)
```

and append:

```python
def find_order_by_txid(client, txid: str) -> OrderLookup | None:
    """An order whose txid Kraken gave us.

    `None` when it could not be read, and never `ABSENT`: Kraken named this order, so it
    exists, and an answer that leaves it out is still unknown.
    """
    orders = client.query_orders(txid)
    if not orders or txid not in orders:
        return None
    return _lookup(txid, orders[txid])
```

In `exchange/client.py`, after `closed_orders`, add:

```python
    def query_orders(self, txid: str) -> dict[str, dict] | None:
        """Orders by Kraken's own id, open or closed."""
        raw = self._private("QueryOrders", {"txid": txid})
        if raw is None:
            return None
        return {name: entry for name, entry in raw.items() if isinstance(entry, dict)}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit -q`
Expected: PASS, every test.

- [ ] **Step 5: Commit**

```bash
git add exchange tests/unit/exchange
git commit -m "feat(exchange): read an order by its txid, with what it cost"
```

---

### Task 5: One evaluation per user at a time

**Files:**
- Create: `core/db/locks.py`
- Modify: `api/context.py`, `api/main.py`
- Modify: `tests/integration/conftest.py` (`FakeLocks`, `user_locks`, `app_context`)
- Modify: `tests/unit/api/test_database_errors.py` (the `AppContext` it builds)
- Test: `tests/integration/test_locks.py`

**Interfaces:**
- Produces:
  - `lock_key(user_id: uuid.UUID) -> int`
  - `advisory_user_lock(engine: Engine, user_id: uuid.UUID) -> ContextManager[bool]` — yields whether it was taken; never waits
  - `AppContext.user_lock: Callable[[uuid.UUID], AbstractContextManager[bool]]`
  - Test fixture `user_locks: FakeLocks` with a `held: set[uuid.UUID]`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_locks.py`:

```python
import uuid

import pytest

from core.db.locks import advisory_user_lock, lock_key


def test_a_second_evaluation_of_the_same_user_is_refused(engine):
    """Two at once could spend the same cash twice (spec §9.6)."""
    user_id = uuid.uuid4()

    with advisory_user_lock(engine, user_id) as first, advisory_user_lock(engine, user_id) as second:
        assert first is True
        assert second is False


def test_the_lock_is_released_when_the_evaluation_ends(engine):
    user_id = uuid.uuid4()
    with advisory_user_lock(engine, user_id):
        pass

    with advisory_user_lock(engine, user_id) as again:
        assert again is True


def test_the_lock_is_released_when_the_evaluation_raises(engine):
    user_id = uuid.uuid4()
    with pytest.raises(RuntimeError), advisory_user_lock(engine, user_id):
        raise RuntimeError("the executor failed")

    with advisory_user_lock(engine, user_id) as again:
        assert again is True


def test_two_users_do_not_wait_on_each_other(engine):
    with advisory_user_lock(engine, uuid.uuid4()) as alice, advisory_user_lock(engine, uuid.uuid4()) as bob:
        assert alice is True
        assert bob is True


def test_the_key_is_stable_and_fits_a_bigint():
    user_id = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")

    assert lock_key(user_id) == lock_key(user_id)
    assert -(2**63) <= lock_key(user_id) < 2**63
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_locks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.db.locks'`.

- [ ] **Step 3: Implement the lock**

Create `core/db/locks.py`:

```python
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
```

- [ ] **Step 4: Give the application its lock**

In `api/context.py`, add `import uuid` to the imports, and in `AppContext`, after `catalog`, add:

```python
    # One evaluation per user at a time (spec §9.6). Yields whether the lock was taken.
    user_lock: Callable[[uuid.UUID], AbstractContextManager[bool]]
```

In `api/main.py`, add `from functools import partial` and
`from core.db.locks import advisory_user_lock`, change
`from core.db.session import configure, session_scope` to
`from core.db.session import configure, get_engine, session_scope`, and in the
`AppContext(...)` call, after `catalog=...`, add:

```python
        user_lock=partial(advisory_user_lock, get_engine()),
```

In `tests/integration/conftest.py`, after the `FakeGoogle` class, add:

```python
class FakeLocks:
    """The per-user lock, without a second connection. A test puts a user in `held` to
    stand for an evaluation already running."""

    def __init__(self):
        self.held = set()

    @contextmanager
    def __call__(self, user_id):
        if user_id in self.held:
            yield False
            return
        self.held.add(user_id)
        try:
            yield True
        finally:
            self.held.discard(user_id)


@pytest.fixture
def user_locks() -> FakeLocks:
    return FakeLocks()
```

Add `user_locks: FakeLocks` to the parameters of the `app_context` fixture, and in its
`AppContext(...)` call, after `catalog=...`, add `user_lock=user_locks,`.

In `tests/unit/api/test_database_errors.py`, add `from contextlib import contextmanager, nullcontext`
(replacing the existing `contextmanager` import), and in the `AppContext(...)` call, after
`catalog=...`, add:

```python
        user_lock=lambda user_id: nullcontext(True),
```

- [ ] **Step 5: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test.

- [ ] **Step 6: Commit**

```bash
git add core/db/locks.py api/context.py api/main.py tests
git commit -m "feat(core): one evaluation per user at a time, on an advisory lock"
```

---

### Task 6: What became of an order

**Files:**
- Create: `core/settlement.py`
- Test: `tests/integration/test_settlement.py`

**Interfaces:**
- Consumes: `mark_sent`, `mark_filled(cost=)`, `mark_failed(error=)`, `pending_orders` (Task 1); `find_order_by_txid` (Task 4); `find_order_by_cl_ord_id`, `ABSENT` (phase 3).
- Produces:
  - `ABSENCE_GRACE: timedelta` (two minutes)
  - `settle(session, cl_ord_id: str, lookup: OrderLookup | None) -> OrderStatus`
  - `Resolution(clear: bool, messages: tuple[str, ...])`
  - `resolve_pending(sessions, private, user_id: uuid.UUID, now: datetime) -> Resolution`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_settlement.py`:

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from core.db.orders import get_by_cl_ord_id, mark_sent, record_attempt
from core.db.types import OrderReason, OrderStatus
from core.settlement import ABSENCE_GRACE, resolve_pending, settle
from engine.types import Side
from exchange.orders import ABSENT
from exchange.types import ExchangeOrderStatus, OrderLookup

D = Decimal
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LONG_AGO = NOW - ABSENCE_GRACE - timedelta(seconds=1)


def _attempt(db_session, user, cl_ord_id, attempted_at=LONG_AGO, txid=None):
    record_attempt(
        db_session,
        user.id,
        cl_ord_id,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
        attempted_at=attempted_at,
    )
    if txid is not None:
        mark_sent(db_session, cl_ord_id, txid)


def _seen(status, executed="0.002", txid="OTX-1"):
    return OrderLookup(
        txid=txid,
        status=status,
        volume=D("0.002"),
        volume_executed=D(executed),
        price=D("50000"),
        fee=D("0.000008"),
        cost=D("100"),
    )


class FakePrivate:
    """Answers the three lookups and records which were asked."""

    def __init__(self, by_txid=None, open_=None, closed=None):
        self.by_txid = {} if by_txid is None else by_txid
        self.open = {} if open_ is None else open_
        self.closed = {} if closed is None else closed
        self.asked = []

    def query_orders(self, txid):
        self.asked.append(("query", txid))
        return self.by_txid

    def open_orders(self, cl_ord_id=None):
        self.asked.append(("open", cl_ord_id))
        return self.open

    def closed_orders(self, cl_ord_id=None):
        self.asked.append(("closed", cl_ord_id))
        return self.closed


def test_a_closed_order_is_filled_with_what_it_cost(db_session, make_user):
    _attempt(db_session, make_user(), "cl-1")

    assert settle(db_session, "cl-1", _seen(ExchangeOrderStatus.CLOSED)) is OrderStatus.FILLED
    order = get_by_cl_ord_id(db_session, "cl-1")
    assert (order.txid, order.cost, order.executed_volume) == ("OTX-1", D("100"), D("0.002"))


def test_a_canceled_order_that_executed_partly_is_filled_with_what_executed(db_session, make_user):
    """Kraken's market price protection can cancel the rest of a market order."""
    _attempt(db_session, make_user(), "cl-2")

    status = settle(db_session, "cl-2", _seen(ExchangeOrderStatus.CANCELED, executed="0.001"))

    assert status is OrderStatus.FILLED
    assert get_by_cl_ord_id(db_session, "cl-2").executed_volume == D("0.001")


def test_a_canceled_order_with_nothing_executed_failed(db_session, make_user):
    _attempt(db_session, make_user(), "cl-3")

    assert settle(db_session, "cl-3", _seen(ExchangeOrderStatus.CANCELED, executed="0")) is OrderStatus.FAILED
    assert get_by_cl_ord_id(db_session, "cl-3").error == "canceled with nothing executed"


def test_an_order_still_open_stays_pending_and_keeps_its_txid(db_session, make_user):
    _attempt(db_session, make_user(), "cl-4")

    assert settle(db_session, "cl-4", _seen(ExchangeOrderStatus.OPEN, executed="0")) is OrderStatus.PENDING
    assert get_by_cl_ord_id(db_session, "cl-4").txid == "OTX-1"


def test_a_status_word_nobody_modelled_stays_pending(db_session, make_user):
    _attempt(db_session, make_user(), "cl-5")

    assert settle(db_session, "cl-5", _seen(ExchangeOrderStatus.UNKNOWN)) is OrderStatus.PENDING


def test_a_lookup_that_failed_decides_nothing(db_session, make_user):
    _attempt(db_session, make_user(), "cl-6")

    assert settle(db_session, "cl-6", None) is OrderStatus.PENDING


def test_a_genuine_absence_failed(db_session, make_user):
    _attempt(db_session, make_user(), "cl-7")

    assert settle(db_session, "cl-7", ABSENT) is OrderStatus.FAILED


def test_nothing_pending_is_clear_and_asks_kraken_nothing(app_context, make_user):
    private = FakePrivate()

    assert resolve_pending(app_context.sessions, private, make_user().id, NOW).clear is True
    assert private.asked == []


def test_a_sent_order_is_resolved_by_its_txid(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-8", txid="OTX-8")
    private = FakePrivate(by_txid={"OTX-8": {"status": "closed", "vol_exec": "0.002", "cost": "100"}})

    resolution = resolve_pending(app_context.sessions, private, user.id, NOW)

    assert resolution.clear is True
    assert private.asked == [("query", "OTX-8")]
    assert get_by_cl_ord_id(db_session, "cl-8").status == OrderStatus.FILLED


def test_an_order_whose_answer_was_lost_is_found_by_its_client_id(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-9")
    closed = {"OTX-9": {"status": "closed", "cl_ord_id": "cl-9", "vol_exec": "0.002", "cost": "100"}}

    resolution = resolve_pending(app_context.sessions, FakePrivate(closed=closed), user.id, NOW)

    assert resolution.clear is True
    assert get_by_cl_ord_id(db_session, "cl-9").txid == "OTX-9"


def test_an_old_absence_fails_the_attempt_so_the_next_plan_retries(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-10")

    resolution = resolve_pending(app_context.sessions, FakePrivate(), user.id, NOW)

    assert resolution.clear is True
    assert get_by_cl_ord_id(db_session, "cl-10").status == OrderStatus.FAILED


def test_an_absence_read_too_soon_is_not_believed(app_context, db_session, make_user):
    """Kraken may not list an order it accepted a moment ago. Failing it now is how a
    lost answer turns into a duplicate order."""
    user = make_user()
    _attempt(db_session, user, "cl-11", attempted_at=NOW - timedelta(seconds=30))

    resolution = resolve_pending(app_context.sessions, FakePrivate(), user.id, NOW)

    assert resolution.clear is False
    assert get_by_cl_ord_id(db_session, "cl-11").status == OrderStatus.PENDING


def test_one_unknown_order_keeps_the_user_unresolved_and_the_rest_still_resolve(
    app_context, db_session, make_user
):
    user = make_user()
    _attempt(db_session, user, "cl-12", txid="OTX-12")
    _attempt(db_session, user, "cl-13")

    class HalfDown(FakePrivate):
        def open_orders(self, cl_ord_id=None):
            return None

    private = HalfDown(by_txid={"OTX-12": {"status": "closed", "vol_exec": "0.002", "cost": "100"}})
    resolution = resolve_pending(app_context.sessions, private, user.id, NOW)

    assert resolution.clear is False
    assert get_by_cl_ord_id(db_session, "cl-12").status == OrderStatus.FILLED
    assert get_by_cl_ord_id(db_session, "cl-13").status == OrderStatus.PENDING
    assert any("cl-13" in message for message in resolution.messages)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_settlement.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.settlement'`.

- [ ] **Step 3: Implement**

Create `core/settlement.py`:

```python
"""What became of an order: reading its fill, and resolving what is still unknown.

Spec §9.2 and §9.5. Used before every evaluation, and right after an order is sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import core.database as db
from core.db.types import OrderStatus
from engine.types import ZERO
from exchange.orders import find_order_by_cl_ord_id, find_order_by_txid
from exchange.types import ExchangeOrderStatus, OrderLookup

# Kraken may not list an order it accepted a moment ago. An absence read sooner than this
# after the attempt is not believed: failing the row would let the next plan buy again.
ABSENCE_GRACE = timedelta(minutes=2)

_FINISHED = (ExchangeOrderStatus.CLOSED, ExchangeOrderStatus.CANCELED)


def settle(session: Session, cl_ord_id: str, lookup: OrderLookup | None) -> OrderStatus:
    """Write down what Kraken says about one order, and return the row's status.

    `None` is a lookup that failed: nothing is decided. `ABSENT` is evidence the order
    does not exist. A finished order is `FILLED` if anything executed, in whatever unit
    Kraken reports it.
    """
    if lookup is None:
        return OrderStatus.PENDING
    if lookup.txid is None:
        db.mark_failed(session, cl_ord_id)
        return OrderStatus.FAILED
    if lookup.status in _FINISHED:
        if lookup.volume_executed > ZERO:
            db.mark_filled(
                session,
                cl_ord_id,
                txid=lookup.txid,
                executed_volume=lookup.volume_executed,
                executed_price=lookup.price,
                fee=lookup.fee,
                cost=lookup.cost,
            )
            return OrderStatus.FILLED
        db.mark_failed(session, cl_ord_id, error=f"{lookup.status.value} with nothing executed")
        return OrderStatus.FAILED
    # Open, pending, or a word nobody modelled: it exists, and it is not finished.
    db.mark_sent(session, cl_ord_id, lookup.txid)
    return OrderStatus.PENDING


@dataclass(frozen=True)
class Resolution:
    clear: bool
    messages: tuple[str, ...]


def resolve_pending(
    sessions: Callable[[], AbstractContextManager[Session]],
    private,
    user_id: uuid.UUID,
    now: datetime,
) -> Resolution:
    """Resolve every `PENDING` attempt of one user. `clear` is false while any is unknown.

    A row with a txid is read by it: the order exists. A row without one is looked up by
    its client id, and an absence counts only once `ABSENCE_GRACE` has passed.
    """
    with sessions() as session:
        pending = [(o.cl_ord_id, o.txid, o.attempted_at) for o in db.pending_orders(session, user_id)]

    clear = True
    messages: list[str] = []
    for cl_ord_id, txid, attempted_at in pending:
        if txid is not None:
            lookup = find_order_by_txid(private, txid)
        else:
            lookup = find_order_by_cl_ord_id(private, cl_ord_id)
        if lookup is not None and lookup.txid is None and now - attempted_at < ABSENCE_GRACE:
            clear = False
            messages.append(f"order {cl_ord_id}: not listed yet; absence is believed after the grace period")
            continue
        with sessions() as session:
            status = settle(session, cl_ord_id, lookup)
        if status is OrderStatus.PENDING:
            clear = False
            messages.append(f"order {cl_ord_id}: still unresolved")
        else:
            messages.append(f"order {cl_ord_id}: resolved as {status.value}")
    return Resolution(clear=clear, messages=tuple(messages))
```

- [ ] **Step 4: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test.

- [ ] **Step 5: Commit**

```bash
git add core/settlement.py tests/integration/test_settlement.py
git commit -m "feat(core): read an order's fill, and resolve what is still unknown"
```

---

### Task 7: The executor

**Files:**
- Create: `core/execution.py`
- Modify: `tests/integration/conftest.py` (`FakeKraken` learns orders)
- Modify: `tests/unit/core/test_layering.py`
- Test: `tests/integration/test_execution.py`

**Interfaces:**
- Consumes: everything above; `read_portfolio`, `PortfolioUnavailable` (phase 4); `reconcile`, `Policy`, `CashPolicy` (phase 1); `plain_amount` (phase 4).
- Produces:
  - `invest(context: ExecutionContext, user_id: uuid.UUID, *, preview: bool = False) -> InvestResult`
  - `EvaluationBusy(Exception)`, `NotReady(Exception)` (message is safe to show)
  - `EvaluationStatus(StrEnum)`: `DONE`, `NOTHING_TO_DO`, `STOPPED`, `UNRESOLVED`, `KRAKEN_UNAVAILABLE`, `PREVIEW`, `ERROR`
  - `LegStatus(StrEnum)`: `FILLED`, `FAILED`, `PENDING`, `SKIPPED`, `VALIDATED`, `REJECTED`, `UNCHECKED`
  - `LegResult(asset, pair, amount_fiat, minimum_fiat, status, cl_ord_id=None, txid=None, cost=None, executed_volume=None, executed_price=None, fee=None, error=None, note=None)`
  - `InvestResult(status, preview, legs: tuple[LegResult, ...] = (), messages: tuple[str, ...] = ())`

- [ ] **Step 1: Teach the fake Kraken to take orders**

In `tests/integration/conftest.py`, add `from decimal import Decimal` to the imports. In
`FakeKraken.__init__`, after `self.calls = []`, add:

```python
        # Orders Kraken knows, by txid, as Kraken reports them.
        self.orders = {}
        # Every AddOrder form, validated ones included.
        self.placed = []
        # The error list the next AddOrder answers with. Empty: it is accepted.
        self.add_order_errors = []
        # None: answer normally. "dropped": fail the HTTP answer and execute nothing.
        # "executed": execute the order, then fail the HTTP answer — the lost response.
        self.lose_add_order = None
        # The status a new order is reported with when it is read.
        self.fill_status = "closed"
        # Called with each AddOrder form, before Kraken acts on it.
        self.on_add_order = None
```

In `FakeKraken.__call__`, before the final `return httpx.Response(404)`, add:

```python
        if endpoint == "AddOrder":
            return self._add_order(dict(urllib.parse.parse_qsl(request.content.decode())))
        if endpoint == "QueryOrders":
            txid = dict(urllib.parse.parse_qsl(request.content.decode())).get("txid")
            if txid not in self.orders:
                return httpx.Response(200, json={"error": ["EOrder:Invalid order"], "result": {}})
            return _ok({txid: self.orders[txid]})
        if endpoint in ("OpenOrders", "ClosedOrders"):
            wanted = dict(urllib.parse.parse_qsl(request.content.decode())).get("cl_ord_id")
            is_open = endpoint == "OpenOrders"
            found = {
                txid: order
                for txid, order in self.orders.items()
                if (order["status"] in ("open", "pending")) == is_open
                and (wanted is None or order["cl_ord_id"] == wanted)
            }
            return _ok({"open" if is_open else "closed": found})
```

and add this method to `FakeKraken`:

```python
    def _add_order(self, form):
        self.placed.append(form)
        if self.on_add_order is not None:
            self.on_add_order(form)
        if self.add_order_errors:
            return httpx.Response(200, json={"error": self.add_order_errors, "result": {}})
        if form.get("validate") == "true":
            return _ok({"descr": {"order": f"buy {form['volume']} {form['pair']} @ market"}})
        if self.lose_add_order == "dropped":
            return httpx.Response(503)
        txid = f"OTX{len(self.orders) + 1:03d}-AAAAA-BBBBBB"
        spent = Decimal(form["volume"])
        price = Decimal(self.prices[form["pair"]])
        filled = self.fill_status == "closed"
        self.orders[txid] = {
            "status": self.fill_status,
            "cl_ord_id": form["cl_ord_id"],
            "oflags": form.get("oflags", ""),
            "vol": form["volume"],
            "vol_exec": str((spent / price).quantize(Decimal("0.00000001"))) if filled else "0",
            "cost": str(spent) if filled else "0",
            "fee": str((spent * Decimal("0.004") / price).quantize(Decimal("0.00000001"))) if filled else "0",
            "price": str(price) if filled else "0",
        }
        if self.lose_add_order == "executed":
            return httpx.Response(503)
        return _ok({"descr": {"order": f"buy {form['volume']} {form['pair']} @ market"}, "txid": [txid]})
```

- [ ] **Step 2: Write the failing tests**

Create `tests/integration/test_execution.py`:

```python
import base64
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from core.db.orders import get_by_cl_ord_id, list_orders
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import latest_snapshot, list_evaluations
from core.db.types import OrderStatus
from core.db.users import save_credentials
from core.execution import (
    EvaluationBusy,
    EvaluationStatus,
    LegStatus,
    NotReady,
    invest,
)
from core.settlement import ABSENCE_GRACE
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
XBT_ETH = (("XBT", "XXBTZEUR", "60"), ("ETH", "XETHZEUR", "40"))


@pytest.fixture
def ready(app_context, db_session, make_user, fake_kraken):
    """A user with EUR, the weights given, a sealed key, and 1000 EUR of free cash."""

    def _ready(weights=XBT_ETH, cash="1000"):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        for asset, pair, pct in weights:
            upsert_asset(db_session, user.id, asset=asset, pair=pair, target_pct=D(pct))
        sealed = app_context.cipher.seal(user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now())
        fake_kraken.balance = {"ZEUR": cash}
        return user

    return _ready


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_free_cash_is_invested_pro_rata_in_fiat(app_context, fake_kraken, ready):
    user = ready()

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert [(leg.asset, leg.status) for leg in result.legs] == [
        ("ETH", LegStatus.FILLED),
        ("XBT", LegStatus.FILLED),
    ]
    forms = {form["pair"]: form for form in _sent(fake_kraken)}
    assert D(forms["XXBTZEUR"]["volume"]) == D("600")
    assert D(forms["XETHZEUR"]["volume"]) == D("400")
    assert {form["oflags"] for form in forms.values()} == {"viqc,fcib"}
    assert {form["type"] for form in forms.values()} == {"buy"}


def test_every_order_is_in_the_ledger_with_what_it_cost(app_context, db_session, fake_kraken, ready):
    user = ready()

    invest(app_context, user.id)

    orders = {order.asset: order for order in list_orders(db_session, user.id)}
    assert orders["XBT"].status == OrderStatus.FILLED
    assert orders["XBT"].requested_fiat == D("600")
    assert orders["XBT"].cost == D("600")
    assert orders["XBT"].txid is not None
    assert orders["XBT"].attempted_at == app_context.now()


def test_the_evaluation_and_a_snapshot_are_recorded(app_context, db_session, ready):
    user = ready()

    invest(app_context, user.id)

    (evaluation,) = list_evaluations(db_session, user.id)
    assert evaluation.status == "DONE"
    assert "XBT" in evaluation.log_messages
    assert latest_snapshot(db_session, user.id).cash == D("1000")


def test_the_cash_target_is_kept(app_context, fake_kraken, ready):
    """XBT at 50 % leaves a 50 % cash target: half of 1000 stays as cash."""
    user = ready(weights=(("XBT", "XXBTZEUR", "50"),))

    invest(app_context, user.id)

    (form,) = _sent(fake_kraken)
    assert D(form["volume"]) == D("500")


def test_drift_policy_spends_on_what_is_furthest_behind(app_context, db_session, fake_kraken, ready):
    """600 EUR of XBT and 400 EUR of cash at 50/50: all of the cash goes to ETH."""
    user = ready(weights=(("XBT", "XXBTZEUR", "50"), ("ETH", "XETHZEUR", "50")), cash="400")
    fake_kraken.balance = {"ZEUR": "400", "XXBT": "0.012"}
    update_settings(db_session, user.id, cash_rebalance_enabled=True)

    invest(app_context, user.id)

    (form,) = _sent(fake_kraken)
    assert (form["pair"], D(form["volume"])) == ("XETHZEUR", D("400"))


def test_no_free_cash_is_nothing_to_do(app_context, fake_kraken, ready):
    user = ready(cash="0")

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert fake_kraken.placed == []


def test_a_leg_under_krakens_minimum_is_skipped_and_the_rest_is_sent(app_context, fake_kraken, ready):
    """6 EUR at 60/40: XBT gets 3.60, under 0.0001 XBT at 50 000 = 5. ETH gets 2.40, over 0.5."""
    user = ready(cash="6")

    result = invest(app_context, user.id)

    legs = {leg.asset: leg for leg in result.legs}
    assert legs["XBT"].status is LegStatus.SKIPPED
    assert legs["XBT"].minimum_fiat == D("5")
    assert "below the minimum" in legs["XBT"].note
    assert legs["ETH"].status is LegStatus.FILLED
    assert [form["pair"] for form in _sent(fake_kraken)] == ["XETHZEUR"]


def test_a_floor_of_the_users_own_skips_what_kraken_would_take(app_context, db_session, fake_kraken, ready):
    user = ready(cash="15")
    update_settings(db_session, user.id, min_order_fiat=D("10"))

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert {leg.status for leg in result.legs} == {LegStatus.SKIPPED}
    assert fake_kraken.placed == []


def test_a_refused_leg_fails_with_krakens_code_and_the_others_are_still_sent(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.add_order_errors = ["EOrder:Insufficient funds"]

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert {leg.status for leg in result.legs} == {LegStatus.FAILED}
    assert {leg.error for leg in result.legs} == {"EOrder:Insufficient funds"}
    assert len(_sent(fake_kraken)) == 2


def test_after_an_unknown_answer_no_further_leg_is_sent(app_context, db_session, fake_kraken, ready):
    user = ready()
    fake_kraken.lose_add_order = "dropped"

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.STOPPED
    assert [leg.status for leg in result.legs] == [LegStatus.PENDING, LegStatus.SKIPPED]
    assert len(_sent(fake_kraken)) == 1
    (order,) = list_orders(db_session, user.id)
    assert (order.status, order.txid) == (OrderStatus.PENDING, None)


def test_the_next_investment_waits_out_the_grace_then_retries_an_order_that_never_arrived(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "dropped"
    invest(app_context, user.id)
    fake_kraken.lose_add_order = None

    soon = invest(app_context, user.id)
    later = invest(replace(app_context, now=lambda: app_context.now() + ABSENCE_GRACE), user.id)

    assert soon.status is EvaluationStatus.UNRESOLVED
    assert later.status is EvaluationStatus.DONE
    assert sorted(o.status for o in list_orders(db_session, user.id)) == [
        OrderStatus.FAILED,
        OrderStatus.FILLED,
        OrderStatus.FILLED,
    ]


def test_an_order_that_executed_but_whose_answer_was_lost_is_adopted_not_repeated(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "executed"
    invest(app_context, user.id)
    fake_kraken.lose_add_order = None
    fake_kraken.balance = {"ZEUR": "0"}

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    (order,) = list_orders(db_session, user.id)
    assert order.status == OrderStatus.FILLED
    assert len(_sent(fake_kraken)) == 1


def test_an_order_not_yet_filled_is_read_again_by_its_txid(app_context, db_session, fake_kraken, ready):
    user = ready(weights=(("XBT", "XXBTZEUR", "100"),))
    fake_kraken.fill_status = "open"
    first = invest(app_context, user.id)
    (txid,) = fake_kraken.orders
    fake_kraken.orders[txid].update(status="closed", vol_exec="0.02", cost="1000")
    fake_kraken.balance = {"ZEUR": "0"}

    invest(app_context, user.id)

    assert first.legs[0].status is LegStatus.PENDING
    assert get_by_cl_ord_id(db_session, fake_kraken.orders[txid]["cl_ord_id"]).status == OrderStatus.FILLED


def test_the_attempt_is_committed_before_the_order_is_sent(app_context, db_session, fake_kraken, ready):
    """Spec §9.2: a row still inside an open transaction does not survive the process."""
    user = ready(weights=(("XBT", "XXBTZEUR", "100"),))
    events = []

    @contextmanager
    def sessions():
        with app_context.sessions() as session:
            yield session
        events.append("commit")

    def on_add_order(form):
        row = get_by_cl_ord_id(db_session, form["cl_ord_id"])
        events.append(("AddOrder", None if row is None else row.status))

    fake_kraken.on_add_order = on_add_order
    invest(replace(app_context, sessions=sessions), user.id)

    sent_at = next(i for i, event in enumerate(events) if isinstance(event, tuple))
    assert events[sent_at] == ("AddOrder", OrderStatus.PENDING)
    assert events[sent_at - 1] == "commit"


def test_a_second_evaluation_of_the_same_user_is_refused(app_context, fake_kraken, ready, user_locks):
    user = ready()
    user_locks.held.add(user.id)

    with pytest.raises(EvaluationBusy):
        invest(app_context, user.id)
    assert fake_kraken.placed == []


def test_settings_come_first(app_context, make_user):
    with pytest.raises(NotReady, match="fiat"):
        invest(app_context, make_user().id)


def test_a_key_comes_next(app_context, db_session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(NotReady, match="key"):
        invest(app_context, user.id)


def test_an_unreadable_balance_sends_nothing_and_is_recorded(app_context, db_session, fake_kraken, ready):
    user = ready()
    fake_kraken.down.add("Balance")

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.KRAKEN_UNAVAILABLE
    assert fake_kraken.placed == []
    assert list_evaluations(db_session, user.id)[0].status == "KRAKEN_UNAVAILABLE"


def test_a_preview_has_kraken_validate_and_records_nothing(app_context, db_session, fake_kraken, ready):
    user = ready()

    result = invest(app_context, user.id, preview=True)

    assert result.status is EvaluationStatus.PREVIEW
    assert {leg.status for leg in result.legs} == {LegStatus.VALIDATED}
    assert {form["validate"] for form in fake_kraken.placed} == {"true"}
    assert list_orders(db_session, user.id) == []
    assert list_evaluations(db_session, user.id) == []
    assert latest_snapshot(db_session, user.id) is None


def test_a_preview_shows_what_kraken_would_refuse(app_context, fake_kraken, ready):
    user = ready()
    fake_kraken.add_order_errors = ["EOrder:Insufficient funds"]

    result = invest(app_context, user.id, preview=True)

    assert {(leg.status, leg.error) for leg in result.legs} == {(LegStatus.REJECTED, "EOrder:Insufficient funds")}


def test_a_preview_with_something_unresolved_says_so_and_resolves_nothing(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "dropped"
    invest(app_context, user.id)
    fake_kraken.placed.clear()

    result = invest(replace(app_context, now=lambda: app_context.now() + timedelta(days=1)), user.id, preview=True)

    assert result.status is EvaluationStatus.UNRESOLVED
    assert fake_kraken.placed == []
    (order,) = list_orders(db_session, user.id)
    assert order.status == OrderStatus.PENDING
```

In `tests/unit/core/test_layering.py`, replace
`test_nothing_outside_the_exchange_layer_places_an_order_yet` with:

```python
EXECUTOR = ROOT / "core" / "execution.py"


def test_only_the_executor_places_an_order():
    """Phase 5 adds the order path, in one module. A second caller of `add_order` would be
    a second place money leaves from, with its own idea of the unknown-result protocol."""
    offenders = [
        str(path.relative_to(ROOT))
        for package in ("api", "core")
        for path in sorted((ROOT / package).rglob("*.py"))
        if path != EXECUTOR and "add_order" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
```

- [ ] **Step 3: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_execution.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.execution'`.

- [ ] **Step 4: Implement the executor**

Create `core/execution.py`:

```python
"""Investing free cash: the one place in this system that places an order (spec §9).

An evaluation runs in short transactions of its own, never in a request's. The row of an
attempt is committed before its order is sent (§9.2), and no transaction is open while
Kraken is waited on (§9.6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

import core.database as db
from core.catalog import MarketCatalog
from core.crypto import CredentialCipher, Sealed
from core.db.models import Order
from core.db.types import OrderReason
from core.portfolio import PortfolioView, plain_amount
from core.reading import PortfolioUnavailable, read_portfolio
from core.settlement import resolve_pending, settle
from engine.reconcile import reconcile
from engine.types import ZERO, CashPolicy, Policy, Side
from exchange.orders import find_order_by_txid, new_cl_ord_id
from exchange.precision import minimum_fiat, round_cost
from exchange.types import Credentials, PlacementOutcome

logger = logging.getLogger("coinpilot.execution")


class ExecutionContext(Protocol):
    """What the executor needs. `api.context.AppContext` is one; a scheduler will be another."""

    sessions: Callable[[], AbstractContextManager[Session]]
    cipher: CredentialCipher
    catalog: MarketCatalog
    now: Callable[[], datetime]
    user_lock: Callable[[uuid.UUID], AbstractContextManager[bool]]

    def public_kraken(self): ...

    def kraken_for(self, credentials: Credentials): ...


class EvaluationBusy(Exception):
    """Another evaluation of this user is running. Nothing was done."""


class NotReady(Exception):
    """The user has not configured what an investment needs. The message says what."""


class EvaluationStatus(StrEnum):
    DONE = "DONE"
    NOTHING_TO_DO = "NOTHING_TO_DO"
    STOPPED = "STOPPED"
    UNRESOLVED = "UNRESOLVED"
    KRAKEN_UNAVAILABLE = "KRAKEN_UNAVAILABLE"
    PREVIEW = "PREVIEW"
    ERROR = "ERROR"


class LegStatus(StrEnum):
    FILLED = "FILLED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    UNCHECKED = "UNCHECKED"


@dataclass(frozen=True)
class LegResult:
    asset: str
    pair: str
    amount_fiat: Decimal
    minimum_fiat: Decimal | None
    status: LegStatus
    cl_ord_id: str | None = None
    txid: str | None = None
    cost: Decimal | None = None
    executed_volume: Decimal | None = None
    executed_price: Decimal | None = None
    fee: Decimal | None = None
    error: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class InvestResult:
    status: EvaluationStatus
    preview: bool
    legs: tuple[LegResult, ...] = ()
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Target:
    asset: str
    pair: str
    target_pct: Decimal


@dataclass(frozen=True)
class _Account:
    fiat: str
    policy: Policy
    # The user's own floor, applied with Kraken's minimum in one place (spec §7.3).
    floor: Decimal
    targets: tuple[_Target, ...]
    sealed: Sealed


@dataclass(frozen=True)
class _Leg:
    asset: str
    pair: str
    # Rounded down to the pair's cost precision.
    amount: Decimal
    minimum: Decimal | None
    # Why it is not sent. `None` for a leg that is.
    note: str | None


@dataclass(frozen=True)
class _Planned:
    view: PortfolioView
    legs: tuple[_Leg, ...]


UNRESOLVED_MESSAGE = "an earlier order is still unresolved; nothing was computed"


def invest(context: ExecutionContext, user_id: uuid.UUID, *, preview: bool = False) -> InvestResult:
    """Invest the user's free cash now or, with `preview`, say what that would do.

    Raises `NotReady` before anything is read, `EvaluationBusy` when another evaluation
    of the user holds the lock, and `CredentialsUnreadable` when the stored key does not
    open. Every other outcome is a status in the result.
    """
    account = _load(context, user_id)
    private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
    if preview:
        return _preview(context, user_id, account, private)
    with context.user_lock(user_id) as taken:
        if not taken:
            raise EvaluationBusy(str(user_id))
        return _run(context, user_id, account, private)


def _load(context: ExecutionContext, user_id: uuid.UUID) -> _Account:
    with context.sessions() as session:
        settings = db.get_settings(session, user_id)
        if settings is None:
            raise NotReady("choose a fiat with PATCH /config first")
        record = db.get_credentials(session, user_id)
        if record is None:
            raise NotReady("register a Kraken key with POST /credentials first")
        policy = Policy(
            allow_sells=False,
            cash_policy=CashPolicy.REDUCE_DRIFT if settings.cash_rebalance_enabled else CashPolicy.PRORATA,
            min_drift_pct=settings.min_drift_pct,
            # Zero for the engine: the executor applies the user's floor beside Kraken's
            # minimum, so a leg dropped for either reason is logged with it.
            min_order_fiat=ZERO,
        )
        targets = tuple(_Target(row.asset, row.pair, row.target_pct) for row in db.list_assets(session, user_id))
        sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
        return _Account(
            fiat=settings.fiat,
            policy=policy,
            floor=settings.min_order_fiat,
            targets=targets,
            sealed=sealed,
        )


def _plan(context: ExecutionContext, account: _Account, private) -> _Planned:
    """Read the account, run the engine, and size each leg against Kraken's minimum.

    Raises `PortfolioUnavailable` when any read fails.
    """
    view = read_portfolio(context.public_kraken(), private, account.fiat, account.targets)
    metas = context.catalog.pairs()
    if metas is None:
        raise PortfolioUnavailable("asset pairs")
    managed = {holding.asset: holding for holding in view.holdings if holding.managed}
    pair_of = {target.asset: target.pair for target in account.targets}
    plan = reconcile(
        {asset: holding.amount for asset, holding in managed.items()},
        {asset: holding.price for asset, holding in managed.items()},
        {target.asset: target.target_pct for target in account.targets},
        view.cash,
        account.policy,
    )

    legs: list[_Leg] = []
    for leg in plan.legs:
        if leg.side is not Side.BUY:
            raise RuntimeError("an invest plan never sells; phase 6 owns sells")
        pair = pair_of[leg.asset]
        meta = metas.get(pair)
        if meta is None or not meta.tradable:
            legs.append(_Leg(leg.asset, pair, leg.amount_fiat, None, f"kraken does not trade {pair} now"))
            continue
        amount = round_cost(meta, leg.amount_fiat)
        minimum = max(minimum_fiat(meta, managed[leg.asset].price), account.floor)
        note = None
        if amount < minimum:
            note = (
                f"{plain_amount(amount)} {account.fiat} is below the minimum "
                f"of {plain_amount(minimum)} {account.fiat}"
            )
        legs.append(_Leg(leg.asset, pair, amount, minimum, note))
    return _Planned(view=view, legs=tuple(legs))


def _run(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> InvestResult:
    with context.sessions() as session:
        evaluation_id = db.start_evaluation(session, user_id, context.now()).id
    log: list[str] = []
    legs: list[LegResult] = []
    status = EvaluationStatus.ERROR
    try:
        status = _evaluate(context, user_id, account, private, log, legs)
    except PortfolioUnavailable as exc:
        status = EvaluationStatus.KRAKEN_UNAVAILABLE
        log.append(f"kraken did not return {exc}; nothing was sent")
    finally:
        with context.sessions() as session:
            db.finish_evaluation(session, evaluation_id, status, context.now(), "\n".join(log) or None)
    return InvestResult(status=status, preview=False, legs=tuple(legs), messages=tuple(log))


def _evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    log: list[str],
    legs: list[LegResult],
) -> EvaluationStatus:
    resolution = resolve_pending(context.sessions, private, user_id, context.now())
    log.extend(resolution.messages)
    if not resolution.clear:
        log.append(UNRESOLVED_MESSAGE)
        return EvaluationStatus.UNRESOLVED

    planned = _plan(context, account, private)
    with context.sessions() as session:
        db.record_snapshot(
            session,
            user_id,
            as_of=context.now(),
            fiat=account.fiat,
            total_value=planned.view.managed_value,
            cash=planned.view.cash,
            holdings=planned.view.snapshot_json(),
        )

    stopped = False
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
        elif stopped:
            legs.append(_skipped(leg, "not sent: an earlier order's answer is unknown"))
        else:
            result = _send(context, user_id, private, leg)
            legs.append(result)
            # An unknown answer leaves no txid. The balance is ambiguous until resolved.
            stopped = result.status is LegStatus.PENDING and result.txid is None
        log.append(_describe(legs[-1], account.fiat))

    if stopped:
        return EvaluationStatus.STOPPED
    if any(leg.status is not LegStatus.SKIPPED for leg in legs):
        return EvaluationStatus.DONE
    return EvaluationStatus.NOTHING_TO_DO


def _send(context: ExecutionContext, user_id: uuid.UUID, private, leg: _Leg) -> LegResult:
    cl_ord_id = new_cl_ord_id()
    with context.sessions() as session:
        db.record_attempt(
            session,
            user_id,
            cl_ord_id,
            pair=leg.pair,
            asset=leg.asset,
            side=Side.BUY,
            reason=OrderReason.INVEST,
            requested_fiat=leg.amount,
            attempted_at=context.now(),
        )
    # Committed. From here a lost answer leaves a row to resolve, not a gap (spec §9.2).
    placement = private.add_order(leg.pair, "buy", leg.amount, cl_ord_id, in_quote=True)

    if placement.outcome is PlacementOutcome.REFUSED:
        with context.sessions() as session:
            db.mark_failed(session, cl_ord_id, error=placement.error)
    elif placement.outcome is PlacementOutcome.SENT:
        with context.sessions() as session:
            db.mark_sent(session, cl_ord_id, placement.txid)
        lookup = find_order_by_txid(private, placement.txid)
        with context.sessions() as session:
            settle(session, cl_ord_id, lookup)

    with context.sessions() as session:
        return _from_row(leg, db.get_by_cl_ord_id(session, cl_ord_id))


def _from_row(leg: _Leg, order: Order) -> LegResult:
    return LegResult(
        asset=leg.asset,
        pair=leg.pair,
        amount_fiat=leg.amount,
        minimum_fiat=leg.minimum,
        status=LegStatus(order.status),
        cl_ord_id=order.cl_ord_id,
        txid=order.txid,
        cost=order.cost,
        executed_volume=order.executed_volume,
        executed_price=order.executed_price,
        fee=order.fee,
        error=order.error,
    )


def _skipped(leg: _Leg, note: str) -> LegResult:
    return LegResult(leg.asset, leg.pair, leg.amount, leg.minimum, LegStatus.SKIPPED, note=note)


def _describe(leg: LegResult, fiat: str) -> str:
    text = f"{leg.asset}: buy of {plain_amount(leg.amount_fiat)} {fiat} {leg.status.value}"
    if leg.error:
        text += f" ({leg.error})"
    if leg.note:
        text += f": {leg.note}"
    return text


def _preview(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> InvestResult:
    """Read, plan and have Kraken validate. Writes nothing, takes no lock, resolves nothing."""
    with context.sessions() as session:
        unresolved = db.has_unresolved(session, user_id)
    if unresolved:
        return InvestResult(EvaluationStatus.UNRESOLVED, preview=True, messages=(UNRESOLVED_MESSAGE,))
    try:
        planned = _plan(context, account, private)
    except PortfolioUnavailable as exc:
        return InvestResult(EvaluationStatus.KRAKEN_UNAVAILABLE, preview=True, messages=(f"kraken did not return {exc}",))

    verdicts = {PlacementOutcome.VALIDATED: LegStatus.VALIDATED, PlacementOutcome.REFUSED: LegStatus.REJECTED}
    legs: list[LegResult] = []
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
            continue
        placement = private.add_order(leg.pair, "buy", leg.amount, new_cl_ord_id(), in_quote=True, validate=True)
        status = verdicts.get(placement.outcome, LegStatus.UNCHECKED)
        legs.append(LegResult(leg.asset, leg.pair, leg.amount, leg.minimum, status, error=placement.error))
    return InvestResult(EvaluationStatus.PREVIEW, preview=True, legs=tuple(legs))
```

- [ ] **Step 5: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test.

If `test_free_cash_is_invested_pro_rata_in_fiat` fails on the order of the legs, read
`engine/reconcile.py`: buys are sorted by asset code, so `ETH` comes before `XBT`. The
test states that order on purpose.

- [ ] **Step 6: Commit**

```bash
git add core/execution.py tests/integration/conftest.py tests/integration/test_execution.py tests/unit/core/test_layering.py
git commit -m "feat(core): invest free cash, writing every order down before it is sent"
```

---

### Task 8: `POST /invest`

**Files:**
- Create: `api/routes/invest.py`
- Modify: `api/app.py`
- Modify: `api/schemas.py`
- Test: `tests/integration/test_api_invest.py`, `tests/integration/test_api_tenant_isolation.py`

**Interfaces:**
- Consumes: `invest`, `EvaluationBusy`, `NotReady`, `EvaluationStatus`, `InvestResult`, `LegResult` (Task 7); `CredentialsUnreadable` (phase 4).
- Produces: `POST /invest?preview=<bool>` → `InvestOut`; `409` busy, not ready or unresolved; `503` when Kraken could not be read; `500` when the stored key does not open.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_api_invest.py`:

```python
import base64
from decimal import Decimal

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()


def _ready(api, headers, fake_kraken, *, cash="1000"):
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/ETH", json={"target_pct": "40"}, headers=headers)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": cash}


def test_investing_needs_a_signed_in_user(api):
    assert api.post("/invest").status_code == 401


def test_investing_needs_settings_first(api, make_user, login):
    response = api.post("/invest", headers=login(make_user()))

    assert response.status_code == 409
    assert "fiat" in response.json()["detail"]


def test_free_cash_is_invested_and_every_amount_is_a_plain_string(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/invest", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DONE"
    assert body["preview"] is False
    legs = {leg["asset"]: leg for leg in body["legs"]}
    assert legs["XBT"]["status"] == "FILLED"
    assert legs["XBT"]["amount_fiat"] == "600"
    assert legs["XBT"]["cost"] == "600"
    assert legs["XBT"]["minimum_fiat"] == "5"


def test_the_orders_appear_in_the_history_with_their_cost(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    api.post("/invest", headers=headers)

    orders = api.get("/orders", headers=headers).json()

    assert {order["status"] for order in orders} == {"FILLED"}
    assert {Decimal(order["cost"]) for order in orders} == {Decimal("600"), Decimal("400")}


def test_a_preview_is_validated_by_kraken_and_leaves_no_history(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/invest", params={"preview": "true"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "PREVIEW"
    assert {leg["status"] for leg in response.json()["legs"]} == {"VALIDATED"}
    assert api.get("/orders", headers=headers).json() == []
    assert api.get("/sessions", headers=headers).json() == []


def test_an_evaluation_already_running_is_a_409(api, make_user, login, fake_kraken, user_locks):
    user = make_user()
    headers = login(user)
    _ready(api, headers, fake_kraken)
    user_locks.held.add(user.id)

    response = api.post("/invest", headers=headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_an_unresolved_order_is_a_409_and_is_recorded(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.lose_add_order = "dropped"
    api.post("/invest", headers=headers)
    fake_kraken.lose_add_order = None

    response = api.post("/invest", headers=headers)

    assert response.status_code == 409
    assert "unresolved" in response.json()["detail"]
    # Both evaluations start at the fixed test time, so their order in the list is not.
    assert "UNRESOLVED" in {row["status"] for row in api.get("/sessions", headers=headers).json()}


def test_kraken_down_is_a_503_and_nothing_is_sent(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.down.add("Balance")

    response = api.post("/invest", headers=headers)

    assert response.status_code == 503
    assert [form for form in fake_kraken.placed if form.get("validate") != "true"] == []
```

In `tests/integration/test_api_tenant_isolation.py`, append:

```python
def test_investing_never_borrows_another_users_key(api, login, bob, alice_ready, fake_kraken):
    """Bob has no key of his own. Alice's must not be the one that answers."""
    response = api.post("/invest", headers=login(bob))

    assert response.status_code == 409
    assert fake_kraken.placed == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_invest.py -q`
Expected: FAIL — `404 Not Found` on `/invest`.

- [ ] **Step 3: Implement**

In `api/schemas.py`, append:

```python
class LegOut(BaseModel):
    """One leg of an investment. Every amount is a plain decimal string."""

    asset: str
    pair: str
    amount_fiat: str
    minimum_fiat: str | None
    status: str
    cl_ord_id: str | None
    txid: str | None
    cost: str | None
    executed_volume: str | None
    executed_price: str | None
    fee: str | None
    error: str | None
    note: str | None


class InvestOut(BaseModel):
    status: str
    preview: bool
    legs: list[LegOut]
    messages: list[str]
```

Create `api/routes/invest.py`:

```python
"""Invest free cash now (spec §11). A preview has Kraken validate and records nothing."""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException

from api.deps import Ctx, CurrentUser
from api.schemas import InvestOut, LegOut
from core.crypto import CredentialsUnreadable
from core.execution import EvaluationBusy, EvaluationStatus, InvestResult, LegResult, NotReady, invest
from core.portfolio import plain_amount

logger = logging.getLogger("coinpilot.api")

router = APIRouter(prefix="/invest", tags=["invest"])


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else plain_amount(value)


def _leg(leg: LegResult) -> LegOut:
    return LegOut(
        asset=leg.asset,
        pair=leg.pair,
        amount_fiat=plain_amount(leg.amount_fiat),
        minimum_fiat=_plain(leg.minimum_fiat),
        status=leg.status.value,
        cl_ord_id=leg.cl_ord_id,
        txid=leg.txid,
        cost=_plain(leg.cost),
        executed_volume=_plain(leg.executed_volume),
        executed_price=_plain(leg.executed_price),
        fee=_plain(leg.fee),
        error=leg.error,
        note=leg.note,
    )


def _out(result: InvestResult) -> InvestOut:
    return InvestOut(
        status=result.status.value,
        preview=result.preview,
        legs=[_leg(leg) for leg in result.legs],
        messages=list(result.messages),
    )


@router.post("", response_model=InvestOut)
def invest_now(user: CurrentUser, context: Ctx, preview: bool = False) -> InvestOut:
    try:
        result = invest(context, user.id, preview=preview)
    except EvaluationBusy:
        raise HTTPException(409, "an evaluation of this account is already running; try again shortly") from None
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from None
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user.id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None

    if result.status is EvaluationStatus.UNRESOLVED:
        raise HTTPException(409, "an earlier order is still unresolved; try again in a few minutes")
    if result.status is EvaluationStatus.KRAKEN_UNAVAILABLE:
        raise HTTPException(503, "kraken could not be read; nothing was sent")
    return _out(result)
```

In `api/app.py`, add `invest` to the import from `api.routes`, and add `invest.router,`
after `portfolio.router,` in the tuple `create_app` iterates.

- [ ] **Step 4: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test, including `test_no_response_model_has_a_field_for_a_credential`.

- [ ] **Step 5: Commit**

```bash
git add api tests/integration/test_api_invest.py tests/integration/test_api_tenant_isolation.py
git commit -m "feat(api): POST /invest, with a preview Kraken validates"
```

---

### Task 9: Kraken's minimum in `GET /assets`

**Files:**
- Modify: `api/schemas.py` (`AssetOut`)
- Modify: `api/routes/assets.py` (`list_assets`)
- Test: `tests/integration/test_api_assets.py`

**Interfaces:**
- Consumes: `minimum_fiat` (Task 2); `MarketCatalog.pairs()` (phase 4); `KrakenClient.ticker`.
- Produces: each item of `GET /assets` carries `kraken_min_fiat: str | None`, `null` when Kraken could not be read.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_api_assets.py`, append:

```python
def test_each_weight_shows_krakens_current_minimum(api, make_user, login):
    """XBT: 0.0001 at 50 000 is 5, over the 0.5 cost minimum. ETH: 0.0001 at 2 500 is
    0.25, under it."""
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/ETH", json={"target_pct": "40"}, headers=headers)

    body = api.get("/assets", headers=headers).json()

    minimums = {row["asset"]: row["kraken_min_fiat"] for row in body["assets"]}
    assert minimums == {"XBT": "5", "ETH": "0.5"}


def test_the_weights_are_shown_even_when_prices_cannot_be_read(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    fake_kraken.down.add("Ticker")

    response = api.get("/assets", headers=headers)

    assert response.status_code == 200
    assert response.json()["assets"][0]["kraken_min_fiat"] is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_assets.py -q`
Expected: FAIL — `KeyError: 'kraken_min_fiat'`.

- [ ] **Step 3: Implement**

In `api/schemas.py`, in `AssetOut`, after `target_pct`, add:

```python
    # Kraken's smallest order on the asset's pair, in fiat, at the current price (§7.3).
    # Absent from `PUT`, and `null` when Kraken could not be read.
    kraken_min_fiat: str | None = None
```

In `api/routes/assets.py`, add `from decimal import Decimal`,
`from core.portfolio import plain_amount` and `from exchange.precision import minimum_fiat`
to the imports, and replace `list_assets` with:

```python
def _minimums(context: Ctx, pairs: list[str]) -> dict[str, Decimal]:
    """Kraken's minimum per pair at the current price. Empty when Kraken cannot be read:
    the weights are still worth showing."""
    if not pairs:
        return {}
    metas = context.catalog.pairs()
    prices = context.public_kraken().ticker(sorted(set(pairs)))
    if metas is None or prices is None:
        return {}
    return {pair: minimum_fiat(metas[pair], prices[pair]) for pair in pairs if pair in metas and pair in prices}


@router.get("", response_model=AssetsOut)
def list_assets(user: CurrentUser, session: Db, context: Ctx) -> AssetsOut:
    rows = db.list_assets(session, user.id)
    minimums = _minimums(context, [row.pair for row in rows])
    return AssetsOut(
        assets=[
            AssetOut(
                asset=row.asset,
                pair=row.pair,
                target_pct=row.target_pct,
                kraken_min_fiat=plain_amount(minimums[row.pair]) if row.pair in minimums else None,
            )
            for row in rows
        ],
        cash_target_pct=HUNDRED - sum((row.target_pct for row in rows), ZERO),
    )
```

- [ ] **Step 4: Run the tests**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS, every test.

- [ ] **Step 5: Commit**

```bash
git add api tests/integration/test_api_assets.py
git commit -m "feat(api): show Kraken's current minimum order beside each weight"
```

---

### Task 10: The README, and the phase gate

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

In `README.md`, replace:

```markdown
> **Status: in development.** Phase 4 of 8: sign-in, encrypted keys and the read path.
> It cannot place an order yet.
```

with:

```markdown
> **Status: in development.** Phase 5 of 8: free cash is invested on request with
> `POST /invest`, after an optional preview Kraken validates. Nothing runs on its own yet.
```

- [ ] **Step 2: Run the whole gate**

Run each, and expect each to pass:

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests --cov-fail-under=80
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: the README describes phase 5"
```

---

## What you verify before phase 6

Phase 5 is the first phase that spends. Do it with a small amount.

### 1. Start from a known state

1. Restart the API, so it runs this phase's code. Apply the migration first:
   `PYTHONPATH=. alembic upgrade head` with your `.env` loaded.
2. Deposit a small amount of fiat on Kraken, 10 to 20 EUR, and let it settle.
3. `GET /assets`: each weight now shows `kraken_min_fiat`. Your free cash, split by your
   weights, should leave each leg above its minimum, or that leg will be skipped.

### 2. Preview

```bash
curl -s -X POST "localhost:8000/invest?preview=true" -H "Authorization: Bearer $TOKEN"
```

- `status` is `PREVIEW`, and each leg is `VALIDATED`, or `SKIPPED` with the reason.
- The amounts are what you expect from your free cash and weights.
- `GET /orders` and `GET /sessions` are unchanged: a preview records nothing.

### 3. Invest

```bash
curl -s -X POST localhost:8000/invest -H "Authorization: Bearer $TOKEN"
```

- `status` is `DONE`, and each leg sent is `FILLED`.
- In Kraken's own trade history, the order is there, a market buy, once.

### 4. Settle the two open facts

Read the row and compare it with Kraken's screen:

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "select asset, status, requested_fiat, cost, executed_volume, executed_price, fee, error from orders order by attempted_at"
```

- **`cost`**: in fiat, equal to `requested_fiat`? If it is not in fiat, `viqc` changed
  its unit.
- **`executed_volume`**: in the asset (for example `0.0002 XBT`), or in fiat?
- **`fee`**: in the asset, as `fcib` asks, or in fiat?

Report the three answers. They go into the plan's departures, and into spec §9.1 in place
of the sentence that says they are unverified.

### 5. Nothing more to do

```bash
curl -s -X POST "localhost:8000/invest?preview=true" -H "Authorization: Bearer $TOKEN"
```

With the cash invested, the legs are gone or `SKIPPED` under the minimum. `GET /sessions`
shows one evaluation, `DONE`, with a line per leg.

### 6. A decision to look at deliberately

- **An investment within two minutes of a lost answer is refused as unresolved.** That
  grace period is what stops a lost answer from turning into a second buy.

---

## Departures taken during execution

The code blocks above are the plan as written. Where the repository differs, trust the
repository.

| Where | What changed | Why |
|---|---|---|
| `core/db/models.py`, migration `8b8c04912293` | `sessions.status` widened from 16 to 32 characters | `KRAKEN_UNAVAILABLE` is 18 characters. The test of an unreadable balance failed on the insert; the plan had not checked the column. |
| `api/routes/invest.py` | The `409` for an unresolved order and the `503` for an unreadable Kraken are returned as a `JSONResponse`, not raised | Both are evaluations that ran and were recorded. Raising rolls back the request's transaction; in the tests, which nest every transaction in one, that erased the evaluation's record. The route no longer depends on the two being separate. `test_kraken_down_is_a_503_and_nothing_is_sent` now also checks the evaluation is recorded. |
| `docs/specs/2026-09-17-platform-design.md` §9.1, `core/db/models.py`, `exchange/types.py` | The two open facts of "What Kraken says" are settled | The first real order, 100 EUR of XBT (`OMMPAM-4D25N-RWECRY`), answered `cost` 100, `vol_exec` 0.00132703, `price` 75356.2, `fee` 0.8. Kraken's trade ledger shows −100 EUR with no fee, and +0.00132703 BTC with a fee of 0.00001061 BTC. So `viqc` leaves `cost` in fiat and `vol_exec` in the asset, gross; `fcib` takes the fee in the asset, and `QueryOrders` still reports it in fiat. The fee was 0.8 %, not the 0.40 % the spec assumed: Kraken has raised its taker fee. Accepted, and recorded in §9.1. |
