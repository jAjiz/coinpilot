# Phase 6 — Proposals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person asks for a rebalance with `POST /rebalance`, reads the proposal it
leaves, and approves it with `POST /proposal/approve`. The approval carries the version
read, and the rebalance executes as a unit: sells first, then buys with what the sells
raised.

**Architecture:** `core/execution.py` stays the only module that places an order. It
learns to size and send a sell, and to fit the buys inside what there is to spend. An
evaluation now takes a *decision*: once the plan is known and the lock is held, the
caller says whether to send it. `core/proposal_plan.py` is pure: it writes a plan as the
proposal stores it, and judges whether two plans differ materially. `core/rebalance.py`
holds the proposal lifecycle: propose, approve, withdraw. `api/routes/proposal.py` is a
thin layer over it.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, PostgreSQL, httpx.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.4, §7.2, §7.3, §8, §9, §11, §14

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 6 of 8

## Global Constraints

- **Python 3.13.** One version, not a range.
- **Money is `Decimal`, never `float`.** A JSON response carries every amount as a string,
  written without padding (`core.portfolio.plain_amount`). The proposal's `plan` column
  is JSON, so every amount in it is a string too.
- **Pin every dependency with `==`.** This phase adds none.
- **No test reads configuration from the environment.** `load_config` takes a mapping, and
  every test hands it a plain dict.
- **No test touches the network, and no test places a real order.** Kraken is answered by
  `httpx.MockTransport`.
- **No endpoint returns a Kraken credential**, not even in an error. No log line contains one.
- **Every endpoint is scoped to the authenticated user.** No route takes a user id.
- **Only `core/execution.py` places an order.** `tests/unit/core/test_layering.py`
  already fails if `add_order` appears anywhere else under `api/` or `core/`.
- **A rebalance never executes without an approval in this phase.** Not even with
  `auto_rebalance_enabled` on: executing a rebalance unapproved is the scheduler's, in
  phase 7.
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

Each of these, if wrong, sells something the user did not agree to sell. Each has a test
in the task that owns it.

1. **Nothing is sold without an approval of the version read.** `POST /rebalance` never
   sends an order. An approval of any other version is refused before Kraken is read. →
   Tasks 4 and 5.
2. **An approval executes only a plan that has not moved materially.** The plan is
   computed again under the lock. If it differs from what the user read by more than a
   leg's minimum, nothing is sent and the new plan becomes the next version. → Task 4.
3. **A version number is never reused.** A proposal made after a withdrawn or executed
   one takes the next number, so an approval meant for the old one cannot reach it. →
   Task 4.
4. **Buys never ask for more fiat than there is.** They are fitted inside the free cash
   plus what the sells raised, as the ledger reports it, and shrink together when that
   falls short. → Task 3.
5. **After an unknown answer to a sell, no buy is sent.** What the sell raised is unknown,
   and so is the balance. → Task 3.
6. **An exit sells the whole position.** A target of 0 % sells the balance read, so no
   dust is left that Kraken would refuse to take. → Task 3.

---

## What Kraken says

