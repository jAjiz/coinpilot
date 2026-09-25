# Phase 3 — The Kraken Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the boundary between this system and Kraken — one authenticated identity
per user, pacing counted per key, Kraken's vocabulary translated into ours, and a key
with withdrawal permission refused before it is ever stored.

**Architecture:** `exchange/` is an anti-corruption layer. Four of its modules are pure
and hold no state: the request signature, the rounding boundary, the status translator
and the client identifier. One module speaks HTTP, and everything it can fail at returns
`None` rather than raising. No module-level global holds a user's state; the per-key
pacing lives in an object the application builds once and passes in.

**Tech Stack:** Python 3.13, httpx, Decimal. No database and no framework in this phase.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §4.2, §5.2, §9.1, §9.2, §10.3, §12

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 3 of 8

## Global Constraints

- **Python 3.13.** `requires-python = ">=3.13"`. One version, not a range.
- **Money is `Decimal`, never `float`.** Every amount, price and volume is
  `decimal.Decimal`. A `float` in a monetary path is a defect.
- **Pin every dependency with `==`.** Resolve the exact version before adding one.
- **No test reads configuration from the environment.** Every test states its inputs.
- **No test in this phase touches the network.** Every HTTP call is served by
  `httpx.MockTransport`. The one live check is a script the user runs by hand, not a test.
- **Coverage gate is 80 %**, enforced by the CI command.
- **`ruff check` and `ruff format --check` must pass.**
- **A credential never reaches a log line, an exception message or a return value.**
- Commit messages follow Conventional Commits.

---

## What Kraken actually says

Every fact below was read from Kraken's documentation while writing this plan, not
recalled. An implementer should not have to re-check them.