| Fact | Source |
|---|---|
| `oflags`: `fciq` is "prefer fee in quote currency (default if buying, mutually exclusive with `fcib`)"; `fcib` is "prefer fee in base currency (default if selling)" | [AddOrder](https://docs.kraken.com/api-reference/trading/add-order) |
| `viqc` is accepted on buy market orders only, so a sell is placed as a volume of the base asset | [AddOrder](https://docs.kraken.com/api-reference/trading/add-order) |
| A buy placed with `viqc,fcib` reports `cost` in fiat, `vol_exec` in the asset (gross), and `fee` in fiat | Verified on the first real order, spec §9.1 |
| A sell reports `cost` as the gross proceeds in fiat, `vol_exec × price`, and `fee` in fiat. A past limit sell of the user's, 1.67940915 ETH at an average of 1,487.18 EUR, shows `cost` 2,497.60049 EUR (the sum of its two trades) and `fee` 4.9952 EUR | The user's order `OAQXD6-7GLKC-VPNFRN` |
| **Open:** that a sell placed with `fciq` *takes* its fee in fiat, so that `cost − fee` is what reached the account. The order above does not settle it: the first buy also reported its fee in fiat although Kraken took it in the asset | Kraken's ledger for the first real sell |

**Why `fciq` on every sell.** By Kraken's default a sell pays its fee in the asset sold.
An exit that sells the whole balance would then lack the asset to pay the fee, and every
other sell would sell slightly more than its volume. With `fciq` the volume sent is the
volume sold, and the fee comes out of the proceeds.

---

## File Structure

| File | Responsibility |
|---|---|
| `exchange/client.py` | `add_order` places every sell with `oflags=fciq` |
| `core/proposal_plan.py` | Pure: `plan_document`, `has_orders`, `is_material` |
| `core/execution.py` | Sizes sells, fits buys inside the budget, takes a decision; `evaluate`, `EvaluationResult`, `PlannedLeg`, `Planned`, `Decision` |
| `core/rebalance.py` | The proposal lifecycle: `propose`, `approve`, `current`, `withdraw` |
| `api/evaluation.py` | What the evaluation routes share: the leg's shape and the error answers |
| `api/routes/invest.py` | Rewritten over `api/evaluation.py` |
| `api/routes/proposal.py` | `POST /rebalance`, `GET /proposal`, `POST /proposal/approve`, `DELETE /proposal` |
| `api/schemas.py` | `LegOut.side`, `LegOut.volume`; `ProposalLegOut`, `ProposalOut`, `ApproveIn`, `RebalanceOut` |
| `api/app.py` | Includes the proposal router |
| `tests/integration/conftest.py` | `FakeKraken` fills a sell |

---

## Decisions taken in this plan

The spec settles what to build. These settle how, where the spec leaves room. The user
chose the first four while this plan was being written.

- **A material change is measured against each leg's effective minimum.** The larger of
  Kraken's minimum at the current price and `min_order_fiat` (§7.3). The spec said
  `min_order_fiat`, which defaults to 0, and a threshold of 0 would make every price move
  a new version. Spec §8 is updated.
- **An approval computes the plan again.** Under the lock it resolves, reads and plans. If
  the fresh plan does not differ materially from the version approved, the **fresh** plan
  executes, with today's amounts. If it does, it is stored as the next version, the answer
  is `409` with it, and nothing is sent.
- **Buys spend the free cash plus what the sells raised, read from the ledger.** The budget
  is the fiat above the cash target when the account was read, plus `cost − fee` of each
  sell that came back `FILLED`. When the buys ask for more, every one shrinks by the same
  factor, and a buy that falls below its minimum is skipped and logged. The balance is not
  read again between the sells and the buys: it may not reflect them yet (§9.2).
- **An exit sells the whole balance.** A target of 0 % sells the balance read, rounded
  down to the pair's volume precision. Any other sell is `amount ÷ price`, rounded down and
  never more than the balance.
- **An unchanged plan does not rewrite the proposal.** When a fresh `POST /rebalance` is not
  material, the stored plan stays what the user read. Rewriting it under the same version
  would let small moves add up, unseen, to a plan nobody approved.
- **The version never goes back.** It starts at 1. A material change, or a proposal after
  a withdrawn or executed one, takes the slot's version plus one.
- **The proposal is `EXECUTING` while its orders are sent, and `EXECUTED` after.** If the
  process dies between the two, the row stays `EXECUTING`. It is not offered for
  approval, and the next `POST /rebalance` overwrites it from the real balance.
- **An approval that finds the drift gone withdraws the proposal** and answers `409`, with
  no proposal.
- **Two new evaluation statuses.** `PROPOSED`: a rebalance was computed and is waiting.
  `SUPERSEDED`: an approval met a plan that had changed, and sent nothing.
- **`EvaluationResult` replaces `InvestResult`.** One evaluation shape for both operations.
  Each leg now says its `side`, and a sell its `volume`.

## What this phase deliberately leaves out

- **The scheduler**, and with it every automatic rebalance — phase 7.
  `auto_rebalance_enabled` is stored and not consulted.
- **A preview of a rebalance.** The proposal is the preview: it is read before anything
  is sent.
- **`paused`.** Not consulted by any endpoint in this phase.

---

### Task 1: A sell pays its fee in fiat

**Files:**
- Modify: `exchange/client.py` (`add_order`)
- Test: `tests/unit/exchange/test_client.py`

**Interfaces:**
- Produces: `KrakenClient.add_order(pair, "sell", volume, cl_ord_id)` sends `oflags=fciq`.
  The signature does not change.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/exchange/test_client.py`:

```python
def test_a_sell_is_a_volume_of_the_asset_and_pays_its_fee_in_fiat():
    """`fciq`: the volume sent is the volume sold, so an exit can sell everything (spec §9.1)."""
    seen = {}

    def handler(request):
        seen["form"] = parse_qs(request.content.decode())
        return _ok({"txid": ["OTX"]})

    _client(handler).add_order(pair="XXBTZEUR", side="sell", volume=D("0.004"), cl_ord_id="abc123")

    assert seen["form"]["type"] == ["sell"]
    assert seen["form"]["volume"] == ["0.004"]
    assert seen["form"]["oflags"] == ["fciq"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/exchange/test_client.py -k fee_in_fiat -v`
Expected: FAIL with `KeyError: 'oflags'`

- [ ] **Step 3: Implement**

In `exchange/client.py`, in `add_order`, replace the docstring's first paragraph and the
`oflags` lines.

Replace:

```python
        """A market order, always, and what became of the request.

        `in_quote=True` makes `volume` an amount of the quote currency and takes the fee
        in the asset bought (`viqc`, `fcib`), so the order spends exactly that amount
        (spec §9.1). Kraken accepts it on buys only. `validate=True` has Kraken check the
        order and never trade it.
```

with:

```python
        """A market order, always, and what became of the request.

        `in_quote=True` makes `volume` an amount of the quote currency and takes the fee
        in the asset bought (`viqc`, `fcib`), so the order spends exactly that amount
        (spec §9.1). Kraken accepts it on buys only. A sell always pays its fee in the
        quote currency (`fciq`): the volume sent is the volume sold, so selling a whole
        balance leaves nothing owed in the asset. `validate=True` has Kraken check the
        order and never trade it.
```

Replace:

```python
        if in_quote:
            payload["oflags"] = "viqc,fcib"
```

with:

```python
        if in_quote:
            payload["oflags"] = "viqc,fcib"
        elif side == "sell":
            payload["oflags"] = "fciq"
```

- [ ] **Step 4: Run the client tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/exchange/test_client.py -v`
Expected: all PASS. `test_a_tiny_volume_is_sent_in_full_not_in_scientific_notation` sends a
sell and checks only its volume, so it still passes.

- [ ] **Step 5: Commit**

```bash
git add exchange/client.py tests/unit/exchange/test_client.py
git commit -m "feat(exchange): a sell pays its fee in fiat, so the volume sent is the volume sold"
```

---

### Task 2: A plan as the proposal stores it, and what counts as material

**Files:**
- Create: `core/proposal_plan.py`
- Test: `tests/unit/core/test_proposal_plan.py`

**Interfaces:**
- Consumes: `core.portfolio.plain_amount`, `engine.types.Side`.
- Produces:
  - `plan_document(fiat: str, legs: Iterable[PlannedLegLike]) -> dict[str, object]`, where
    a leg has `asset: str`, `pair: str`, `side: Side`, `amount: Decimal`,
    `minimum: Decimal | None`, `note: str | None`. Shape:
    `{"fiat": "EUR", "legs": [{"asset", "pair", "side", "amount_fiat", "minimum_fiat", "note"}]}`,
    every amount a plain string, `side` the `Side` value (`"buy"`, `"sell"`).
  - `has_orders(document: Mapping) -> bool`: whether any leg would be sent (its `note` is null).
  - `is_material(old: Mapping, new: Mapping) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/core/test_proposal_plan.py`:

```python
from dataclasses import dataclass
from decimal import Decimal

from core.proposal_plan import has_orders, is_material, plan_document
from engine.types import Side

D = Decimal


@dataclass(frozen=True)
class Leg:
    asset: str
    pair: str
    side: Side
    amount: Decimal
    minimum: Decimal | None
    note: str | None = None


def _doc(*legs):
    return plan_document("EUR", legs)


SELL_XBT = Leg("XBT", "XXBTZEUR", Side.SELL, D("200.00000"), D("5"))
BUY_ETH = Leg("ETH", "XETHZEUR", Side.BUY, D("200.00000"), D("0.5"))


def test_every_amount_is_a_plain_string():
    document = _doc(SELL_XBT)

    assert document == {
        "fiat": "EUR",
        "legs": [
            {
                "asset": "XBT",
                "pair": "XXBTZEUR",
                "side": "sell",
                "amount_fiat": "200",
                "minimum_fiat": "5",
                "note": None,
            }
        ],
    }


def test_a_leg_kraken_does_not_trade_has_no_minimum():
    leg = Leg("SOL", "SOLEUR", Side.BUY, D("10"), None, "kraken does not trade SOLEUR now")

    assert _doc(leg)["legs"][0]["minimum_fiat"] is None


def test_a_plan_whose_every_leg_is_skipped_has_no_orders():
    skipped = Leg("ETH", "XETHZEUR", Side.BUY, D("0.1"), D("0.5"), "below the minimum")

    assert has_orders(_doc(SELL_XBT)) is True
    assert has_orders(_doc(skipped)) is False
    assert has_orders(_doc()) is False


def test_the_same_plan_is_not_material():
    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT, BUY_ETH)) is False


def test_a_move_within_the_legs_minimum_is_not_material():
    """XBT moves 5, exactly its minimum: not more than it."""
    moved = Leg("XBT", "XXBTZEUR", Side.SELL, D("205"), D("5"))

    assert is_material(_doc(SELL_XBT), _doc(moved)) is False


def test_a_move_beyond_the_legs_minimum_is_material():
    moved = Leg("ETH", "XETHZEUR", Side.BUY, D("200.6"), D("0.5"))

    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT, moved)) is True


def test_a_leg_that_appears_or_disappears_is_material():
    assert is_material(_doc(SELL_XBT), _doc(SELL_XBT, BUY_ETH)) is True
    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT)) is True


def test_a_leg_that_changes_side_is_material():
    bought = Leg("XBT", "XXBTZEUR", Side.BUY, D("200"), D("5"))

    assert is_material(_doc(SELL_XBT), _doc(bought)) is True


def test_a_skipped_leg_that_becomes_sendable_is_material():
    skipped = Leg("ETH", "XETHZEUR", Side.BUY, D("0.4"), D("0.5"), "below the minimum")
    sendable = Leg("ETH", "XETHZEUR", Side.BUY, D("0.6"), D("0.5"))

    assert is_material(_doc(SELL_XBT, skipped), _doc(SELL_XBT, sendable)) is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/core/test_proposal_plan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.proposal_plan'`

- [ ] **Step 3: Implement**

Create `core/proposal_plan.py`:

```python
"""A rebalance plan as the proposal stores it, and what counts as a material change.

Pure: no I/O. The document is JSON, and JSON has no decimal type, so every amount is a
plain string (spec §8, `core/db/proposals.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Protocol

from core.portfolio import plain_amount
from engine.types import Side


class PlannedLegLike(Protocol):
    asset: str
    pair: str
    side: Side
    amount: Decimal
    minimum: Decimal | None
    note: str | None


def plan_document(fiat: str, legs: Iterable[PlannedLegLike]) -> dict[str, object]:
    """Every leg, the skipped ones too: the reader sees why a leg is missing."""
    return {
        "fiat": fiat,
        "legs": [
            {
                "asset": leg.asset,
                "pair": leg.pair,
                "side": leg.side.value,
                "amount_fiat": plain_amount(leg.amount),
                "minimum_fiat": None if leg.minimum is None else plain_amount(leg.minimum),
                "note": leg.note,
            }
            for leg in legs
        ],
    }


def _sendable(document: Mapping) -> dict[tuple[str, str], Mapping]:
    return {(leg["asset"], leg["side"]): leg for leg in document["legs"] if leg["note"] is None}


def has_orders(document: Mapping) -> bool:
    """Whether any leg would be sent. A plan of skipped legs is nothing to approve."""
    return bool(_sendable(document))


def is_material(old: Mapping, new: Mapping) -> bool:
    """Whether `new` differs from `old` enough to need a fresh approval (spec §8).

    A leg that would be sent appears or disappears, and a change of side is both. Or one
    moves by more than its effective minimum in `new`: the larger of Kraken's minimum and
    the user's floor (§7.3). The minimum and not `min_order_fiat` alone, because the floor
    defaults to 0, and a threshold of 0 would make every price move a new version.
    """
    before, after = _sendable(old), _sendable(new)
    if before.keys() != after.keys():
        return True
    for key, leg in after.items():
        moved = abs(Decimal(leg["amount_fiat"]) - Decimal(before[key]["amount_fiat"]))
        # A sendable leg always has a minimum: only a leg Kraken does not trade lacks one,
        # and that leg carries a note.
        if moved > Decimal(leg["minimum_fiat"]):
            return True
    return False
```

- [ ] **Step 4: Run them to verify they pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit/core/test_proposal_plan.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add core/proposal_plan.py tests/unit/core/test_proposal_plan.py
git commit -m "feat(core): a proposal's plan as a document, and what counts as a material change"
```

---

### Task 3: The executor sells, and the sells fund the buys

**Files:**
- Modify: `core/execution.py` (rewritten whole; the block below is the complete file)
- Modify: `api/routes/invest.py` (one import, one annotation)
- Modify: `tests/integration/conftest.py` (`FakeKraken._add_order`)
- Create: `tests/integration/test_rebalance_execution.py`

**Interfaces:**
- Consumes: `add_order(..., "sell", volume, cl_ord_id)` from Task 1.
- Produces, for Task 4 and Task 5:
  - `evaluate(context, user_id, *, allow_sells: bool, reason: OrderReason, decide: Decision) -> EvaluationResult`.
    Raises `NotReady`, `EvaluationBusy`, `CredentialsUnreadable`.
  - `Decision = Callable[[Planned, list[str]], EvaluationStatus | None]`: `None` sends the
    plan, a status ends the evaluation with nothing sent. It runs under the lock, after
    the plan and the snapshot, and may write in transactions of its own. It may append to
    the log.
  - `Planned(view: PortfolioView, legs: tuple[PlannedLeg, ...], free_cash: Decimal)`.
  - `PlannedLeg(asset, pair, side: Side, amount: Decimal, minimum: Decimal | None, note: str | None, volume: Decimal | None = None, meta: PairMeta | None = None)`.
  - `EvaluationResult(status, preview, legs, messages)`, the former `InvestResult`.
  - `LegResult` gains `side: Side` (third field, required) and `volume: Decimal | None = None` (last).
  - `EvaluationStatus.PROPOSED`, `EvaluationStatus.SUPERSEDED`.
  - `invest(context, user_id, *, preview=False)` is unchanged from outside.

- [ ] **Step 1: Teach `FakeKraken` to fill a sell**

In `tests/integration/conftest.py`, in `FakeKraken._add_order`, replace from
`txid = f"OTX...` down to the closing `}` of `self.orders[txid] = {...}`:

```python
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
```

with:

```python
        txid = f"OTX{len(self.orders) + 1:03d}-AAAAA-BBBBBB"
        volume = Decimal(form["volume"])
        price = Decimal(self.prices[form["pair"]])
        if form["type"] == "sell":
            # A volume of the asset; `fciq` takes the fee from the proceeds, in fiat.
            proceeds = (volume * price).quantize(Decimal("0.00001"))
            vol_exec, cost, fee = volume, proceeds, (proceeds * Decimal("0.004")).quantize(Decimal("0.00001"))
        else:
            # An amount of fiat (`viqc`). Reported as on the first real order: cost and fee in fiat.
            vol_exec = (volume / price).quantize(Decimal("0.00000001"))
            cost, fee = volume, (volume * Decimal("0.004")).quantize(Decimal("0.00001"))
        filled = self.fill_status == "closed"
        self.orders[txid] = {
            "status": self.fill_status,
            "cl_ord_id": form["cl_ord_id"],
            "oflags": form.get("oflags", ""),
            "vol": form["volume"],
            "vol_exec": str(vol_exec) if filled else "0",
            "cost": str(cost) if filled else "0",
            "fee": str(fee) if filled else "0",
            "price": str(price) if filled else "0",
        }
```

Also replace both `f"buy {form['volume']} {form['pair']} @ market"` strings in
`_add_order` with `f"{form['type']} {form['volume']} {form['pair']} @ market"`.

The buy's fee was in the asset before, which the real order showed is not what Kraken
reports. Run the phase 5 tests to confirm none depended on it:

Run: the test command, with `tests/integration/test_execution.py tests/integration/test_api_invest.py tests/integration/test_settlement.py`
Expected: all PASS

- [ ] **Step 2: Write the failing tests**

Create `tests/integration/test_rebalance_execution.py`:

```python
"""The executor with sells allowed, driven directly. `core/rebalance.py` decides when to
call it; here the decision is a plain function, so the sending is tested on its own."""

import base64
from decimal import Decimal

import pytest

from core.db.orders import list_orders
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import latest_snapshot, list_evaluations
from core.db.types import OrderReason
from core.db.users import save_credentials
from core.execution import EvaluationStatus, LegStatus, evaluate, invest
from engine.types import Side
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
HALF_HALF = (("XBT", "XXBTZEUR", "50"), ("ETH", "XETHZEUR", "50"))
# At 50 000 and 2 500: 700 EUR of XBT and 300 EUR of ETH, no cash. Against 50/50 the
# plan sells 200 EUR of XBT and buys 200 EUR of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}


@pytest.fixture
def ready(app_context, db_session, make_user, fake_kraken):
    def _ready(weights=HALF_HALF, balance=DRIFTED):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        for asset, pair, pct in weights:
            upsert_asset(db_session, user.id, asset=asset, pair=pair, target_pct=D(pct))
        sealed = app_context.cipher.seal(user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(
            db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
        )
        fake_kraken.balance = dict(balance)
        return user

    return _ready


def _send(planned, log):
    return None


def _rebalance(app_context, user, decide=_send):
    return evaluate(app_context, user.id, allow_sells=True, reason=OrderReason.REBALANCE, decide=decide)


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_the_sell_goes_first_and_its_proceeds_fund_the_buy(app_context, fake_kraken, ready):
    """The sell raises 200 and pays 0.80 of fee: the buy shrinks from 200 to 199.20."""
    user = ready()

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.DONE
    sell, buy = _sent(fake_kraken)
    assert (sell["type"], sell["pair"], D(sell["volume"]), sell["oflags"]) == ("sell", "XXBTZEUR", D("0.004"), "fciq")
    assert (buy["type"], buy["pair"], D(buy["volume"]), buy["oflags"]) == ("buy", "XETHZEUR", D("199.2"), "viqc,fcib")
    assert [(leg.asset, leg.side, leg.status) for leg in result.legs] == [
        ("XBT", Side.SELL, LegStatus.FILLED),
        ("ETH", Side.BUY, LegStatus.FILLED),
    ]


def test_a_rebalance_writes_its_orders_with_its_reason(app_context, db_session, ready):
    user = ready()

    _rebalance(app_context, user)

    orders = {order.asset: order for order in list_orders(db_session, user.id)}
    assert (orders["XBT"].side, orders["XBT"].reason) == (Side.SELL, OrderReason.REBALANCE)
    assert orders["XBT"].requested_fiat == D("200")
    assert orders["XBT"].cost == D("200")
    assert orders["XBT"].fee == D("0.8")
    assert (orders["ETH"].side, orders["ETH"].requested_fiat) == (Side.BUY, D("199.2"))


def test_an_exit_sells_the_whole_balance(app_context, fake_kraken, ready):
    """XBT at 0 % is an exit. 0.0123456789 rounds down to the pair's eight places."""
    user = ready(
        weights=(("XBT", "XXBTZEUR", "0"), ("ETH", "XETHZEUR", "100")),
        balance={"ZEUR": "0", "XXBT": "0.0123456789", "XETH": "0.4"},
    )

    _rebalance(app_context, user)

    sell = next(form for form in _sent(fake_kraken) if form["type"] == "sell")
    assert D(sell["volume"]) == D("0.01234567")


def test_free_cash_above_the_target_is_spent_with_the_proceeds(app_context, fake_kraken, ready):
    """1000 of XBT and 1000 of cash at 50/50 with no cash target: sell 0, buy ETH 1000."""
    user = ready(balance={"ZEUR": "1000", "XXBT": "0.02", "XETH": "0"})

    _rebalance(app_context, user)

    (buy,) = _sent(fake_kraken)
    assert (buy["pair"], D(buy["volume"])) == ("XETHZEUR", D("1000"))


def test_a_refused_sell_leaves_nothing_to_buy_with(app_context, fake_kraken, ready):
    user = ready()

    def refuse_sells(form):
        fake_kraken.add_order_errors = ["EOrder:Insufficient funds"] if form["type"] == "sell" else []

    fake_kraken.on_add_order = refuse_sells

    result = _rebalance(app_context, user)

    legs = {leg.asset: leg for leg in result.legs}
    assert legs["XBT"].status is LegStatus.FAILED
    assert legs["ETH"].status is LegStatus.SKIPPED
    assert "after the sells" in legs["ETH"].note
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell"]


def test_after_an_unknown_answer_to_a_sell_no_buy_is_sent(app_context, fake_kraken, ready):
    user = ready()
    fake_kraken.lose_add_order = "dropped"

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.STOPPED
    assert [leg.status for leg in result.legs] == [LegStatus.PENDING, LegStatus.SKIPPED]
    assert len(_sent(fake_kraken)) == 1


def test_a_decision_that_says_no_sends_nothing_and_is_recorded(app_context, db_session, fake_kraken, ready):
    user = ready()
    seen = []

    def hold(planned, log):
        seen.append(planned)
        log.append("held for approval")
        return EvaluationStatus.PROPOSED

    result = _rebalance(app_context, user, decide=hold)

    assert result.status is EvaluationStatus.PROPOSED
    assert fake_kraken.placed == []
    (planned,) = seen
    assert [(leg.asset, leg.side, leg.amount) for leg in planned.legs] == [
        ("XBT", Side.SELL, D("200")),
        ("ETH", Side.BUY, D("200")),
    ]
    assert planned.legs[0].volume == D("0.004")
    assert planned.free_cash == D("0")
    (evaluation,) = list_evaluations(db_session, user.id)
    assert evaluation.status == "PROPOSED"
    assert "held for approval" in evaluation.log_messages
    assert latest_snapshot(db_session, user.id) is not None


def test_a_users_floor_is_the_minimum_of_a_sell_too(app_context, db_session, fake_kraken, ready):
    user = ready()
    update_settings(db_session, user.id, min_order_fiat=D("250"))

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert {leg.status for leg in result.legs} == {LegStatus.SKIPPED}
    assert fake_kraken.placed == []


def test_investing_never_sells_however_far_a_weight_has_drifted(app_context, fake_kraken, ready):
    user = ready(balance={"ZEUR": "100", "XXBT": "0.014", "XETH": "0.12"})

    invest(app_context, user.id)

    assert {form["type"] for form in _sent(fake_kraken)} == {"buy"}
```

- [ ] **Step 3: Run them to verify they fail**

Run: the test command, with `tests/integration/test_rebalance_execution.py`
Expected: FAIL with `ImportError: cannot import name 'evaluate' from 'core.execution'`

- [ ] **Step 4: Rewrite the executor**

Replace the whole of `core/execution.py` with:

```python
"""Placing orders: the one place in this system that does (spec §9).

Two operations run through here. An investment buys with free cash and needs no
approval. A rebalance sells first and buys with what the sells raised, and is sent only
when the caller's decision says so; `core/rebalance.py` holds that decision.

An evaluation runs in short transactions of its own, never in a request's. The row of an
attempt is committed before its order is sent (§9.2), and no transaction is open while
Kraken is waited on (§9.6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
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
from engine.types import HUNDRED, ZERO, CashPolicy, Policy, Side
from exchange.orders import find_order_by_txid, new_cl_ord_id
from exchange.precision import minimum_fiat, round_cost, round_volume, volume_from_fiat
from exchange.types import Credentials, PairMeta, Placement, PlacementOutcome

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
    """The user has not configured what an operation needs. The message says what."""


class EvaluationStatus(StrEnum):
    DONE = "DONE"
    NOTHING_TO_DO = "NOTHING_TO_DO"
    STOPPED = "STOPPED"
    UNRESOLVED = "UNRESOLVED"
    KRAKEN_UNAVAILABLE = "KRAKEN_UNAVAILABLE"
    PREVIEW = "PREVIEW"
    ERROR = "ERROR"
    # A rebalance was computed and waits for approval. Nothing was sent.
    PROPOSED = "PROPOSED"
    # An approval met a plan that had changed. Nothing was sent.
    SUPERSEDED = "SUPERSEDED"


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
    side: Side
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
    # A sell's volume of the asset. A buy is placed in fiat and has none.
    volume: Decimal | None = None


@dataclass(frozen=True)
class EvaluationResult:
    status: EvaluationStatus
    preview: bool
    legs: tuple[LegResult, ...] = ()
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedLeg:
    asset: str
    pair: str
    side: Side
    # In fiat, rounded down to the pair's cost precision.
    amount: Decimal
    minimum: Decimal | None
    # Why it is not sent. `None` for a leg that is.
    note: str | None
    # A sell's volume of the asset, rounded down. A buy is placed in fiat and has none.
    volume: Decimal | None = None
    # The pair's metadata, to resize a buy against what the sells raised.
    meta: PairMeta | None = None


@dataclass(frozen=True)
class Planned:
    view: PortfolioView
    legs: tuple[PlannedLeg, ...]
    # Fiat above the cash target when the account was read: what buys may spend before
    # any sell has raised anything.
    free_cash: Decimal


# Once the plan is known, under the lock: `None` sends it, and a status ends the
# evaluation with nothing sent. It may write in transactions of its own, and log.
Decision = Callable[[Planned, list[str]], EvaluationStatus | None]


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


UNRESOLVED_MESSAGE = "an earlier order is still unresolved; nothing was computed"


def invest(context: ExecutionContext, user_id: uuid.UUID, *, preview: bool = False) -> EvaluationResult:
    """Invest the user's free cash now or, with `preview`, say what that would do.

    Raises `NotReady` before anything is read, `EvaluationBusy` when another evaluation
    of the user holds the lock, and `CredentialsUnreadable` when the stored key does not
    open. Every other outcome is a status in the result.
    """
    if preview:
        account = _load(context, user_id, allow_sells=False)
        private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
        return _preview(context, user_id, account, private)
    return evaluate(context, user_id, allow_sells=False, reason=OrderReason.INVEST, decide=_send_it)


def _send_it(planned: Planned, log: list[str]) -> None:
    """An investment needs no approval (spec §3.4)."""
    return None


def evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    *,
    allow_sells: bool,
    reason: OrderReason,
    decide: Decision,
) -> EvaluationResult:
    """Lock, resolve, read and plan; then let `decide` judge, and send what it lets through.

    Raises as `invest` does. Every other outcome is a status in the result, and recorded.
    """
    account = _load(context, user_id, allow_sells=allow_sells)
    private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
    with context.user_lock(user_id) as taken:
        if not taken:
            raise EvaluationBusy(str(user_id))
        return _run(context, user_id, account, private, reason, decide)


def _load(context: ExecutionContext, user_id: uuid.UUID, *, allow_sells: bool) -> _Account:
    with context.sessions() as session:
        settings = db.get_settings(session, user_id)
        if settings is None:
            raise NotReady("choose a fiat with PATCH /config first")
        record = db.get_credentials(session, user_id)
        if record is None:
            raise NotReady("register a Kraken key with POST /credentials first")
        policy = Policy(
            allow_sells=allow_sells,
            cash_policy=CashPolicy.REDUCE_DRIFT if settings.cash_rebalance_enabled else CashPolicy.PRORATA,
            min_drift_pct=settings.min_drift_pct,
            # Zero for the engine: the executor applies the user's floor beside Kraken's
            # minimum, so a leg dropped for either reason is logged with it.
            min_order_fiat=ZERO,
        )
        targets = tuple(
            _Target(row.asset, row.pair, row.target_pct) for row in db.list_assets(session, user_id)
        )
        sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
        return _Account(
            fiat=settings.fiat,
            policy=policy,
            floor=settings.min_order_fiat,
            targets=targets,
            sealed=sealed,
        )


def _plan(context: ExecutionContext, account: _Account, private) -> Planned:
    """Read the account, run the engine, and size each leg against Kraken's minimum.

    Raises `PortfolioUnavailable` when any read fails.
    """
    view = read_portfolio(context.public_kraken(), private, account.fiat, account.targets)
    metas = context.catalog.pairs()
    if metas is None:
        raise PortfolioUnavailable("asset pairs")
    managed = {holding.asset: holding for holding in view.holdings if holding.managed}
    pair_of = {target.asset: target.pair for target in account.targets}
    target_of = {target.asset: target.target_pct for target in account.targets}
    plan = reconcile(
        {asset: holding.amount for asset, holding in managed.items()},
        {asset: holding.price for asset, holding in managed.items()},
        target_of,
        view.cash,
        account.policy,
    )

    legs: list[PlannedLeg] = []
    for leg in plan.legs:
        pair = pair_of[leg.asset]
        meta = metas.get(pair)
        if meta is None or not meta.tradable:
            legs.append(
                PlannedLeg(leg.asset, pair, leg.side, leg.amount_fiat, None, f"kraken does not trade {pair} now")
            )
            continue
        holding = managed[leg.asset]
        amount = round_cost(meta, leg.amount_fiat)
        volume = None
        if leg.side is Side.SELL:
            held = round_volume(meta, holding.amount)
            # An exit sells everything: sized from a price, it would leave dust Kraken
            # will not take. Any other sell never asks for more than is held.
            if target_of[leg.asset] == ZERO:
                volume = held
            else:
                volume = min(volume_from_fiat(meta, leg.amount_fiat, holding.price), held)
        minimum = max(minimum_fiat(meta, holding.price), account.floor)
        note = None
        if amount < minimum:
            note = (
                f"{plain_amount(amount)} {account.fiat} is below the minimum "
                f"of {plain_amount(minimum)} {account.fiat}"
            )
        legs.append(PlannedLeg(leg.asset, pair, leg.side, amount, minimum, note, volume, meta))
    return Planned(view=view, legs=tuple(legs), free_cash=_free_cash(view))


def _free_cash(view: PortfolioView) -> Decimal:
    """Cash above the cash target. The engine's `investable_cash`, from the same valuation."""
    wanted = view.managed_value * view.cash_target_pct / HUNDRED
    excess = view.cash - wanted
    return excess if excess > ZERO else ZERO


def _run(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    reason: OrderReason,
    decide: Decision,
) -> EvaluationResult:
    with context.sessions() as session:
        evaluation_id = db.start_evaluation(session, user_id, context.now()).id
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


def _evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    reason: OrderReason,
    decide: Decision,
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

    verdict = decide(planned, log)
    if verdict is not None:
        return verdict

    stopped = _send_all(context, user_id, private, planned, reason, account.fiat, log, legs)
    if stopped:
        return EvaluationStatus.STOPPED
    if any(leg.status is not LegStatus.SKIPPED for leg in legs):
        return EvaluationStatus.DONE
    return EvaluationStatus.NOTHING_TO_DO


def _send_all(
    context: ExecutionContext,
    user_id: uuid.UUID,
    private,
    planned: Planned,
    reason: OrderReason,
    fiat: str,
    log: list[str],
    legs: list[LegResult],
) -> bool:
    """Sells first, then the buys inside what there is to spend (spec §7.2).

    True when an unknown answer stopped it. The budget is read from the ledger, not from
    the balance, which may not reflect the sells yet (§9.2).
    """
    budget = planned.free_cash
    stopped = False
    for leg in planned.legs:
        if leg.side is not Side.SELL:
            continue
        result, stopped = _attempt(context, user_id, private, leg, reason, stopped)
        legs.append(result)
        log.append(_describe(result, fiat))
        if result.status is LegStatus.FILLED:
            # `fciq`: Kraken reports a sell's proceeds and its fee in fiat.
            budget += (result.cost or ZERO) - (result.fee or ZERO)

    buys = [leg for leg in planned.legs if leg.side is Side.BUY]
    for leg in _within(buys, budget, fiat):
        result, stopped = _attempt(context, user_id, private, leg, reason, stopped)
        legs.append(result)
        log.append(_describe(result, fiat))
    return stopped


def _within(buys: list[PlannedLeg], budget: Decimal, fiat: str) -> list[PlannedLeg]:
    """The buys, shrunk in proportion when together they ask for more than `budget`.

    A rebalance's buys are sized from prices read before the sells, and a sell raises less
    than planned: Kraken keeps a fee, and the price moves. One factor for every buy keeps
    the plan's proportions. A buy that shrinks below its minimum is skipped.
    """
    asked = sum((leg.amount for leg in buys if leg.note is None), ZERO)
    if asked <= budget:
        return buys
    factor = budget / asked
    fitted: list[PlannedLeg] = []
    for leg in buys:
        if leg.note is not None:
            fitted.append(leg)
            continue
        amount = round_cost(leg.meta, leg.amount * factor)
        note = None
        if amount < leg.minimum:
            note = (
                f"after the sells, {plain_amount(amount)} {fiat} is below the minimum "
                f"of {plain_amount(leg.minimum)} {fiat}"
            )
        fitted.append(replace(leg, amount=amount, note=note))
    return fitted


def _attempt(
    context: ExecutionContext,
    user_id: uuid.UUID,
    private,
    leg: PlannedLeg,
    reason: OrderReason,
    stopped: bool,
) -> tuple[LegResult, bool]:
    """Send one leg unless it is skipped or an earlier answer was lost. Returns `stopped`."""
    if leg.note is not None:
        return _skipped(leg, leg.note), stopped
    if stopped:
        return _skipped(leg, "not sent: an earlier order's answer is unknown"), True
    result = _send(context, user_id, private, leg, reason)
    # An unknown answer leaves no txid. The balance is ambiguous until resolved.
    return result, result.status is LegStatus.PENDING and result.txid is None


def _place(private, leg: PlannedLeg, cl_ord_id: str, *, validate: bool = False) -> Placement:
    """A buy is an amount of fiat (`viqc`); a sell is a volume of the asset (spec §9.1)."""
    if leg.side is Side.BUY:
        return private.add_order(leg.pair, "buy", leg.amount, cl_ord_id, in_quote=True, validate=validate)
    return private.add_order(leg.pair, "sell", leg.volume, cl_ord_id, validate=validate)


def _send(
    context: ExecutionContext, user_id: uuid.UUID, private, leg: PlannedLeg, reason: OrderReason
) -> LegResult:
    cl_ord_id = new_cl_ord_id()
    with context.sessions() as session:
        db.record_attempt(
            session,
            user_id,
            cl_ord_id,
            pair=leg.pair,
            asset=leg.asset,
            side=leg.side,
            reason=reason,
            requested_fiat=leg.amount,
            attempted_at=context.now(),
        )
    # Committed. From here a lost answer leaves a row to resolve, not a gap (spec §9.2).
    placement = _place(private, leg, cl_ord_id)

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


def _from_row(leg: PlannedLeg, order: Order) -> LegResult:
    return LegResult(
        asset=leg.asset,
        pair=leg.pair,
        side=leg.side,
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
        volume=leg.volume,
    )


def _skipped(leg: PlannedLeg, note: str) -> LegResult:
    return LegResult(
        leg.asset, leg.pair, leg.side, leg.amount, leg.minimum, LegStatus.SKIPPED, note=note, volume=leg.volume
    )


def _describe(leg: LegResult, fiat: str) -> str:
    text = f"{leg.asset}: {leg.side.value} of {plain_amount(leg.amount_fiat)} {fiat} {leg.status.value}"
    if leg.error:
        text += f" ({leg.error})"
    if leg.note:
        text += f": {leg.note}"
    return text


def _preview(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> EvaluationResult:
    """Read, plan and have Kraken validate. Writes nothing, takes no lock, resolves nothing."""
    with context.sessions() as session:
        unresolved = db.has_unresolved(session, user_id)
    if unresolved:
        return EvaluationResult(EvaluationStatus.UNRESOLVED, preview=True, messages=(UNRESOLVED_MESSAGE,))
    try:
        planned = _plan(context, account, private)
    except PortfolioUnavailable as exc:
        return EvaluationResult(
            EvaluationStatus.KRAKEN_UNAVAILABLE, preview=True, messages=(f"kraken did not return {exc}",)
        )

    verdicts = {PlacementOutcome.VALIDATED: LegStatus.VALIDATED, PlacementOutcome.REFUSED: LegStatus.REJECTED}
    legs: list[LegResult] = []
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
            continue
        placement = _place(private, leg, new_cl_ord_id(), validate=True)
        status = verdicts.get(placement.outcome, LegStatus.UNCHECKED)
        legs.append(
            LegResult(leg.asset, leg.pair, leg.side, leg.amount, leg.minimum, status, error=placement.error)
        )
    return EvaluationResult(EvaluationStatus.PREVIEW, preview=True, legs=tuple(legs))
```

- [ ] **Step 5: Follow the rename in the invest route**

In `api/routes/invest.py`, replace:

```python
from core.execution import EvaluationBusy, EvaluationStatus, InvestResult, LegResult, NotReady, invest
```

with:

```python
from core.execution import EvaluationBusy, EvaluationResult, EvaluationStatus, LegResult, NotReady, invest
```

and `def _out(result: InvestResult) -> InvestOut:` with
`def _out(result: EvaluationResult) -> InvestOut:`. Task 5 rewrites this route; this keeps
it importable meanwhile.

- [ ] **Step 6: Run the whole suite**

Run: the test command
Expected: all PASS — the new file and every phase 5 test. The log line of a buy reads as
before (`XBT: buy of 600 EUR FILLED`).

- [ ] **Step 7: Commit**

```bash
git add core/execution.py api/routes/invest.py tests/integration/conftest.py tests/integration/test_rebalance_execution.py
git commit -m "feat(core): the executor sells, and fits the buys inside what the sells raised"
```

---

### Task 4: The proposal lifecycle

**Files:**
- Create: `core/rebalance.py`
- Modify: `core/db/models.py` (the `Proposal` docstring only)
- Create: `tests/integration/test_rebalance.py`

**Interfaces:**
- Consumes: `evaluate`, `Planned`, `EvaluationResult`, `EvaluationStatus`, `ExecutionContext`
  (Task 3); `plan_document`, `has_orders`, `is_material` (Task 2); `db.get_proposal`,
  `db.get_live_proposal`, `db.save_proposal`, `db.set_status`, `db.withdraw` (phase 2).
- Produces, for Task 5:
  - `ProposalState(version: int, status: str, trigger: str, plan: dict, updated_at: datetime)`.
  - `RebalanceResult(evaluation: EvaluationResult, proposal: ProposalState | None)`.
  - `propose(context, user_id) -> RebalanceResult`.
  - `approve(context, user_id, version: int) -> RebalanceResult`. Raises `NoProposal`,
    `StaleVersion` (with `.current: ProposalState`) before anything is read from Kraken,
    and whatever `evaluate` raises.
  - `current(context, user_id) -> ProposalState | None`: the live proposal.
  - `withdraw(context, user_id) -> bool`: false when there was no live proposal.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_rebalance.py`:

```python
import base64
from decimal import Decimal

import pytest

from core.db.orders import list_orders, record_attempt
from core.db.proposals import get_proposal
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import list_evaluations
from core.db.types import OrderReason, ProposalStatus
from core.db.users import save_credentials
from core.execution import EvaluationStatus
from core.rebalance import NoProposal, StaleVersion, approve, current, propose, withdraw
from engine.types import Side
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
# 700 EUR of XBT and 300 EUR of ETH against 50/50: sell 200 of XBT, buy 200 of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}
ON_TARGET = {"ZEUR": "0", "XXBT": "0.01", "XETH": "0.2"}


@pytest.fixture
def user(app_context, db_session, make_user, fake_kraken):
    person = make_user()
    create_settings(db_session, person.id, fiat="EUR")
    upsert_asset(db_session, person.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
    upsert_asset(db_session, person.id, asset="ETH", pair="XETHZEUR", target_pct=D("50"))
    sealed = app_context.cipher.seal(person.id, Credentials("TEST-KEY", SECRET))
    save_credentials(
        db_session, person.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
    )
    fake_kraken.balance = dict(DRIFTED)
    return person


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def _legs(state):
    return [(leg["asset"], leg["side"], leg["amount_fiat"]) for leg in state.plan["legs"]]


def test_a_rebalance_is_proposed_and_nothing_is_sent(app_context, db_session, fake_kraken, user):
    result = propose(app_context, user.id)

    assert result.evaluation.status is EvaluationStatus.PROPOSED
    assert (result.proposal.version, result.proposal.status, result.proposal.trigger) == (1, "LIVE", "MANUAL")
    assert _legs(result.proposal) == [("XBT", "sell", "200"), ("ETH", "buy", "200")]
    assert fake_kraken.placed == []
    assert list_orders(db_session, user.id) == []
    assert [e.status for e in list_evaluations(db_session, user.id)] == ["PROPOSED"]


def test_proposing_with_automatic_rebalancing_on_still_sends_nothing(app_context, db_session, fake_kraken, user):
    update_settings(db_session, user.id, auto_rebalance_enabled=True)

    propose(app_context, user.id)

    assert fake_kraken.placed == []


def test_proposing_again_on_the_same_plan_keeps_the_version(app_context, user):
    propose(app_context, user.id)

    again = propose(app_context, user.id)

    assert again.proposal.version == 1


def test_a_move_within_the_minimum_keeps_the_version_and_the_plan_the_user_read(
    app_context, db_session, fake_kraken, user
):
    """A floor of 10. XBT at 50 100 moves each leg by 0.70: not material."""
    update_settings(db_session, user.id, min_order_fiat=D("10"))
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "50100"

    again = propose(app_context, user.id)

    assert again.proposal.version == 1
    assert _legs(again.proposal) == [("XBT", "sell", "200"), ("ETH", "buy", "200")]


def test_a_material_move_is_a_new_version(app_context, fake_kraken, user):
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    again = propose(app_context, user.id)

    assert again.proposal.version == 2
    assert _legs(again.proposal) == [("XBT", "sell", "207"), ("ETH", "buy", "207")]


def test_a_proposal_is_withdrawn_when_the_drift_is_gone(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)
    fake_kraken.balance = dict(ON_TARGET)

    result = propose(app_context, user.id)

    assert result.evaluation.status is EvaluationStatus.NOTHING_TO_DO
    assert result.proposal is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN


def test_a_proposal_after_a_withdrawn_one_takes_the_next_version(app_context, user):
    propose(app_context, user.id)
    withdraw(app_context, user.id)

    again = propose(app_context, user.id)

    assert again.proposal.version == 2


def test_withdrawing_says_whether_there_was_a_live_proposal(app_context, user):
    assert withdraw(app_context, user.id) is False
    propose(app_context, user.id)

    assert withdraw(app_context, user.id) is True
    assert current(app_context, user.id) is None
    assert withdraw(app_context, user.id) is False


def test_approving_the_live_version_executes_it(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.DONE
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    orders = list_orders(db_session, user.id)
    assert {order.reason for order in orders} == {OrderReason.REBALANCE}
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTED
    assert result.proposal is None


def test_a_proposal_after_an_executed_one_takes_the_next_version(app_context, fake_kraken, user):
    propose(app_context, user.id)
    approve(app_context, user.id, 1)

    again = propose(app_context, user.id)

    assert again.proposal.version == 2


def test_an_approval_of_another_version_is_refused_before_kraken_is_read(
    app_context, db_session, fake_kraken, user
):
    propose(app_context, user.id)
    fake_kraken.calls.clear()

    with pytest.raises(StaleVersion) as refused:
        approve(app_context, user.id, 2)

    assert refused.value.current.version == 1
    assert fake_kraken.calls == []
    assert len(list_evaluations(db_session, user.id)) == 1


def test_there_is_nothing_to_approve_without_a_live_proposal(app_context, fake_kraken, user):
    with pytest.raises(NoProposal):
        approve(app_context, user.id, 1)

    assert fake_kraken.calls == []


def test_an_approval_that_meets_a_material_change_sends_nothing_and_offers_the_new_version(
    app_context, db_session, fake_kraken, user
):
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.SUPERSEDED
    assert result.proposal.version == 2
    assert _sent(fake_kraken) == []
    assert list_orders(db_session, user.id) == []


def test_an_approval_within_the_minimum_executes_todays_amounts(app_context, db_session, fake_kraken, user):
    """Approved at 200; at 50 100 the sell is 200.70, and that is what is sent."""
    update_settings(db_session, user.id, min_order_fiat=D("10"))
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "50100"

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.DONE
    sell = next(order for order in list_orders(db_session, user.id) if order.side == Side.SELL)
    assert sell.requested_fiat == D("200.7")


def test_an_approval_that_finds_the_drift_gone_withdraws_the_proposal(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)
    fake_kraken.balance = dict(ON_TARGET)

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.SUPERSEDED
    assert result.proposal is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert _sent(fake_kraken) == []


def test_an_approval_waits_for_an_unresolved_order(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)
    record_attempt(
        db_session,
        user.id,
        "unresolved-1",
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("10"),
        attempted_at=app_context.now(),
    )

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.UNRESOLVED
    assert result.proposal.version == 1
    assert result.proposal.status == "LIVE"
    assert _sent(fake_kraken) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: the test command, with `tests/integration/test_rebalance.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.rebalance'`

- [ ] **Step 3: Implement**

Create `core/rebalance.py`:

```python
"""The rebalance operation and its proposal (spec §3.4, §8).

A rebalance sells, and a sell cannot be undone. So a request to rebalance never sends
anything: `propose` computes the plan and keeps it as the user's one live proposal, and
`approve` executes it once the user has read it. The executor sends; this module decides
whether there is anything to send.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

import core.database as db
from core.db.models import Proposal
from core.db.types import OrderReason, ProposalStatus, ProposalTrigger
from core.execution import EvaluationResult, EvaluationStatus, ExecutionContext, Planned, evaluate
from core.proposal_plan import has_orders, is_material, plan_document


@dataclass(frozen=True)
class ProposalState:
    version: int
    status: str
    trigger: str
    plan: dict[str, object]
    updated_at: datetime


@dataclass(frozen=True)
class RebalanceResult:
    evaluation: EvaluationResult
    # The live proposal as the evaluation left it. `None` when there is none.
    proposal: ProposalState | None


class NoProposal(Exception):
    """There is no live proposal to approve. Nothing was read."""


class StaleVersion(Exception):
    """The approval named a version that is not the live one. Nothing was read."""

    def __init__(self, current: ProposalState) -> None:
        super().__init__(f"the live proposal is version {current.version}")
        self.current = current


def current(context: ExecutionContext, user_id: uuid.UUID) -> ProposalState | None:
    with context.sessions() as session:
        return _state(db.get_live_proposal(session, user_id))


def withdraw(context: ExecutionContext, user_id: uuid.UUID) -> bool:
    """False when there was no live proposal. An executed one is not withdrawn."""
    with context.sessions() as session:
        if db.get_live_proposal(session, user_id) is None:
            return False
        return db.withdraw(session, user_id)


def propose(context: ExecutionContext, user_id: uuid.UUID) -> RebalanceResult:
    """Compute a rebalance and keep it as the live proposal. Never sends an order.

    Not even with automatic rebalancing on: a rebalance executed without an approval is
    the scheduler's, in phase 7. Raises what `evaluate` raises.
    """

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus:
        document = plan_document(planned.view.fiat, planned.legs)
        with context.sessions() as session:
            _keep(session, user_id, document, ProposalTrigger.MANUAL, log)
        return EvaluationStatus.PROPOSED if has_orders(document) else EvaluationStatus.NOTHING_TO_DO

    result = evaluate(context, user_id, allow_sells=True, reason=OrderReason.REBALANCE, decide=decide)
    return RebalanceResult(result, current(context, user_id))


def approve(context: ExecutionContext, user_id: uuid.UUID, version: int) -> RebalanceResult:
    """Execute the live proposal, if `version` is still it and its plan has not moved.

    The version is checked first, before anything is read from Kraken. Under the lock the
    plan is computed again: a material change is stored as the next version, and the
    evaluation ends `SUPERSEDED` with nothing sent. Otherwise the fresh plan executes,
    with today's amounts (spec §8).
    """
    with context.sessions() as session:
        slot = db.get_live_proposal(session, user_id)
        if slot is None:
            raise NoProposal(str(user_id))
        if slot.version != version:
            raise StaleVersion(_state(slot))

    executing = False

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus | None:
        nonlocal executing
        document = plan_document(planned.view.fiat, planned.legs)
        with context.sessions() as session:
            slot = db.get_live_proposal(session, user_id)
            if slot is None or slot.version != version:
                log.append("the proposal changed before it could execute; nothing was sent")
                return EvaluationStatus.SUPERSEDED
            if not has_orders(document) or is_material(slot.plan, document):
                _keep(session, user_id, document, ProposalTrigger(slot.trigger), log)
                log.append("the plan changed since it was proposed; nothing was sent")
                return EvaluationStatus.SUPERSEDED
            # What executes is today's plan, recorded under the version approved.
            db.save_proposal(session, user_id, plan=document, trigger=ProposalTrigger(slot.trigger), version=version)
            db.set_status(session, user_id, ProposalStatus.EXECUTING)
        executing = True
        log.append(f"proposal version {version} approved; executing")
        return None

    result = evaluate(context, user_id, allow_sells=True, reason=OrderReason.REBALANCE, decide=decide)
    if executing:
        with context.sessions() as session:
            db.set_status(session, user_id, ProposalStatus.EXECUTED)
    return RebalanceResult(result, current(context, user_id))


def _keep(
    session: Session, user_id: uuid.UUID, document: Mapping, trigger: ProposalTrigger, log: list[str]
) -> None:
    """Keep `document` as the live proposal, or withdraw the proposal when it is empty.

    The version moves only on a material change (spec §8), and an unchanged plan is not
    rewritten: the stored plan stays the one the user read. The version never goes back:
    a proposal after a withdrawn or executed one takes the next number, so an approval
    meant for the old one cannot reach it.
    """
    slot = db.get_proposal(session, user_id)
    live = slot is not None and slot.status == ProposalStatus.LIVE
    if not has_orders(document):
        if live:
            db.withdraw(session, user_id)
            log.append("the drift is below the threshold; the proposal was withdrawn")
        else:
            log.append("the drift is below the threshold; nothing to propose")
        return
    if live and not is_material(slot.plan, document):
        log.append(f"proposal version {slot.version} still stands")
        return
    version = 1 if slot is None else slot.version + 1
    db.save_proposal(session, user_id, plan=dict(document), trigger=trigger, version=version)
    log.append(f"proposal version {version}")


def _state(row: Proposal | None) -> ProposalState | None:
    if row is None:
        return None
    return ProposalState(
        version=row.version,
        status=row.status,
        trigger=row.trigger,
        plan=row.plan,
        updated_at=row.updated_at,
    )
```

- [ ] **Step 4: Update the `Proposal` docstring**

In `core/db/models.py`, replace:

```python
    """At most one per user.

    A later phase owns the transitions between the statuses. This one owns the row and
    the rule that there is only ever one.
    """
```

with:

```python
    """At most one per user. `core/rebalance.py` owns the transitions between the statuses."""
```

- [ ] **Step 5: Run them to verify they pass**

Run: the test command, with `tests/integration/test_rebalance.py`
Expected: 16 PASS

- [ ] **Step 6: Commit**

```bash
git add core/rebalance.py core/db/models.py tests/integration/test_rebalance.py
git commit -m "feat(core): propose a rebalance, and execute it only on approval of the version read"
```

---

### Task 5: The endpoints

**Files:**
- Create: `api/evaluation.py`
- Create: `api/routes/proposal.py`
- Modify: `api/routes/invest.py` (rewritten whole)
- Modify: `api/schemas.py`
- Modify: `api/app.py`
- Create: `tests/integration/test_api_rebalance.py`
- Modify: `tests/integration/test_api_invest.py`, `tests/integration/test_api_tenant_isolation.py`

**Interfaces:**
- Consumes: `propose`, `approve`, `current`, `withdraw`, `NoProposal`, `StaleVersion`,
  `ProposalState`, `RebalanceResult` (Task 4); `EvaluationResult`, `LegResult` (Task 3).
- Produces: `POST /rebalance`, `GET /proposal`, `POST /proposal/approve`, `DELETE /proposal`.

| Endpoint | Answer |
|---|---|
| `POST /rebalance` | `200` `RebalanceOut`, `proposal` null when the drift is below the threshold |
| `GET /proposal` | `200` `ProposalOut`, `404` when none is live |
| `POST /proposal/approve` `{"version": n}` | `200` `RebalanceOut` once executed; `404` none live; `409` `{"detail", "proposal"}` for another version or a changed plan (`proposal` null when the drift is gone); `422` with no version |
| `DELETE /proposal` | `204`, `404` when none is live |

Both evaluation endpoints answer as `POST /invest` does when the evaluation cannot run:
`409` busy, not configured, or unresolved; `503` Kraken unreadable; `500` a key that does
not open.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_api_rebalance.py`:

```python
import base64
import uuid

import pytest

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}


@pytest.fixture
def headers(api, make_user, login, fake_kraken):
    signed_in = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=signed_in)
    api.put("/assets/XBT", json={"target_pct": "50"}, headers=signed_in)
    api.put("/assets/ETH", json={"target_pct": "50"}, headers=signed_in)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=signed_in)
    fake_kraken.balance = dict(DRIFTED)
    return signed_in


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_rebalancing_needs_a_signed_in_user(api):
    assert api.post("/rebalance").status_code == 401
    assert api.get("/proposal").status_code == 401
    assert api.post("/proposal/approve", json={"version": 1}).status_code == 401
    assert api.delete("/proposal").status_code == 401


def test_rebalancing_needs_settings_first(api, make_user, login):
    response = api.post("/rebalance", headers=login(make_user()))

    assert response.status_code == 409
    assert "fiat" in response.json()["detail"]


def test_a_rebalance_answers_with_its_proposal_and_sends_nothing(api, headers, fake_kraken):
    response = api.post("/rebalance", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROPOSED"
    assert body["legs"] == []
    proposal = body["proposal"]
    assert (proposal["version"], proposal["status"], proposal["fiat"]) == (1, "LIVE", "EUR")
    assert [(leg["asset"], leg["side"], leg["amount_fiat"], leg["minimum_fiat"]) for leg in proposal["legs"]] == [
        ("XBT", "sell", "200", "5"),
        ("ETH", "buy", "200", "0.5"),
    ]
    assert fake_kraken.placed == []


def test_the_live_proposal_can_be_read(api, headers):
    assert api.get("/proposal", headers=headers).status_code == 404
    api.post("/rebalance", headers=headers)

    response = api.get("/proposal", headers=headers)

    assert response.status_code == 200
    assert response.json()["version"] == 1


def test_approving_the_version_read_executes_the_rebalance(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DONE"
    assert body["proposal"] is None
    assert [(leg["asset"], leg["side"], leg["status"]) for leg in body["legs"]] == [
        ("XBT", "sell", "FILLED"),
        ("ETH", "buy", "FILLED"),
    ]
    assert body["legs"][0]["volume"] == "0.004"
    assert {order["reason"] for order in api.get("/orders", headers=headers).json()} == {"REBALANCE"}
    assert api.get("/proposal", headers=headers).status_code == 404


def test_approving_another_version_is_a_409_with_the_live_proposal(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)

    response = api.post("/proposal/approve", json={"version": 7}, headers=headers)

    assert response.status_code == 409
    assert response.json()["proposal"]["version"] == 1
    assert fake_kraken.placed == []


def test_an_approval_that_meets_a_changed_plan_is_a_409_with_the_new_version(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 409
    assert response.json()["proposal"]["version"] == 2
    assert _sent(fake_kraken) == []
    # Both evaluations start at the test's fixed clock, so their order is not defined.
    assert {e["status"] for e in api.get("/sessions", headers=headers).json()} == {"PROPOSED", "SUPERSEDED"}


def test_there_is_nothing_to_approve_without_a_proposal(api, headers):
    assert api.post("/proposal/approve", json={"version": 1}, headers=headers).status_code == 404


def test_an_approval_names_its_version(api, headers):
    assert api.post("/proposal/approve", json={}, headers=headers).status_code == 422
    assert api.post("/proposal/approve", json={"version": 0}, headers=headers).status_code == 422


def test_a_proposal_can_be_withdrawn(api, headers):
    api.post("/rebalance", headers=headers)

    assert api.delete("/proposal", headers=headers).status_code == 204
    assert api.get("/proposal", headers=headers).status_code == 404
    assert api.delete("/proposal", headers=headers).status_code == 404


def test_a_rebalance_already_running_is_a_409(api, headers, user_locks):
    user_locks.held.add(uuid.UUID(api.get("/auth/me", headers=headers).json()["id"]))

    response = api.post("/rebalance", headers=headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_kraken_down_is_a_503_and_the_proposal_is_untouched(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)
    fake_kraken.down.add("Balance")

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 503
    assert api.get("/proposal", headers=headers).json()["version"] == 1
```

In `tests/integration/test_api_invest.py`, in
`test_free_cash_is_invested_and_every_amount_is_a_plain_string`, after
`assert legs["XBT"]["status"] == "FILLED"`, add:

```python
    assert legs["XBT"]["side"] == "buy"
    assert legs["XBT"]["volume"] is None
```

Append to `tests/integration/test_api_tenant_isolation.py`:

```python
def test_a_proposal_is_not_shared(api, login, bob, alice_ready, fake_kraken):
    fake_kraken.balance = {"ZEUR": "100", "XXBT": "0.01"}
    assert api.post("/rebalance", headers=alice_ready).status_code == 200

    assert api.get("/proposal", headers=login(bob)).status_code == 404
    assert api.post("/proposal/approve", json={"version": 1}, headers=login(bob)).status_code == 404
    assert api.delete("/proposal", headers=login(bob)).status_code == 404
    assert api.get("/proposal", headers=alice_ready).json()["version"] == 1
```

`alice_ready` holds XBT at 60 % with 100 EUR. With 0.01 XBT (500 EUR) and 100 EUR of cash
the plan sells XBT down to 60 % of 600, so a proposal exists.

- [ ] **Step 2: Run them to verify they fail**

Run: the test command, with `tests/integration/test_api_rebalance.py tests/integration/test_api_invest.py tests/integration/test_api_tenant_isolation.py`
Expected: FAIL — `/rebalance` answers `404`, and `side` is missing from an invest leg.

- [ ] **Step 3: Add the schemas**

In `api/schemas.py`, replace the whole `LegOut` class with:

```python
class LegOut(BaseModel):
    """One leg of an operation. Every amount is a plain decimal string."""

    asset: str
    pair: str
    side: str
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
    # A sell's volume of the asset. A buy is placed in fiat and has none.
    volume: str | None
```

Append to `api/schemas.py`:

```python
class ProposalLegOut(BaseModel):
    """One leg as it was proposed, the skipped ones too, with why."""

    asset: str
    pair: str
    side: str
    amount_fiat: str
    minimum_fiat: str | None
    note: str | None


class ProposalOut(BaseModel):
    version: int
    status: str
    trigger: str
    fiat: str
    legs: list[ProposalLegOut]
    updated_at: datetime


class ApproveIn(BaseModel):
    """The version read. An approval of any other is refused (spec §8)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class RebalanceOut(BaseModel):
    status: str
    # What was sent. Empty for a proposal, which sends nothing.
    legs: list[LegOut]
    # The live proposal as the evaluation left it. `null` when there is none.
    proposal: ProposalOut | None
    messages: list[str]
```

- [ ] **Step 4: Write what the evaluation routes share**

Create `api/evaluation.py`:

```python
"""What `POST /invest`, `POST /rebalance` and `POST /proposal/approve` share: the shape
of a leg, and the answers when an evaluation cannot run."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from api.schemas import LegOut
from core.crypto import CredentialsUnreadable
from core.execution import EvaluationBusy, EvaluationResult, EvaluationStatus, LegResult, NotReady
from core.portfolio import plain_amount

logger = logging.getLogger("coinpilot.api")


def plain(value: Decimal | None) -> str | None:
    return None if value is None else plain_amount(value)


def leg_out(leg: LegResult) -> LegOut:
    return LegOut(
        asset=leg.asset,
        pair=leg.pair,
        side=leg.side.value,
        amount_fiat=plain_amount(leg.amount_fiat),
        minimum_fiat=plain(leg.minimum_fiat),
        status=leg.status.value,
        cl_ord_id=leg.cl_ord_id,
        txid=leg.txid,
        cost=plain(leg.cost),
        executed_volume=plain(leg.executed_volume),
        executed_price=plain(leg.executed_price),
        fee=plain(leg.fee),
        error=leg.error,
        note=leg.note,
        volume=plain(leg.volume),
    )


@contextmanager
def evaluation_errors(user_id: uuid.UUID) -> Iterator[None]:
    """The evaluations that never started: busy, not configured, or a key that does not open."""
    try:
        yield
    except EvaluationBusy:
        raise HTTPException(409, "an evaluation of this account is already running; try again shortly") from None
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from None
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user_id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None


def refusal(status_code: int, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, **extra})


def unfinished(result: EvaluationResult) -> JSONResponse | None:
    """The answer for an evaluation that ran, was recorded, and could not compute.

    Returned, not raised: raising would roll back the request's transaction, which must
    never be what decides whether an evaluation's record survives.
    """
    if result.status is EvaluationStatus.UNRESOLVED:
        return refusal(409, "an earlier order is still unresolved; try again in a few minutes")
    if result.status is EvaluationStatus.KRAKEN_UNAVAILABLE:
        return refusal(503, "kraken could not be read; nothing was sent")
    return None
```

- [ ] **Step 5: Rewrite the invest route over it**

Replace the whole of `api/routes/invest.py` with:

```python
"""Invest free cash now (spec §11). A preview has Kraken validate and records nothing."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import Ctx, CurrentUser
from api.evaluation import evaluation_errors, leg_out, unfinished
from api.schemas import InvestOut
from core.execution import invest

router = APIRouter(prefix="/invest", tags=["invest"])


@router.post("", response_model=InvestOut)
def invest_now(user: CurrentUser, context: Ctx, preview: bool = False) -> InvestOut | JSONResponse:
    with evaluation_errors(user.id):
        result = invest(context, user.id, preview=preview)
    refused = unfinished(result)
    if refused is not None:
        return refused
    return InvestOut(
        status=result.status.value,
        preview=result.preview,
        legs=[leg_out(leg) for leg in result.legs],
        messages=list(result.messages),
    )
```

- [ ] **Step 6: Write the proposal routes**

Create `api/routes/proposal.py`:

```python
"""The rebalance and its proposal (spec §8, §11).

`POST /rebalance` only proposes. What is sold is sold on `POST /proposal/approve`, with
the version the user read.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from api.deps import Ctx, CurrentUser
from api.evaluation import evaluation_errors, leg_out, refusal, unfinished
from api.schemas import ApproveIn, ProposalLegOut, ProposalOut, RebalanceOut
from core.execution import EvaluationStatus
from core.rebalance import NoProposal, ProposalState, RebalanceResult, StaleVersion, approve, current, propose, withdraw

router = APIRouter(tags=["proposal"])

NO_PROPOSAL = "there is no live proposal"


def _proposal(state: ProposalState | None) -> ProposalOut | None:
    if state is None:
        return None
    return ProposalOut(
        version=state.version,
        status=state.status,
        trigger=state.trigger,
        fiat=state.plan["fiat"],
        legs=[ProposalLegOut(**leg) for leg in state.plan["legs"]],
        updated_at=state.updated_at,
    )


def _proposal_json(state: ProposalState | None) -> dict | None:
    out = _proposal(state)
    return None if out is None else out.model_dump(mode="json")


def _out(result: RebalanceResult) -> RebalanceOut:
    return RebalanceOut(
        status=result.evaluation.status.value,
        legs=[leg_out(leg) for leg in result.evaluation.legs],
        proposal=_proposal(result.proposal),
        messages=list(result.evaluation.messages),
    )


@router.post("/rebalance", response_model=RebalanceOut)
def rebalance(user: CurrentUser, context: Ctx) -> RebalanceOut | JSONResponse:
    with evaluation_errors(user.id):
        result = propose(context, user.id)
    refused = unfinished(result.evaluation)
    if refused is not None:
        return refused
    return _out(result)


@router.get("/proposal", response_model=ProposalOut)
def read_proposal(user: CurrentUser, context: Ctx) -> ProposalOut:
    state = current(context, user.id)
    if state is None:
        raise HTTPException(404, NO_PROPOSAL)
    return _proposal(state)


@router.post("/proposal/approve", response_model=RebalanceOut)
def approve_proposal(body: ApproveIn, user: CurrentUser, context: Ctx) -> RebalanceOut | JSONResponse:
    try:
        with evaluation_errors(user.id):
            result = approve(context, user.id, body.version)
    except NoProposal:
        raise HTTPException(404, NO_PROPOSAL) from None
    except StaleVersion as exc:
        return refusal(
            409, "that is not the live version; read the proposal again", proposal=_proposal_json(exc.current)
        )

    refused = unfinished(result.evaluation)
    if refused is not None:
        return refused
    if result.evaluation.status is EvaluationStatus.SUPERSEDED:
        return refusal(
            409,
            "the plan changed since it was proposed; nothing was sent",
            proposal=_proposal_json(result.proposal),
        )
    return _out(result)


@router.delete("/proposal", status_code=204)
def withdraw_proposal(user: CurrentUser, context: Ctx) -> Response:
    if not withdraw(context, user.id):
        raise HTTPException(404, NO_PROPOSAL)
    return Response(status_code=204)
```

- [ ] **Step 7: Include the router**

In `api/app.py`, replace:

```python
from api.routes import assets, auth, config, credentials, health, history, invest, portfolio
```

with:

```python
from api.routes import assets, auth, config, credentials, health, history, invest, portfolio, proposal
```

and add `proposal.router,` after `invest.router,` in the tuple of `create_app`.

- [ ] **Step 8: Run the API tests**

Run: the test command, with `tests/integration/test_api_rebalance.py tests/integration/test_api_invest.py tests/integration/test_api_tenant_isolation.py`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add api/ tests/integration/test_api_rebalance.py tests/integration/test_api_invest.py tests/integration/test_api_tenant_isolation.py
git commit -m "feat(api): POST /rebalance proposes, and POST /proposal/approve executes the version read"
```

---

### Task 6: The spec, the README, and the phase gate

**Files:**
- Modify: `docs/specs/2026-09-17-platform-design.md` (§8, §9.1, §14)
- Modify: `README.md`

- [ ] **Step 1: Spec §8**

Replace:

```markdown
**The version increments only on a material change**: a leg appears or disappears, or a
leg's amount moves by more than `min_order_fiat`. That threshold is reused deliberately —
a separate tolerance parameter would be one more thing to configure and to explain.

Approval carries the version. If it matches, the current plan executes. If it does not,
the request is refused and the new plan is returned; nothing executes.
```

with:

```markdown
**The version increments only on a material change**: a leg appears or disappears, or a
leg's amount moves by more than its effective minimum, the larger of `min_order_fiat`
and Kraken's minimum for the pair (§7.3). That threshold is reused deliberately — a
separate tolerance parameter would be one more thing to configure and to explain — and
Kraken's minimum is part of it because `min_order_fiat` defaults to 0, which would make
every price move a new version. An unchanged plan is not rewritten: the stored plan stays
the one the user read. The version never goes back; a proposal after a withdrawn or
executed one takes the next number.

Approval carries the version. If it does not match, the request is refused with the live
proposal and nothing is read. If it matches, the plan is computed again under the user's
lock: if it has not moved materially, it executes with today's amounts; if it has, it
becomes the next version, the request is refused with it, and nothing executes.
```

- [ ] **Step 2: Spec §9.1**

After the paragraph that ends `which is what the user holds.`, insert:

```markdown
A sell pays its fee in fiat (`fciq`), so the volume sent is the volume sold. A sell is
sized as its amount over the price, rounded down and never above the balance; an exit, a
target of 0 %, sells the whole balance, which a size computed from a price would leave
as dust Kraken will not take.

The buys of a rebalance spend the free cash above the cash target plus what the sells
raised, `cost − fee` of each filled sell as the ledger reports it. A sell raises less than
planned — the fee, and the price move — so when the buys ask for more, every one shrinks
by the same factor, and one that falls below its minimum is skipped and logged. The
balance is not read between the sells and the buys: it may not reflect them yet (§9.2).
```

- [ ] **Step 3: Spec §14**

After the bullet that begins `- **The proposal version tracks material change only`,
insert:

```markdown
- **An approval executes today's plan, not the stored one.** Hours can pass between
  reading a proposal and approving it. Executing the stored amounts would sell on stale
  prices; recomputing and comparing executes what is true now, and only when it is what
  the user agreed to.
```

- [ ] **Step 4: README**

In `README.md`, replace:

```markdown
> **Status: in development.** Phase 5 of 8: free cash is invested on request with
> `POST /invest`, after an optional preview Kraken validates. Nothing runs on its own yet.
```

with:

```markdown
> **Status: in development.** Phase 6 of 8: free cash is invested on request with
> `POST /invest`, and a rebalance is proposed with `POST /rebalance` and executed once
> approved with `POST /proposal/approve`. Nothing runs on its own yet.
```

- [ ] **Step 5: Run the whole gate**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests --cov-fail-under=80
```

Expected: each passes.

- [ ] **Step 6: Commit**

```bash
git add docs/specs/2026-09-17-platform-design.md README.md
git commit -m "docs: the spec settles material change, sells and the buy budget; the README describes phase 6"
```

---

## What you verify before phase 7

Phase 6 is the first phase that sells. Do it with a small position.

### 1. Start from a known state

1. Restart the API, so it runs this phase's code. There is no migration in this phase.
2. Hold two configured assets, each worth a few times its Kraken minimum. `GET /assets`
   shows each minimum.
3. Make a small, deliberate drift: change the weights with `PUT /assets/{asset}` so that
   one asset is overweight by 10 to 20 EUR.

### 2. Propose

```bash
curl -s -X POST localhost:8000/rebalance -H "Authorization: Bearer $TOKEN"
```

- `status` is `PROPOSED`, `legs` is empty, and `proposal.legs` holds one sell and one buy
  of about the amount you expect.
- Kraken's own order history is unchanged: nothing was sent.
- Run it again: the `version` stays 1.

### 3. Approve

```bash
curl -s -X POST localhost:8000/proposal/approve -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"version": 2}'
```

That is the wrong version on purpose: `409`, with the live proposal, and nothing sent.
Then approve version 1:

```bash
curl -s -X POST localhost:8000/proposal/approve -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"version": 1}'
```

- `status` is `DONE`. The sell is `FILLED` first, then the buy.
- `GET /proposal` is `404`: the proposal is executed.
- In Kraken's trade history, one market sell and one market buy.

### 4. Settle the open fact

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "select asset, side, status, requested_fiat, cost, executed_volume, executed_price, fee from orders where reason = 'REBALANCE' order by attempted_at"
```

Compare the sell's row with Kraken's ledger for that trade:

- **`cost`**: the gross proceeds in fiat, `executed_volume × executed_price`?
- **`fee`**: in fiat, and the ledger's fiat entry for the sell equal to `cost − fee`?
- **The buy's `requested_fiat`**: about the sell's `cost − fee` plus any free cash, never
  more.

Report the three answers. They go into the plan's departures and into spec §9.1.

### 5. Nothing more to do

`POST /rebalance` again. The drift is gone or below the minimum: `status` is
`NOTHING_TO_DO`, and `proposal` is `null`.

---

## Departures taken during execution

The code blocks above are the plan as written. Where the repository differs, trust the
repository.

| Where | What changed | Why |
|---|---|---|