| Fact | Source |
|---|---|
| `AddOrder` accepts `cl_ord_id`: a 32-character hex short UUID, a dashed UUID, or free text up to 18 ASCII characters. It is **mutually exclusive with `userref`** | [AddOrder](https://docs.kraken.com/api/docs/rest-api/add-order) |
| `AddOrder` accepts `validate`, default false: the order is checked and never reaches the matching engine | [AddOrder](https://docs.kraken.com/api/docs/rest-api/add-order) |
| `OpenOrders` and `ClosedOrders` accept `cl_ord_id` as a **filter**, and each returned order echoes its own `cl_ord_id` | [OpenOrders](https://docs.kraken.com/api/docs/rest-api/get-open-orders) |
| An order's `status` is one of `pending`, `open`, `closed`, `canceled`, `expired` | [OpenOrders](https://docs.kraken.com/api/docs/rest-api/get-open-orders) |
| `result.open` is keyed by txid; each order carries `vol`, `vol_exec`, `price`, `cost`, `fee`, `descr` | [OpenOrders](https://docs.kraken.com/api/docs/rest-api/get-open-orders) |
| `GetApiKeyInfo` is `POST /0/private/GetApiKeyInfo` and returns `permissions` and `ipAllowlist` | [GetApiKeyInfo](https://docs.kraken.com/api-reference/account-data/get-api-key-info) |
| `AssetPairs` gives `pair_decimals`, `lot_decimals`, `ordermin`, `costmin`, `altname`, `base`, `quote`, and a `status` of `online`, `cancel_only`, `post_only`, `limit_only` or `reduce_only` | [AssetPairs](https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs) |

**The signature algorithm**, from
[Spot REST Authentication](https://docs.kraken.com/api/docs/guides/spot-rest-auth/):

```
API-Sign = base64( HMAC-SHA512( base64decode(secret),
                                uri_path + SHA256(nonce + urlencoded_body) ) )
```

Kraken publishes a worked example, and **this plan's `sign` function was run against it
and reproduces the expected output exactly**. Task 1 pins it as a test.

---

## File Structure

| File | Responsibility |
|---|---|
| `exchange/__init__.py` | Marks the package; exports nothing |
| `exchange/types.py` | `Credentials`, `PairMeta`, `ExchangeOrderStatus`, `OrderLookup`, `KeyRejection`, `KeyValidation` |
| `exchange/signing.py` | `encode_body` and `sign` — the request signature, pure |
| `exchange/limits.py` | `KeyLimiter` — per-key pacing and per-key nonces |
| `exchange/precision.py` | `round_price`, `round_volume`, `volume_from_fiat`, `is_orderable` |
| `exchange/client.py` | `build_http_client`, `KrakenClient` — the only module that speaks HTTP |
| `exchange/orders.py` | `map_order_status`, `new_cl_ord_id`, `find_order_by_cl_ord_id` |
| `exchange/keys.py` | `validate_key` — the permission contract of §5.2 |
| `scripts/check_key.py` | The live check the user runs by hand against a real key |
| `tests/unit/exchange/test_signing.py` | The published test vector and the encoding contract |
| `tests/unit/exchange/test_limits.py` | Pacing and nonces, on a fake clock |
| `tests/unit/exchange/test_precision.py` | The rounding boundary and the order minimums |
| `tests/unit/exchange/test_client.py` | Every call, every failure, against `MockTransport` |
| `tests/unit/exchange/test_orders.py` | Status translation and the client identifier |
| `tests/unit/exchange/test_find_order.py` | The unknown-result primitive, in every branch |
| `tests/unit/exchange/test_keys.py` | The permission contract |

These are **unit** tests, not integration tests: nothing here needs a database or a
network, so they run in the suite a developer runs constantly.

---

## Two names that look alike and are not

`core.db.types.OrderStatus` is **our** ledger vocabulary: `PENDING`, `FILLED`, `FAILED`.
It says what this system knows about an attempt.

`exchange.types.ExchangeOrderStatus` is **Kraken's** vocabulary, normalised: `PENDING`,
`OPEN`, `CLOSED`, `CANCELED`, plus `NOT_FOUND` and `UNKNOWN`, which Kraken has no word
for. It says what the exchange reports.

They are deliberately different types with different names. Translating between them is
the whole point of an anti-corruption layer, and a single shared enumeration would let
Kraken's vocabulary leak into the ledger one rename at a time.

---

## What this phase deliberately leaves out

- **Nothing calls Kraken from the application.** There is no scheduler and no endpoint
  yet. The client exists, is fully tested, and is invoked only by a script the user runs.
- **The unknown-result *protocol*** — write before sending, resolve before computing — is
  phase 5. This phase builds `find_order_by_cl_ord_id`, the primitive that protocol needs,
  and gets its three answers exactly right.
- **Encryption.** The client takes a `Credentials` value. Where it came from, and how it
  was decrypted, is phase 4.
- **Per-user client construction.** Phase 4 builds a client from a user's stored key. This
  phase defines what a client is.
- **Refusing an asset that cannot be traded against the user's fiat** (§3.1). This phase
  provides `asset_pairs`, which is the reading that decision needs. Making the decision,
  and refusing at configuration time rather than at order time, is phase 4.

---

### Task 1: The value objects and the request signature

**Files:**
- Create: `exchange/__init__.py`
- Create: `exchange/types.py`
- Create: `exchange/signing.py`
- Create: `tests/unit/exchange/test_signing.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Credentials(api_key: str, api_secret: str)` — frozen
  - `PairMeta(pair, altname, base, quote, price_decimals, volume_decimals, order_min, cost_min, status)` with a `tradable` property
  - `ExchangeOrderStatus` — `PENDING`, `OPEN`, `CLOSED`, `CANCELED`, `NOT_FOUND`, `UNKNOWN`
  - `OrderLookup(txid, status, volume, volume_executed, price, fee)` — frozen
  - `KeyRejection` — `UNREACHABLE`, `MISSING_PERMISSIONS`, `FORBIDDEN_PERMISSIONS`
  - `KeyValidation(accepted, rejection, permissions, missing, forbidden, ip_allowlist)` — frozen
  - `encode_body(payload: Mapping[str, object]) -> str`
  - `sign(path: str, nonce: str, body: str, secret: str) -> str`

- [ ] **Step 1: Add httpx to `requirements.txt`**

The client needs it in task 4, and its `MockTransport` is what keeps every test in this
phase off the network. FastAPI brings it in a later phase anyway.

```
SQLAlchemy==2.0.54
alembic==1.20.0
psycopg[binary]==3.3.5
httpx==0.28.1
```

Install it:

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Measure the new package**

In `pyproject.toml`, add `exchange` to the coverage source. A package that is not measured
passes the gate no matter what it contains.

```toml
[tool.coverage.run]
source = ["engine", "core", "exchange"]
```

- [ ] **Step 3: Write `exchange/types.py`**

`exchange/__init__.py` is an empty file.

```python
"""The vocabulary of the exchange boundary.

Every value here is frozen and carries no behaviour beyond reading itself. Kraken's words
are translated into these on the way in, and nothing outside this package ever sees a raw
Kraken field name.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class Credentials:
    """One user's Kraken key.

    It arrives already decrypted and is never logged, never put in an exception message,
    and never returned by anything in this package.
    """

    api_key: str
    api_secret: str


@dataclass(frozen=True)
class PairMeta:
    """What Kraken will accept for one tradable pair.

    `price_decimals` and `volume_decimals` are the rounding boundary: a number with more
    precision than this is rejected by the exchange, so it is rounded here and nowhere
    else.
    """

    pair: str
    altname: str
    base: str
    quote: str
    price_decimals: int
    volume_decimals: int
    order_min: Decimal
    cost_min: Decimal
    status: str

    @property
    def tradable(self) -> bool:
        """Kraken publishes five statuses and only one of them accepts a market order."""
        return self.status == "online"


class ExchangeOrderStatus(StrEnum):
    """Kraken's order statuses, normalised.

    `NOT_FOUND` and `UNKNOWN` have no Kraken counterpart. The first means Kraken answered
    and does not know the id; the second means Kraken used a word this code does not
    model, which must fail loudly rather than be guessed at.
    """

    CANCELED = "canceled"
    CLOSED = "closed"
    NOT_FOUND = "not_found"
    OPEN = "open"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OrderLookup:
    """What one order looks like at the exchange.

    A lookup that resolved nothing carries `txid=None` and `status=None`. That is the
    answer *both endpoints replied and neither had it*, which is different from the
    lookup having failed — the caller gets `None` for that, never this.
    """

    txid: str | None
    status: ExchangeOrderStatus | None
    volume: Decimal
    volume_executed: Decimal
    price: Decimal
    fee: Decimal


class KeyRejection(StrEnum):
    """Why a key was refused. Never shown to anyone but its own owner."""

    FORBIDDEN_PERMISSIONS = "forbidden_permissions"
    MISSING_PERMISSIONS = "missing_permissions"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class KeyValidation:
    """The answer to *may this key be stored*.

    It names what is missing and what is forbidden so the user can fix their key without
    guessing. It carries no part of the key itself.
    """

    accepted: bool
    rejection: KeyRejection | None
    permissions: tuple[str, ...]
    missing: tuple[str, ...]
    forbidden: tuple[str, ...]
    ip_allowlist: tuple[str, ...]
```

- [ ] **Step 4: Write the failing tests**

`tests/unit/exchange/test_signing.py`:

```python
import pytest

from exchange.signing import encode_body, sign

# Kraken's own worked example, from the Spot REST Authentication guide. It is the whole
# reason this module can be trusted without ever making a request.
VECTOR_SECRET = (
    "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
)
VECTOR_NONCE = "1616492376594"
VECTOR_BODY = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
VECTOR_PATH = "/0/private/AddOrder"
VECTOR_SIGNATURE = (
    "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
)


def test_the_signature_matches_krakens_published_example():
    assert sign(VECTOR_PATH, VECTOR_NONCE, VECTOR_BODY, VECTOR_SECRET) == VECTOR_SIGNATURE


def test_the_path_is_part_of_the_signature():
    """A signature valid for one endpoint must not be valid for another."""
    other = sign("/0/private/Balance", VECTOR_NONCE, VECTOR_BODY, VECTOR_SECRET)

    assert other != VECTOR_SIGNATURE


def test_the_nonce_is_part_of_the_signature():
    other = sign(VECTOR_PATH, "1616492376595", VECTOR_BODY, VECTOR_SECRET)

    assert other != VECTOR_SIGNATURE


def test_a_secret_that_is_not_base64_raises_rather_than_signing_nonsense():
    """A mistyped secret must fail here, not produce a signature Kraken silently rejects."""
    with pytest.raises(ValueError):
        sign(VECTOR_PATH, VECTOR_NONCE, VECTOR_BODY, "not base64 at all!!")


def test_the_body_encoding_keeps_the_order_it_was_given():
    """The signed bytes and the sent bytes must be identical, so the order cannot drift."""
    body = encode_body({"nonce": "1", "pair": "XBTEUR", "type": "buy"})

    assert body == "nonce=1&pair=XBTEUR&type=buy"


def test_the_body_encoding_escapes_what_a_url_cannot_carry():
    body = encode_body({"nonce": "1", "cl_ord_id": "a b/c"})

    assert body == "nonce=1&cl_ord_id=a+b%2Fc"


def test_encoding_the_vector_payload_reproduces_the_vector_body():
    """Proof that `encode_body` is what produced the string the signature test pins."""
    body = encode_body(
        {
            "nonce": "1616492376594",
            "ordertype": "limit",
            "pair": "XBTUSD",
            "price": "37500",
            "type": "buy",
            "volume": "1.25",
        }
    )

    assert body == VECTOR_BODY
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_signing.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.signing'`

- [ ] **Step 6: Write `exchange/signing.py`**

```python
"""The Kraken request signature.

Pure: given a path, a nonce, the encoded body and the secret, it returns one header
value. No I/O, no clock and no state, which is why the algorithm is pinned by Kraken's
own published example rather than by whether a request happened to succeed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import urlencode


def encode_body(payload: Mapping[str, object]) -> str:
    """The exact string that is both signed and sent.

    One function serves both on purpose. Signing a different encoding from the one that
    goes out is the failure that looks exactly like a wrong secret, and it would cost an
    afternoon to find.
    """
    return urlencode(payload)


def sign(path: str, nonce: str, body: str, secret: str) -> str:
    """The value of the `API-Sign` header.

    Raises `ValueError` when the secret is not valid base64, because a signature built
    from a mistyped secret is indistinguishable from a rejected one at the far end.
    """
    try:
        decoded = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("the API secret is not valid base64") from exc

    message = path.encode() + hashlib.sha256((nonce + body).encode()).digest()
    signature = hmac.new(decoded, message, hashlib.sha512)
    return base64.b64encode(signature.digest()).decode()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_signing.py -v --no-cov`
Expected: 7 passed.

- [ ] **Step 8: Commit**

```bash
git add exchange requirements.txt tests/unit/exchange
git commit -m "feat(exchange): value objects and the request signature"
```

---

### Task 2: Per-key pacing and per-key nonces

**Files:**
- Create: `exchange/limits.py`
- Create: `tests/unit/exchange/test_limits.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `KeyLimiter(min_interval: float, *, now=time.monotonic, sleep=time.sleep, clock=time.time)`
  - `KeyLimiter.wait_turn(bucket: str) -> None`
  - `KeyLimiter.next_nonce(bucket: str) -> str`
  - `PUBLIC_BUCKET` — the bucket name every unauthenticated call shares

**Rules this implements** (spec §10.3, §4.2):
- Kraken counts against the **key**, so two users never contend. That is what makes the
  multi-tenant load a distribution problem rather than a volume one.
- Public endpoints are counted by address instead, so they share one bucket.
- The limiter is an **object the application builds once and passes in**, not a module
  global. Per-user state in a global is exactly what §4.2 forbids, and an injected object
  is also what lets a test run on a fake clock instead of really sleeping.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_limits.py`:

```python
from exchange.limits import PUBLIC_BUCKET, KeyLimiter


class FakeClock:
    """A clock the test moves by hand. Sleeping advances it, exactly as it would in life."""

    def __init__(self) -> None:
        self.monotonic = 1000.0
        self.wall = 1_700_000_000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.monotonic

    def time(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.monotonic += seconds
        self.wall += seconds


def _limiter(clock: FakeClock, min_interval: float = 1.0) -> KeyLimiter:
    return KeyLimiter(min_interval, now=clock.now, sleep=clock.sleep, clock=clock.time)


def test_the_first_call_for_a_key_never_waits():
    clock = FakeClock()
    limiter = _limiter(clock)

    limiter.wait_turn("key-a")

    assert clock.slept == []


def test_a_second_call_too_soon_waits_the_remainder():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")
    clock.monotonic += 0.25

    limiter.wait_turn("key-a")

    assert clock.slept == [0.75]


def test_a_second_call_after_the_interval_does_not_wait():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")
    clock.monotonic += 5.0

    limiter.wait_turn("key-a")

    assert clock.slept == []


def test_one_users_pace_does_not_slow_another():
    """The whole multi-tenant argument in one test. Kraken counts per key."""
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")

    limiter.wait_turn("key-b")

    assert clock.slept == []


def test_every_public_call_shares_one_bucket():
    """Public endpoints are counted by address, so they contend with each other."""
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn(PUBLIC_BUCKET)

    limiter.wait_turn(PUBLIC_BUCKET)

    assert clock.slept == [1.0]


def test_a_nonce_is_the_clock_in_microseconds():
    clock = FakeClock()
    limiter = _limiter(clock)

    assert limiter.next_nonce("key-a") == str(int(clock.wall * 1_000_000))


def test_two_nonces_for_one_key_always_increase():
    """Kraken refuses a nonce that is not greater than the last one this key used."""
    clock = FakeClock()
    limiter = _limiter(clock)

    first = int(limiter.next_nonce("key-a"))
    second = int(limiter.next_nonce("key-a"))

    assert second > first


def test_a_clock_that_jumps_backwards_still_yields_an_increasing_nonce():
    """An NTP correction would otherwise lock the key out until the clock caught up."""
    clock = FakeClock()
    limiter = _limiter(clock)
    first = int(limiter.next_nonce("key-a"))
    clock.wall -= 60.0

    second = int(limiter.next_nonce("key-a"))

    assert second > first


def test_each_key_keeps_its_own_nonce_sequence():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.next_nonce("key-a")
    limiter.next_nonce("key-a")
    clock.wall -= 60.0

    fresh = int(limiter.next_nonce("key-b"))

    assert fresh == int(clock.wall * 1_000_000)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_limits.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.limits'`

- [ ] **Step 3: Write `exchange/limits.py`**

```python
"""The two facts Kraken tracks per key: how recently it called, and its last nonce.

They live in one object because they share a scope and a lifetime. Both are counted per
key, both must outlive any single client object, and neither may sit in a module global —
§4.2 forbids user state there, and an injected object is also what lets a test run on a
fake clock instead of really sleeping.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Kraken counts public endpoints against the calling address, not a key, so every
# unauthenticated call shares this one bucket.
PUBLIC_BUCKET = "__public__"


class KeyLimiter:
    """Paces calls and hands out nonces, separately for each key."""

    def __init__(
        self,
        min_interval: float,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._min_interval = min_interval
        self._now = now
        self._sleep = sleep
        self._clock = clock
        self._guard = threading.Lock()
        self._last_call: dict[str, float] = {}
        self._last_nonce: dict[str, int] = {}

    def wait_turn(self, bucket: str) -> None:
        """Block until this bucket may call again.

        The wait happens outside the guard: holding it across a sleep would make one
        key's pacing block every other key, which is the exact contention this design
        exists to avoid.
        """
        with self._guard:
            previous = self._last_call.get(bucket)
            now = self._now()
            wait = 0.0 if previous is None else previous + self._min_interval - now
            self._last_call[bucket] = now if wait <= 0 else now + wait

        if wait > 0:
            self._sleep(wait)

    def next_nonce(self, bucket: str) -> str:
        """A nonce strictly greater than the last one this bucket used.

        The clock alone is not enough. A correction can move it backwards, and Kraken
        then refuses every later request from that key until it catches up.
        """
        with self._guard:
            candidate = int(self._clock() * 1_000_000)
            previous = self._last_nonce.get(bucket, 0)
            if candidate <= previous:
                candidate = previous + 1
            self._last_nonce[bucket] = candidate
            return str(candidate)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_limits.py -v --no-cov`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add exchange/limits.py tests/unit/exchange/test_limits.py
git commit -m "feat(exchange): per-key pacing and per-key nonces"
```

---

### Task 3: The rounding boundary

**Files:**
- Create: `exchange/precision.py`
- Create: `tests/unit/exchange/test_precision.py`

**Interfaces:**
- Consumes: `exchange.types.PairMeta`
- Produces:
  - `format_decimal(value: Decimal) -> str`
  - `round_price(meta: PairMeta, price: Decimal) -> Decimal`
  - `round_volume(meta: PairMeta, volume: Decimal) -> Decimal`
  - `volume_from_fiat(meta: PairMeta, amount_fiat: Decimal, price: Decimal) -> Decimal`
  - `is_orderable(meta: PairMeta, volume: Decimal, cost: Decimal) -> bool`

**Rules this implements** (spec §4.2):
- Rounding happens **here and nowhere else**. Precision comes from the pair, never from a
  constant, so a pair whose price is a fraction of a cent keeps its precision.
- Volume always rounds **down**. Rounding a buy up overspends; rounding a sell up tries to
  sell coins the user does not hold.
- A rounded-down volume can reach zero, and `is_orderable` is what catches it.

> **`str(Decimal)` is not safe on a money path.**
> `str(Decimal("0.00000001"))` is `"1E-8"`, and Kraken rejects that. Bitcoin's
> `lot_decimals` is 8, so this is reachable with a real order, and it fails as a rejected
> request rather than as anything that points at the cause. `format_decimal` exists for
> exactly this, and every number leaving this package for Kraken goes through it.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_precision.py`:

```python
from decimal import Decimal

import pytest

from exchange.precision import (
    format_decimal,
    is_orderable,
    round_price,
    round_volume,
    volume_from_fiat,
)
from exchange.types import PairMeta

D = Decimal

BTC = PairMeta(
    pair="XXBTZEUR",
    altname="XBTEUR",
    base="XXBT",
    quote="ZEUR",
    price_decimals=1,
    volume_decimals=8,
    order_min=D("0.00005"),
    cost_min=D("5"),
    status="online",
)

# A pair whose price is a fraction of a cent. A rounding rule taken from a constant
# instead of from the pair destroys this one and leaves Bitcoin looking fine.
CHEAP = PairMeta(
    pair="XDGEUR",
    altname="XDGEUR",
    base="XDG",
    quote="ZEUR",
    price_decimals=7,
    volume_decimals=8,
    order_min=D("20"),
    cost_min=D("5"),
    status="online",
)


def test_a_small_decimal_is_written_in_full_not_in_scientific_notation():
    """`str` would give "1E-8" here, and Kraken rejects it."""
    assert format_decimal(D("0.00000001")) == "0.00000001"


def test_format_leaves_an_ordinary_number_alone():
    assert format_decimal(D("1.25")) == "1.25"
    assert format_decimal(D("12345.6")) == "12345.6"


def test_format_keeps_trailing_zeros_because_they_carry_the_precision():
    assert format_decimal(D("0.00100000")) == "0.00100000"


def test_a_price_rounds_to_the_precision_of_its_own_pair():
    assert round_price(BTC, D("47123.456")) == D("47123.5")
    assert round_price(CHEAP, D("0.08213456")) == D("0.0821346")


def test_a_fraction_of_a_cent_survives_rounding():
    """The precision comes from the pair, so a cheap pair is not flattened to zero."""
    assert round_price(CHEAP, D("0.0000821")) == D("0.0000821")


def test_a_volume_always_rounds_down():
    """Rounding up would overspend on a buy and oversell on a sell."""
    assert round_volume(BTC, D("0.123456789")) == D("0.12345678")


def test_a_volume_below_the_pairs_precision_rounds_to_zero():
    """It is not an error here. `is_orderable` is what refuses it."""
    assert round_volume(BTC, D("0.000000001")) == D("0")


def test_volume_is_the_money_divided_by_the_price_rounded_down():
    volume = volume_from_fiat(BTC, D("100"), D("47000"))

    assert volume == D("0.00212765")


def test_a_price_of_zero_raises_instead_of_dividing():
    """A zero price is not a market state. Returning zero would silently drop the leg."""
    with pytest.raises(ValueError, match="price"):
        volume_from_fiat(BTC, D("100"), D("0"))


def test_a_negative_price_raises():
    with pytest.raises(ValueError, match="price"):
        volume_from_fiat(BTC, D("100"), D("-1"))


def test_an_order_below_the_pairs_minimum_volume_is_refused():
    assert is_orderable(BTC, volume=D("0.00001"), cost=D("100")) is False


def test_an_order_below_the_pairs_minimum_cost_is_refused():
    assert is_orderable(BTC, volume=D("1"), cost=D("4.99")) is False


def test_an_order_exactly_at_both_minimums_is_accepted():
    assert is_orderable(BTC, volume=D("0.00005"), cost=D("5")) is True


def test_a_pair_that_is_not_online_is_not_tradable():
    """Kraken publishes five statuses and only one of them accepts a market order."""
    frozen = PairMeta(
        pair="XXBTZEUR",
        altname="XBTEUR",
        base="XXBT",
        quote="ZEUR",
        price_decimals=1,
        volume_decimals=8,
        order_min=D("0.00005"),
        cost_min=D("5"),
        status="cancel_only",
    )

    assert BTC.tradable is True
    assert frozen.tradable is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_precision.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.precision'`

- [ ] **Step 3: Write `exchange/precision.py`**

```python
"""Where a number meets the precision its pair will accept.

Every rounding rule comes from the pair, never from a constant. A constant is invisible
on a pair worth tens of thousands and destroys one worth a fraction of a cent.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from exchange.types import PairMeta


def format_decimal(value: Decimal) -> str:
    """The string form Kraken accepts.

    `str` switches to scientific notation below a millionth, so `Decimal("0.00000001")`
    becomes `"1E-8"` and the request is rejected. Bitcoin rounds to eight places, which
    puts that inside the ordinary range of a real order.
    """
    return format(value, "f")


def _quantum(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


def round_price(meta: PairMeta, price: Decimal) -> Decimal:
    """To the pair's price precision. Half up, because a price is a reading."""
    return price.quantize(_quantum(meta.price_decimals), rounding=ROUND_HALF_UP)


def round_volume(meta: PairMeta, volume: Decimal) -> Decimal:
    """To the pair's volume precision, always down.

    Down is not a preference. Rounding a buy up spends more than was allocated, and
    rounding a sell up asks to sell coins the user does not hold.
    """
    return volume.quantize(_quantum(meta.volume_decimals), rounding=ROUND_DOWN)


def volume_from_fiat(meta: PairMeta, amount_fiat: Decimal, price: Decimal) -> Decimal:
    """How much of the base asset `amount_fiat` buys, rounded down.

    Raises on a price that is not positive. Returning zero instead would drop the leg
    silently, and a missing order is harder to notice than a refused one.
    """
    if price <= 0:
        raise ValueError(f"cannot size an order at a price of {price}")
    return round_volume(meta, amount_fiat / price)


def is_orderable(meta: PairMeta, volume: Decimal, cost: Decimal) -> bool:
    """Whether Kraken will accept an order of this size on this pair.

    Both minimums are the pair's own. A volume that rounded down to zero fails here,
    which is the point of checking after rounding rather than before.
    """
    return volume >= meta.order_min and cost >= meta.cost_min
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_precision.py -v --no-cov`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add exchange/precision.py tests/unit/exchange/test_precision.py
git commit -m "feat(exchange): the rounding boundary and the order minimums"
```

---

### Task 4: The client, and what it does when a call fails

**Files:**
- Create: `exchange/client.py`
- Create: `tests/unit/exchange/test_client.py`

**Interfaces:**
- Consumes: `exchange.types.Credentials`, `exchange.types.PairMeta`, `exchange.signing`, `exchange.limits`, `exchange.precision.format_decimal`
- Produces:
  - `build_http_client(timeout_seconds: float = 10.0) -> httpx.Client`
  - `KrakenClient(http, limiter, credentials=None)`
  - `KrakenClient.asset_pairs(pairs=None) -> dict[str, PairMeta] | None`
  - `KrakenClient.ticker(pairs) -> dict[str, Decimal] | None`
  - `KrakenClient.api_key_info() -> dict | None`
  - `KrakenClient.balance() -> dict[str, Decimal] | None`
  - `KrakenClient.add_order(pair, side, volume, cl_ord_id, validate=False) -> dict | None`
  - `KrakenClient.open_orders(cl_ord_id=None) -> dict[str, dict] | None`
  - `KrakenClient.closed_orders(cl_ord_id=None) -> dict[str, dict] | None`
  - `MissingCredentials(Exception)`

**Rules this implements** (spec §4.2, §9.1, §9.2, §10.3, §12):
- Every call that can fail returns `None`. A missed evaluation is recoverable; a crashed
  process is not.
- Kraken prefixes errors with `E` and warnings with `W`. Only an `E` is a failure.
- Every blocking call is time-bounded. One stalled call on a single-worker scheduler
  blocks every later tick.
- **No log line, and no exception this module lets escape, carries a credential.**
- Orders are market orders. There is no price parameter and no order that rests.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_client.py`:

```python
import logging
from decimal import Decimal

import httpx
import pytest

from exchange.client import KrakenClient, MissingCredentials, build_http_client
from exchange.limits import KeyLimiter
from exchange.types import Credentials

D = Decimal

CREDENTIALS = Credentials(
    api_key="THE-PUBLIC-KEY",
    # Valid base64, and not a real secret.
    api_secret="c2VjcmV0LXZhbHVlLXRoYXQtaXMtb25seS1mb3ItYS10ZXN0AAAAAA==",
)

ASSET_PAIRS = {
    "XXBTZEUR": {
        "altname": "XBTEUR",
        "base": "XXBT",
        "quote": "ZEUR",
        "pair_decimals": 1,
        "lot_decimals": 8,
        "ordermin": "0.00005",
        "costmin": "5",
        "status": "online",
    }
}


def _client(handler, *, credentials=CREDENTIALS, min_interval=0.0):
    """A client whose every request is answered by `handler`, never by the network."""
    http = httpx.Client(
        base_url="https://api.kraken.com", transport=httpx.MockTransport(handler)
    )
    return KrakenClient(http, KeyLimiter(min_interval), credentials=credentials)


def _ok(result):
    return httpx.Response(200, json={"error": [], "result": result})


def test_a_public_call_is_unwrapped_into_value_objects():
    client = _client(lambda request: _ok(ASSET_PAIRS))

    pairs = client.asset_pairs()

    assert pairs["XXBTZEUR"].altname == "XBTEUR"
    assert pairs["XXBTZEUR"].volume_decimals == 8
    assert pairs["XXBTZEUR"].order_min == D("0.00005")
    assert pairs["XXBTZEUR"].tradable is True


def test_a_ticker_price_comes_back_as_a_decimal_not_a_float():
    client = _client(lambda request: _ok({"XXBTZEUR": {"c": ["47123.4", "0.01"]}}))

    prices = client.ticker(["XXBTZEUR"])

    assert prices == {"XXBTZEUR": D("47123.4")}
    assert isinstance(prices["XXBTZEUR"], Decimal)


def test_a_balance_comes_back_as_decimals():
    client = _client(lambda request: _ok({"ZEUR": "1234.5678", "XXBT": "0.05"}))

    assert client.balance() == {"ZEUR": D("1234.5678"), "XXBT": D("0.05")}


def test_a_private_call_carries_the_key_and_a_signature():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = request.content.decode()
        return _ok({})

    _client(handler).balance()

    assert seen["headers"]["API-Key"] == "THE-PUBLIC-KEY"
    assert seen["headers"]["API-Sign"]
    assert seen["body"].startswith("nonce=")


def test_a_private_call_without_credentials_is_a_programming_error():
    """Not a `None`. Asking for a balance with no key is a bug in the caller, not an
    outage, and returning `None` would hide it among the real ones."""
    client = _client(lambda request: _ok({}), credentials=None)

    with pytest.raises(MissingCredentials):
        client.balance()


def test_a_public_call_without_credentials_still_works():
    """This is what the scheduler uses for its one shared price fetch per tick."""
    client = _client(lambda request: _ok({"XXBTZEUR": {"c": ["100", "1"]}}), credentials=None)

    assert client.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("100")}


def test_a_kraken_error_becomes_none():
    client = _client(
        lambda request: httpx.Response(200, json={"error": ["EGeneral:Invalid arguments"]})
    )

    assert client.balance() is None


def test_a_kraken_warning_is_not_an_error():
    """Kraken prefixes an error with E and a warning with W. Treating a warning as a
    failure would throw away a perfectly good answer."""
    client = _client(
        lambda request: httpx.Response(
            200, json={"error": ["WGeneral:Deprecated"], "result": {"ZEUR": "10"}}
        )
    )

    assert client.balance() == {"ZEUR": D("10")}


def test_an_http_error_becomes_none():
    client = _client(lambda request: httpx.Response(502, text="bad gateway"))

    assert client.balance() is None


def test_a_timeout_becomes_none():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    assert _client(handler).balance() is None


def test_a_response_that_is_not_json_becomes_none():
    client = _client(lambda request: httpx.Response(200, text="<html>maintenance</html>"))

    assert client.balance() is None


def test_a_failure_never_writes_a_credential_to_the_log(caplog):
    """The one credential test this phase can run. Nothing here may leak a key."""

    def handler(request):
        raise httpx.ConnectError(
            f"connection failed for {CREDENTIALS.api_key} with {CREDENTIALS.api_secret}",
            request=request,
        )

    with caplog.at_level(logging.WARNING):
        assert _client(handler).balance() is None

    written = caplog.text
    assert CREDENTIALS.api_key not in written
    assert CREDENTIALS.api_secret not in written


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
    assert result["txid"] == ["OABCDE-12345-XYZ"]


def test_a_tiny_volume_is_sent_in_full_not_in_scientific_notation():
    """`str(Decimal("0.00000001"))` is "1E-8", which Kraken refuses."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"txid": ["X"]})

    _client(handler).add_order(
        pair="XXBTZEUR", side="sell", volume=D("0.00000001"), cl_ord_id="abc123"
    )

    assert "volume=0.00000001" in seen["body"]


def test_a_validate_only_order_says_so():
    """No integration test places a real order. This is how that rule is kept."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({})

    _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("1"), cl_ord_id="abc123", validate=True
    )

    assert "validate=true" in seen["body"]


def test_open_orders_can_be_filtered_by_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"open": {"OABC": {"cl_ord_id": "abc123", "status": "open"}}})

    orders = _client(handler).open_orders(cl_ord_id="abc123")

    assert "cl_ord_id=abc123" in seen["body"]
    assert orders["OABC"]["status"] == "open"


def test_closed_orders_can_be_filtered_by_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"closed": {"OABC": {"cl_ord_id": "abc123", "status": "closed"}}})

    orders = _client(handler).closed_orders(cl_ord_id="abc123")

    assert "cl_ord_id=abc123" in seen["body"]
    assert orders["OABC"]["status"] == "closed"


def test_the_http_client_is_always_built_with_a_timeout():
    """One stalled call on a single-worker scheduler blocks every later tick."""
    http = build_http_client(timeout_seconds=7.5)

    assert http.timeout.read == 7.5
    assert http.timeout.connect == 7.5
    http.close()


def test_a_pair_that_is_not_online_comes_back_untradable():
    frozen = {"XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "status": "cancel_only"}}
    client = _client(lambda request: _ok(frozen))

    assert client.asset_pairs()["XXBTZEUR"].tradable is False


def test_an_asset_pair_missing_a_field_is_skipped_rather_than_crashing_the_read():
    """One malformed pair must not cost the caller every other pair in the response."""
    payload = {"GOOD": ASSET_PAIRS["XXBTZEUR"], "BROKEN": {"altname": "X"}}
    client = _client(lambda request: _ok(payload))

    pairs = client.asset_pairs()

    assert set(pairs) == {"GOOD"}

```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_client.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.client'`

- [ ] **Step 3: Write `exchange/client.py`**

```python
"""The only module in this system that speaks HTTP to Kraken.

Everything that can fail returns `None`. A missed evaluation is recoverable and a crashed
process is not, so no network problem is ever allowed to escape as an exception.

The one thing that does raise is asking for a private call with no credentials. That is a
bug in the caller, not an outage, and returning `None` would hide it among the real ones.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

import httpx

from exchange.limits import PUBLIC_BUCKET, KeyLimiter
from exchange.precision import format_decimal
from exchange.signing import encode_body, sign
from exchange.types import Credentials, PairMeta

logger = logging.getLogger("coinpilot.exchange")

KRAKEN_BASE_URL = "https://api.kraken.com"


class MissingCredentials(Exception):
    """A private endpoint was asked for on a client that has no key."""


def build_http_client(timeout_seconds: float = 10.0) -> httpx.Client:
    """The transport, always with a timeout.

    httpx defaults to five seconds, but stating it here means nobody can build one
    without a bound by accident. One stalled call on a single-worker scheduler blocks
    every later tick.
    """
    return httpx.Client(base_url=KRAKEN_BASE_URL, timeout=timeout_seconds)


def _is_error(entry: object) -> bool:
    """Kraken prefixes an error with `E` and a warning with `W`."""
    return str(entry).startswith("E")


def _decimal(raw: object) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


class KrakenClient:
    """One authenticated identity against Kraken.

    The credentials are optional. A client without them still reads public data, which is
    what the scheduler uses for its one shared price fetch per tick.
    """

    def __init__(
        self,
        http: httpx.Client,
        limiter: KeyLimiter,
        credentials: Credentials | None = None,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._credentials = credentials

    # ----- the two ways in -------------------------------------------------

    def _public(self, endpoint: str, params: Mapping[str, str] | None = None) -> dict | None:
        def call() -> dict:
            self._limiter.wait_turn(PUBLIC_BUCKET)
            response = self._http.get(f"/0/public/{endpoint}", params=dict(params or {}))
            response.raise_for_status()
            return self._unwrap(response.json())

        return self._safely(call, endpoint)

    def _private(self, endpoint: str, payload: Mapping[str, str] | None = None) -> dict | None:
        if self._credentials is None:
            raise MissingCredentials(endpoint)
        key = self._credentials.api_key
        path = f"/0/private/{endpoint}"

        def call() -> dict:
            self._limiter.wait_turn(key)
            nonce = self._limiter.next_nonce(key)
            body = encode_body({"nonce": nonce, **dict(payload or {})})
            headers = {
                "API-Key": key,
                "API-Sign": sign(path, nonce, body, self._credentials.api_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            response = self._http.post(path, content=body, headers=headers)
            response.raise_for_status()
            return self._unwrap(response.json())

        return self._safely(call, endpoint)

    def _unwrap(self, payload: dict) -> dict:
        errors = [entry for entry in payload.get("error", []) if _is_error(entry)]
        if errors:
            raise RuntimeError(f"kraken returned {errors}")
        return payload.get("result", {})

    def _safely(self, call, endpoint: str) -> dict | None:
        try:
            return call()
        except Exception as exc:
            logger.warning("kraken %s failed: %s", endpoint, self._redact(str(exc)))
            return None

    def _redact(self, text: str) -> str:
        """Nothing this module writes may carry a credential, whatever produced it.

        An exception raised deep in a transport can quote the request it was building.
        Redacting at the one place that logs is cheaper than auditing every path that
        could reach it.
        """
        if self._credentials is None:
            return text
        return text.replace(self._credentials.api_key, "***").replace(
            self._credentials.api_secret, "***"
        )

    # ----- public data -----------------------------------------------------

    def asset_pairs(self, pairs: list[str] | None = None) -> dict[str, PairMeta] | None:
        """Every tradable pair, or the ones named, as value objects.

        A pair missing a field is skipped rather than raised on: one malformed entry must
        not cost the caller every other pair in the response.
        """
        params = {"pair": ",".join(pairs)} if pairs else None
        raw = self._public("AssetPairs", params)
        if raw is None:
            return None

        parsed: dict[str, PairMeta] = {}
        for name, entry in raw.items():
            try:
                parsed[name] = PairMeta(
                    pair=name,
                    altname=entry["altname"],
                    base=entry["base"],
                    quote=entry["quote"],
                    price_decimals=int(entry["pair_decimals"]),
                    volume_decimals=int(entry["lot_decimals"]),
                    order_min=Decimal(str(entry["ordermin"])),
                    cost_min=Decimal(str(entry["costmin"])),
                    status=str(entry["status"]),
                )
            except (KeyError, TypeError, ValueError, InvalidOperation):
                logger.warning("skipping unreadable asset pair %s", name)
        return parsed

    def ticker(self, pairs: list[str]) -> dict[str, Decimal] | None:
        """The last traded price of each pair. `c` is [price, lot volume]."""
        raw = self._public("Ticker", {"pair": ",".join(pairs)})
        if raw is None:
            return None
        prices: dict[str, Decimal] = {}
        for name, entry in raw.items():
            price = _decimal((entry.get("c") or [None])[0])
            if price is not None:
                prices[name] = price
        return prices

    # ----- private data ----------------------------------------------------

    def api_key_info(self) -> dict | None:
        """Requires no permission to call, which is why key validation starts here."""
        return self._private("GetApiKeyInfo")

    def balance(self) -> dict[str, Decimal] | None:
        raw = self._private("Balance")
        if raw is None:
            return None
        balances: dict[str, Decimal] = {}
        for asset, amount in raw.items():
            value = _decimal(amount)
            if value is not None:
                balances[asset] = value
        return balances

    def add_order(
        self,
        pair: str,
        side: str,
        volume: Decimal,
        cl_ord_id: str,
        validate: bool = False,
    ) -> dict | None:
        """A market order, always.

        There is no price and no order that rests between ticks, so there is nothing to
        reprice, nothing to cancel and no order state machine. `validate=True` has Kraken
        check the order and never send it to the matching engine.
        """
        payload = {
            "pair": pair,
            "type": side,
            "ordertype": "market",
            "volume": format_decimal(volume),
            "cl_ord_id": cl_ord_id,
        }
        if validate:
            payload["validate"] = "true"
        return self._private("AddOrder", payload)

    def open_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("OpenOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("open", {})

    def closed_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("ClosedOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("closed", {})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_client.py -v --no-cov`
Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add exchange/client.py tests/unit/exchange/test_client.py
git commit -m "feat(exchange): the Kraken client, and None on every failure"
```

---

### Task 5: Kraken's order vocabulary, translated

**Files:**
- Create: `exchange/orders.py`
- Create: `tests/unit/exchange/test_orders.py`

**Interfaces:**
- Consumes: `exchange.types.ExchangeOrderStatus`
- Produces:
  - `map_order_status(raw: object) -> ExchangeOrderStatus`
  - `new_cl_ord_id() -> str`

**Rules this implements** (spec §4.2, §9.2):
- `expired` folds into `CANCELED`. Both mean off the book with nothing more coming.
- A status this code does not model becomes `UNKNOWN`, never a guess. An order the system
  cannot read must be reported, not assumed.
- One client id per **attempt**, never per order and never reused. Kraken requires
  uniqueness among open orders, and a reused id would make a lost response unresolvable.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_orders.py`:

```python
import pytest

from exchange.orders import map_order_status, new_cl_ord_id
from exchange.types import ExchangeOrderStatus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pending", ExchangeOrderStatus.PENDING),
        ("open", ExchangeOrderStatus.OPEN),
        ("closed", ExchangeOrderStatus.CLOSED),
        ("canceled", ExchangeOrderStatus.CANCELED),
    ],
)
def test_every_status_kraken_publishes_is_translated(raw, expected):
    assert map_order_status(raw) == expected


def test_expired_and_canceled_mean_the_same_thing_here():
    """Both are off the book with nothing more coming, so nothing downstream needs to
    tell them apart."""
    assert map_order_status("expired") == ExchangeOrderStatus.CANCELED


def test_a_status_this_code_does_not_model_is_unknown_not_a_guess():
    """An order the system cannot read must be reported, never assumed."""
    assert map_order_status("partially_filled") == ExchangeOrderStatus.UNKNOWN


def test_a_missing_status_is_unknown():
    assert map_order_status(None) == ExchangeOrderStatus.UNKNOWN
    assert map_order_status("") == ExchangeOrderStatus.UNKNOWN


def test_a_client_id_is_krakens_short_uuid_form():
    """Thirty-two hexadecimal characters, no dashes. Kraken also accepts free text up to
    eighteen characters, which is too narrow to be unique without coordination."""
    minted = new_cl_ord_id()

    assert len(minted) == 32
    assert all(character in "0123456789abcdef" for character in minted)


def test_two_client_ids_never_collide():
    assert new_cl_ord_id() != new_cl_ord_id()


def test_a_client_id_fits_the_ledger_column():
    """`orders.cl_ord_id` is String(64)."""
    assert len(new_cl_ord_id()) <= 64
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_orders.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.orders'`

- [ ] **Step 3: Write `exchange/orders.py`**

```python
"""Kraken's order vocabulary, and the identifier this system puts on every attempt."""

from __future__ import annotations

import uuid

from exchange.types import ExchangeOrderStatus

# Kraken publishes exactly these five. `expired` folds into `CANCELED` because both mean
# off the book with nothing more coming, and nothing downstream needs to tell them apart.
_KRAKEN_STATUS = {
    "pending": ExchangeOrderStatus.PENDING,
    "open": ExchangeOrderStatus.OPEN,
    "closed": ExchangeOrderStatus.CLOSED,
    "canceled": ExchangeOrderStatus.CANCELED,
    "expired": ExchangeOrderStatus.CANCELED,
}


def map_order_status(raw: object) -> ExchangeOrderStatus:
    """Translate one Kraken status.

    Anything unmodelled becomes `UNKNOWN` rather than a nearby guess. An order the system
    cannot read has to be reported, and a guess here would be a guess about money.
    """
    return _KRAKEN_STATUS.get(str(raw), ExchangeOrderStatus.UNKNOWN)


def new_cl_ord_id() -> str:
    """One identifier per attempt.

    Never per order and never reused: Kraken requires uniqueness among open orders, and a
    reused id would make a lost response impossible to resolve.

    Thirty-two hexadecimal characters is Kraken's short-UUID form. Its free-text form
    allows eighteen characters, which is too narrow to be unique without coordination.
    """
    return uuid.uuid4().hex
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_orders.py -v --no-cov`
Expected: 10 passed — 4 parametrised statuses and 6 plain tests.

- [ ] **Step 5: Commit**

```bash
git add exchange/orders.py tests/unit/exchange/test_orders.py
git commit -m "feat(exchange): order status translation and the client identifier"
```

---

### Task 6: Resolving an order whose response was lost

**Files:**
- Modify: `exchange/orders.py`
- Create: `tests/unit/exchange/test_find_order.py`

**Interfaces:**
- Consumes: `exchange.client.KrakenClient`, `exchange.types.OrderLookup`, `map_order_status`
- Produces: `find_order_by_cl_ord_id(client, cl_ord_id) -> OrderLookup | None`

**Rules this implements** (spec §9.2):

This is the highest-risk function in the system. `_safe_call` returns `None`, and `None`
cannot tell *the request never arrived* from *Kraken executed it and the reply was lost*.
Re-sending on the first reading buys twice; not re-sending on the second silently fails
to do the job. This function is what separates them, and it has exactly three answers:

| Return | Meaning | What phase 5 does with it |
|---|---|---|
| An `OrderLookup` with a txid | The order exists | Adopt it, read the fill, mark `FILLED` |
| `None` | The lookup itself failed | Still unknown: stay `PENDING`, skip this user |
| `OrderLookup(txid=None, status=None)` | Both endpoints answered and neither had it | Mark `FAILED`; the next plan retries |

**A lookup failure is "unknown", never "absent."** The two readings differ by a duplicate
order.

Three further rules the tests pin:

- **Open orders are asked first**, and a hit there returns without asking the closed ones.
  A resting order must win over a terminal one carrying the same id: adopting the dead
  txid would finalise the trade and orphan a live order.
- **One failing endpoint never hides a clean hit on the other.** The failure only decides
  the answer once neither endpoint produced a match.
- **Rows that do not echo the id are unresolved, not absent.** Kraken is asked to filter;
  if it ever stopped honouring the filter, this is the difference between failing loudly
  and adopting a stranger's txid.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_find_order.py`:

```python
from decimal import Decimal

from exchange.orders import find_order_by_cl_ord_id
from exchange.types import ExchangeOrderStatus

D = Decimal
CL_ORD_ID = "abc123"


def _order(status: str = "closed", cl_ord_id: str = CL_ORD_ID) -> dict:
    return {
        "cl_ord_id": cl_ord_id,
        "status": status,
        "vol": "0.00212765",
        "vol_exec": "0.00212765",
        "price": "47000.5",
        "fee": "0.40",
    }


class FakeClient:
    """Answers the two lookups with whatever the test hands it, and counts the calls.

    `None` stands for an endpoint that could not be read at all.
    """

    def __init__(self, open_result, closed_result):
        self._open = open_result
        self._closed = closed_result
        self.calls: list[str] = []

    def open_orders(self, cl_ord_id=None):
        self.calls.append("open")
        return self._open

    def closed_orders(self, cl_ord_id=None):
        self.calls.append("closed")
        return self._closed


def test_an_order_still_on_the_book_resolves_to_its_txid():
    client = FakeClient({"OABC-1": _order("open")}, {})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-1"
    assert found.status == ExchangeOrderStatus.OPEN


def test_a_finished_order_resolves_from_the_closed_endpoint():
    client = FakeClient({}, {"OABC-2": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-2"
    assert found.status == ExchangeOrderStatus.CLOSED


def test_the_fill_comes_back_as_decimals():
    client = FakeClient({}, {"OABC-2": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.volume == D("0.00212765")
    assert found.volume_executed == D("0.00212765")
    assert found.price == D("47000.5")
    assert found.fee == D("0.40")


def test_an_expired_order_reads_as_canceled():
    client = FakeClient({}, {"OABC-3": _order("expired")})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID).status == ExchangeOrderStatus.CANCELED


def test_a_live_order_wins_over_a_dead_one_carrying_the_same_id():
    """Adopting the dead txid would finalise the trade and orphan a live order."""
    client = FakeClient({"LIVE": _order("open")}, {"DEAD": _order("canceled")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "LIVE"


def test_the_closed_endpoint_is_not_asked_once_the_open_one_answers():
    client = FakeClient({"LIVE": _order("open")}, {})

    find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert client.calls == ["open"]


def test_both_endpoints_answering_empty_is_a_genuine_absence():
    """Evidence that nothing landed. Phase 5 marks the attempt failed and retries."""
    client = FakeClient({}, {})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found is not None
    assert found.txid is None
    assert found.status is None


def test_an_endpoint_that_could_not_be_read_makes_the_whole_lookup_unknown():
    """The two readings differ by a duplicate order, so absence is never assumed."""
    client = FakeClient(None, {})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_both_endpoints_failing_is_unknown():
    client = FakeClient(None, None)

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_one_failing_endpoint_does_not_hide_a_clean_hit_on_the_other():
    client = FakeClient(None, {"OABC-4": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-4"


def test_rows_that_do_not_echo_the_id_are_unknown_not_absent():
    """Kraken is asked to filter. If it ever stopped, this is the difference between
    failing loudly and adopting a stranger's txid."""
    client = FakeClient({"SOMEONE-ELSE": _order(cl_ord_id="different")}, {})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_a_field_kraken_omits_reads_as_zero_rather_than_crashing():
    client = FakeClient({}, {"OABC-5": {"cl_ord_id": CL_ORD_ID, "status": "closed"}})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.volume == D("0")
    assert found.fee == D("0")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_find_order.py -v --no-cov`
Expected: FAIL, `ImportError: cannot import name 'find_order_by_cl_ord_id'`

- [ ] **Step 3: Extend `exchange/orders.py`**

Replace the import block. The `exchange.types` line already exists and gains a name;
the other two are new. `ruff format` will settle the layout.

```python
from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from exchange.types import ExchangeOrderStatus, OrderLookup

ZERO = Decimal("0")
```

Then append:

```python
def _as_decimal(raw: object) -> Decimal:
    """A field Kraken omitted reads as zero. A partial answer is still an answer, and
    crashing here would turn a readable order into an unresolvable one."""
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _match(orders: dict[str, dict], cl_ord_id: str) -> OrderLookup | None:
    """The first order that echoes the id we asked for, as a value object."""
    for txid, order in orders.items():
        if order.get("cl_ord_id") != cl_ord_id:
            continue
        return OrderLookup(
            txid=txid,
            status=map_order_status(order.get("status")),
            volume=_as_decimal(order.get("vol")),
            volume_executed=_as_decimal(order.get("vol_exec")),
            price=_as_decimal(order.get("price")),
            fee=_as_decimal(order.get("fee")),
        )
    return None


ABSENT = OrderLookup(
    txid=None, status=None, volume=ZERO, volume_executed=ZERO, price=ZERO, fee=ZERO
)


def find_order_by_cl_ord_id(client, cl_ord_id: str) -> OrderLookup | None:
    """Resolve a client id to Kraken's txid when the txid itself was never received.

    Three answers, and the difference between the last two is a duplicate order:

    - an `OrderLookup` with a txid — the order exists
    - `None` — the lookup itself failed, so the outcome is still **unknown**
    - `ABSENT` — both endpoints answered and neither had it, which is **evidence**

    Open orders are asked first. A resting order must win over a terminal one carrying
    the same id, because adopting the dead txid would finalise the trade and orphan a
    live one. The cost is a second call in the common case, on a path that only runs
    after a lost response.
    """
    lookups: tuple[Callable[..., dict[str, dict] | None], ...] = (
        client.open_orders,
        client.closed_orders,
    )
    unresolved = False

    for fetch in lookups:
        orders = fetch(cl_ord_id=cl_ord_id)
        if orders is None:
            # Could not ask. Decide nothing from this endpoint.
            unresolved = True
            continue
        if not orders:
            # Asked, and it is not here. That is evidence.
            continue
        found = _match(orders, cl_ord_id)
        if found is not None:
            return found
        # Rows came back and none echo the id. Either they are not ours or the filter was
        # ignored, and those two are indistinguishable from here.
        unresolved = True

    return None if unresolved else ABSENT
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_find_order.py -v --no-cov`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add exchange/orders.py tests/unit/exchange/test_find_order.py
git commit -m "feat(exchange): resolve an order whose response was lost"
```

---

### Task 7: The permission contract

**Files:**
- Create: `exchange/keys.py`
- Create: `tests/unit/exchange/test_keys.py`

**Interfaces:**
- Consumes: `exchange.client.KrakenClient`, `exchange.types.KeyRejection`, `exchange.types.KeyValidation`
- Produces:
  - `REQUIRED_PERMISSIONS: frozenset[str]`
  - `FORBIDDEN_PERMISSIONS: frozenset[str]`
  - `validate_key(client) -> KeyValidation`

**Rules this implements** (spec §5.2):

| | Permissions |
|---|---|
| **Required** | `query-funds`, `modify-trades`, `query-open-trades`, `query-closed-trades` |
| **Forbidden** | `withdraw-funds`, `add-withdraw-address`, `update-withdraw-address` |

- `GetApiKeyInfo` requires no permission to call, so it is the first call made. Validation
  is a **read**, not a probe: nothing is attempted to see whether it is allowed.
- `query-open-trades` and `query-closed-trades` are required because
  `find_order_by_cl_ord_id` calls both endpoints.
- The two withdraw-address permissions are refused although neither can move funds alone.
  Staging an address is the step before a withdrawal, if the withdrawal permission is ever
  enabled.
- **A key that fails is rejected and never stored.** So is a key that could not be read:
  an unreachable Kraken is a rejection, because storing an unvalidated key is exactly
  what this contract exists to prevent.
- The check runs **once, at registration**. A permission can be widened afterwards and
  this system cannot observe that, so it does not pretend to.

- [ ] **Step 1: Write the failing tests**

`tests/unit/exchange/test_keys.py`:

```python
from exchange.keys import FORBIDDEN_PERMISSIONS, REQUIRED_PERMISSIONS, validate_key
from exchange.types import KeyRejection

ENOUGH = [
    "query-funds",
    "modify-trades",
    "query-open-trades",
    "query-closed-trades",
]


class FakeClient:
    """Returns whatever `GetApiKeyInfo` is supposed to have said. `None` means the call
    could not be made at all."""

    def __init__(self, info):
        self._info = info

    def api_key_info(self):
        return self._info


def _info(permissions, ip_allowlist=()):
    return {"permissions": list(permissions), "ipAllowlist": list(ip_allowlist)}


def test_a_key_with_exactly_what_is_needed_is_accepted():
    result = validate_key(FakeClient(_info(ENOUGH)))

    assert result.accepted is True
    assert result.rejection is None
    assert result.missing == ()
    assert result.forbidden == ()


def test_a_harmless_extra_permission_does_not_matter():
    """Only the forbidden list is refused. Everything else is the user's business."""
    result = validate_key(FakeClient(_info([*ENOUGH, "query-ledger", "export-data"])))

    assert result.accepted is True


def test_a_key_missing_a_required_permission_is_refused_and_says_which():
    result = validate_key(FakeClient(_info(["query-funds", "modify-trades"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.MISSING_PERMISSIONS
    assert set(result.missing) == {"query-open-trades", "query-closed-trades"}


def test_a_key_that_can_withdraw_is_refused():
    """The whole point of the contract. A stolen key can trade; it cannot drain."""
    result = validate_key(FakeClient(_info([*ENOUGH, "withdraw-funds"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS
    assert result.forbidden == ("withdraw-funds",)


def test_a_key_that_can_add_a_withdrawal_address_is_refused():
    """It cannot move funds on its own. It is the step before something that can."""
    result = validate_key(FakeClient(_info([*ENOUGH, "add-withdraw-address"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS


def test_a_key_that_can_change_a_withdrawal_address_is_refused():
    result = validate_key(FakeClient(_info([*ENOUGH, "update-withdraw-address"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS


def test_a_key_that_is_both_short_and_dangerous_reports_the_danger():
    """Both facts are returned, and the one named as the reason is the security one."""
    result = validate_key(FakeClient(_info(["query-funds", "withdraw-funds"])))

    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS
    assert result.forbidden == ("withdraw-funds",)
    assert "modify-trades" in result.missing


def test_a_kraken_that_cannot_be_reached_is_a_rejection_not_an_acceptance():
    """Storing a key that was never validated is exactly what this contract prevents."""
    result = validate_key(FakeClient(None))

    assert result.accepted is False
    assert result.rejection is KeyRejection.UNREACHABLE
    assert result.permissions == ()


def test_a_response_with_no_permissions_field_is_refused():
    result = validate_key(FakeClient({}))

    assert result.accepted is False
    assert result.rejection is KeyRejection.MISSING_PERMISSIONS


def test_the_address_allowlist_is_surfaced():
    """So the user can see whether their key is already restricted to one address."""
    result = validate_key(FakeClient(_info(ENOUGH, ip_allowlist=["203.0.113.7"])))

    assert result.ip_allowlist == ("203.0.113.7",)


def test_the_two_lists_do_not_overlap():
    """A permission that was both required and forbidden would make every key fail."""
    assert REQUIRED_PERMISSIONS & FORBIDDEN_PERMISSIONS == frozenset()


def test_the_result_carries_no_part_of_the_key():
    """Nothing about validation may become a way to read a credential back."""
    result = validate_key(FakeClient(_info(ENOUGH)))

    assert "api_key" not in repr(result)
    assert "secret" not in repr(result).lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_keys.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'exchange.keys'`

- [ ] **Step 3: Write `exchange/keys.py`**

```python
"""Whether a Kraken key may be stored at all.

`GetApiKeyInfo` needs no permission to call, so this is a **read** and not a probe:
nothing is attempted in order to find out whether it is allowed.

The check runs once, when the key is registered. Permissions can be widened afterwards
and this system cannot observe that, so it does not pretend to. What the contract buys is
that a key the platform holds never *started* able to withdraw.
"""

from __future__ import annotations

from exchange.types import KeyRejection, KeyValidation

# `query-open-trades` and `query-closed-trades` are here because resolving a lost order
# response calls both OpenOrders and ClosedOrders.
REQUIRED_PERMISSIONS = frozenset(
    {"query-funds", "modify-trades", "query-open-trades", "query-closed-trades"}
)

# The two address permissions cannot move funds on their own. Staging an address is the
# step before a withdrawal, if the withdrawal permission is ever enabled.
FORBIDDEN_PERMISSIONS = frozenset(
    {"withdraw-funds", "add-withdraw-address", "update-withdraw-address"}
)

_UNREACHABLE = KeyValidation(
    accepted=False,
    rejection=KeyRejection.UNREACHABLE,
    permissions=(),
    missing=(),
    forbidden=(),
    ip_allowlist=(),
)


def validate_key(client) -> KeyValidation:
    """Read the key's permissions and decide whether it may be stored.

    A key that cannot be read is rejected, not deferred. Storing a key that was never
    validated is the one outcome this contract exists to prevent.
    """
    info = client.api_key_info()
    if info is None:
        return _UNREACHABLE

    granted = frozenset(str(entry) for entry in info.get("permissions", []))
    missing = tuple(sorted(REQUIRED_PERMISSIONS - granted))
    forbidden = tuple(sorted(FORBIDDEN_PERMISSIONS & granted))

    # Both facts are returned; the one named as the reason is the security one. A key that
    # can withdraw is a different kind of problem from a key that is merely incomplete.
    if forbidden:
        rejection = KeyRejection.FORBIDDEN_PERMISSIONS
    elif missing:
        rejection = KeyRejection.MISSING_PERMISSIONS
    else:
        rejection = None

    return KeyValidation(
        accepted=rejection is None,
        rejection=rejection,
        permissions=tuple(sorted(granted)),
        missing=missing,
        forbidden=forbidden,
        ip_allowlist=tuple(str(entry) for entry in info.get("ipAllowlist", [])),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/exchange/test_keys.py -v --no-cov`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add exchange/keys.py tests/unit/exchange/test_keys.py
git commit -m "feat(exchange): refuse a key that can withdraw"
```

---

### Task 8: The live check and the phase gate

**Files:**
- Create: `scripts/check_key.py`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything from tasks 1 to 7
- Produces: a verified phase 3. Nothing later depends on this task beyond the guarantee
  that the layer works against the real Kraken.

- [ ] **Step 1: Write `scripts/check_key.py`**

This is the instrument for the one check that cannot be a unit test: does this layer work
against the real Kraken, and does it really refuse a dangerous key.

It prints the permissions, never the key.

```python
"""Check a real Kraken key against the permission contract.

Run by hand. It reads the key from the environment, calls `GetApiKeyInfo`, and prints
what the key is allowed to do. It places no order and changes nothing.

    KRAKEN_API_KEY=... KRAKEN_API_SECRET=... PYTHONPATH=. python scripts/check_key.py
"""

from __future__ import annotations

import os
import sys

from exchange.client import KrakenClient, build_http_client
from exchange.keys import validate_key
from exchange.limits import KeyLimiter
from exchange.types import Credentials


def main() -> int:
    key = os.environ.get("KRAKEN_API_KEY", "")
    secret = os.environ.get("KRAKEN_API_SECRET", "")
    if not key or not secret:
        print("set KRAKEN_API_KEY and KRAKEN_API_SECRET", file=sys.stderr)
        return 2

    http = build_http_client()
    try:
        client = KrakenClient(http, KeyLimiter(1.0), Credentials(key, secret))
        result = validate_key(client)
    finally:
        http.close()

    print(f"accepted   : {result.accepted}")
    print(f"rejection  : {result.rejection or '-'}")
    print(f"permissions: {', '.join(result.permissions) or '-'}")
    print(f"missing    : {', '.join(result.missing) or '-'}")
    print(f"forbidden  : {', '.join(result.forbidden) or '-'}")
    print(f"ip allowed : {', '.join(result.ip_allowlist) or 'any address'}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Name the new settings in `.env.example`**

Append, keeping the existing entries:

```
# Only read by scripts/check_key.py. The application never reads a key from here.
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
```

- [ ] **Step 3: Run the whole suite with the gate**

```bash
docker compose -f docker-compose.dev.yml up -d
RUN_DB_INTEGRATION=true DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot PYTHONPATH=. pytest tests --cov-fail-under=80
```

Expected: 209 passed — the 125 from phases 1 and 2, plus 84 here.

- [ ] **Step 4: Prove the new tests need nothing but Python**

```bash
PYTHONPATH=. pytest tests/unit --no-cov
```

Expected: 121 passed, with no database running and nothing skipped. Every test in this
phase is a unit test, and none of them reaches the network.

- [ ] **Step 5: Run lint and format**

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 6: Commit and push**

```bash
git add scripts/check_key.py .env.example
git commit -m "feat(exchange): a script to check a real key against the contract"
git push -u origin feat/phase-3-kraken-layer
```

- [ ] **Step 7: Open the pull request and confirm CI is green**

```bash
gh pr create --base main --title "Phase 3: the Kraken layer" \
  --body "Per-user client, per-key pacing, status translation and the permission contract."
gh pr checks --watch
```

Expected: `pass`.

---

## What you verify before phase 4

Phases 1 to 3 cannot move money, because nothing is wired to an account. This phase adds
the ability to *reach* Kraken, and the checks below are the first that involve a real one.

### 1. The suite is green and CI agrees

Every test here runs with no network and no database, so `pytest tests/unit` is the fast
loop.

### 2. Read the three answers of `find_order_by_cl_ord_id`

This is the highest-risk function in the system, and the difference between two of its
answers is a duplicate order. Read
`tests/unit/exchange/test_find_order.py` and check each case against what you would want.
The rule to hold it to: **a lookup failure is unknown, never absent.**

### 3. Point it at a real key, and at a dangerous one

Create **two** Kraken API keys for this:

| Key | Permissions | Expected |
|---|---|---|
| A | Query Funds, Query Open Orders & Trades, Query Closed Orders & Trades, Create & Modify Orders | `accepted: True` |
| B | The same, **plus Withdraw Funds** | `accepted: False`, `forbidden: withdraw-funds` |

```bash
KRAKEN_API_KEY=... KRAKEN_API_SECRET=... PYTHONPATH=. python scripts/check_key.py
```

Key B is the one that matters. It is the difference between a compromise that costs a bad
trade and one that empties the account, and it is worth watching the refusal happen with
your own key rather than trusting a test.

**Delete key B as soon as you have seen it refused.** It is a key with withdrawal
permission and it has no other purpose.

### 4. Check what the script does not print

Read `scripts/check_key.py` and its output. Neither the key nor the secret appears
anywhere in it. The same rule holds inside the client: a failed call redacts both before
it writes a log line, and a test forces an exception carrying the secret to prove it.

### 5. One decision deserves a deliberate look

**An unreachable Kraken is a rejection, not a retry.** If the network fails while a user
is registering their key, the key is refused and they try again. The alternative — storing
it and validating later — means the system briefly holds a key it has not checked, which
is the one outcome the whole contract exists to prevent.

---

## Departures taken during execution

The code blocks above are the plan as written. Where the repository differs, trust the
repository.

| Where | What changed | Why |
|---|---|---|
| `requirements.txt` | `psycopg[binary]==3.3.6`, not 3.3.5 | Dependabot moved it after the plan was written. |
| `tests/unit/exchange/test_signing.py` | `# noqa: E501  # gitleaks:allow` on the vector secret | gitleaks blocked the commit: Kraken's published example has the entropy of a real key. It is public, and the exception is scoped to that one line. |
| `tests/unit/exchange/test_client.py` | A fake secret of base64 `this-is-a-test-secret`, marked `# gitleaks:allow` | Same scanner, same reason. |
| `tests/unit/exchange/test_client.py` | The redaction test also asserts `"connection failed" in written` | Without it the test passes on an empty log, which contains no key either. This assertion is what exposed the next row. |
| `scripts/migrations/env.py` | `fileConfig(..., disable_existing_loggers=False)` | The standard library's default disables every logger that already exists. The migrations ran after `coinpilot.exchange` was created and silenced it. In production, running migrations in-process would have muted every failed-call warning. |
| `tests/integration/test_schema.py` | A test that runs the migrations and asserts the logger stays on | Pins the previous row without depending on the order the suite runs in. The suite total is 210, not 209. |
| `tests/unit/exchange/test_keys.py` | `REQUIRED_PERMISSIONS.isdisjoint(FORBIDDEN_PERMISSIONS)` | Rule `SIM300` misreads the comparison with `frozenset()`, and `isdisjoint` says what the test means. |
