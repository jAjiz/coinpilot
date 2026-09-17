# Phase 1 — Foundations and the Reconciliation Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the project's tooling and build the pure reconciliation engine — the
function that turns holdings, prices and target weights into a plan of buys and sells.

**Architecture:** The engine is a leaf package. It imports nothing from the rest of the
system, reads no configuration, performs no I/O, and holds no state. Every input arrives
as an argument and every output is a frozen value object. That is what lets it be tested
exhaustively with no mocks, and what will later let the same code serve the scheduler, a
manual endpoint and any future caller unchanged.

**Tech Stack:** Python 3.12, pytest, pytest-cov, ruff. No database, no HTTP, no
framework in this phase.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.1, §3.2, §3.3, §7.1, §7.3

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 1 of 8

## Global Constraints

- **Python 3.12.** `requires-python = ">=3.12"`.
- **Money is `Decimal`, never `float`.** Every amount, price, weight and percentage in the
  engine is `decimal.Decimal`. A `float` in a monetary path is a defect.
- **Pin every dependency with `==`.** Resolve the exact version before adding one.
- **No test reads configuration from the environment.** Every test states its inputs
  explicitly. CI runs with no `.env` present, which is what catches a test that does not.
- **Coverage gate is 80 %.**
- **`ruff check` and `ruff format --check` must pass.**
- **Percentages are 0–100, not 0–1.** `target_pct = Decimal("60")` means sixty percent.
- Commit messages follow Conventional Commits.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata, ruff, pytest and coverage configuration |
| `requirements-dev.txt` | Pinned development dependencies |
| `.github/workflows/ci.yml` | Lint and test on every push and pull request |
| `engine/__init__.py` | Marks the package; exports nothing |
| `engine/types.py` | Value objects and enums: `Side`, `CashPolicy`, `Policy`, `Leg`, `Plan`, `UnpricedAsset` |
| `engine/valuation.py` | `Valuation` and `value_portfolio` — what the portfolio is worth and how it is weighted |
| `engine/drift.py` | `cash_target_pct`, `target_values`, `deltas`, `drifts` — how far each asset sits from its target |
| `engine/allocation.py` | `investable_cash`, `allocate_prorata`, `allocate_reduce_drift` — where new cash goes |
| `engine/reconcile.py` | `reconcile` — the single entry point that assembles a `Plan` |
| `tests/unit/engine/test_valuation.py` | Valuation, weights, unmanaged holdings, unpriced assets |
| `tests/unit/engine/test_drift.py` | Cash as remainder, target values, deltas, drifts |
| `tests/unit/engine/test_allocation.py` | Investable cash and both cash policies |
| `tests/unit/engine/test_reconcile.py` | End-to-end plans for every policy combination |

The split is by responsibility, not by layer. Valuation answers "what do I have", drift
answers "how far am I from what I want", allocation answers "where does new money go", and
reconcile is the only module that knows about all three.

---

### Task 1: Project scaffolding and CI

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `.github/workflows/ci.yml`
- Create: `engine/__init__.py`
- Create: `tests/unit/engine/test_smoke.py`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: nothing
- Produces: a working `pytest` and `ruff` invocation, and a green CI run. Later tasks
  assume `PYTHONPATH=.` and that `engine` is an importable package.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "coinpilot"
version = "0.1.0"
description = "Multi-tenant portfolio rebalancer for Kraken"
requires-python = ">=3.12"

[tool.ruff]
line-length = 110
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
minversion = "9.0"
testpaths = ["tests"]
addopts = "-ra --strict-markers --cov --cov-report=term-missing --cov-fail-under=80"
markers = [
    "unit: Unit tests with no network and no database.",
    "integration: Tests that may touch external services.",
]

[tool.coverage.run]
source = ["engine"]

[tool.coverage.report]
show_missing = true
```

- [ ] **Step 2: Write `requirements-dev.txt`**

```
pre-commit==4.6.2
pytest==9.1.1
pytest-cov==7.1.0
ruff==0.16.8
```

- [ ] **Step 3: Create the package and a smoke test**

`engine/__init__.py` is an empty file.

`tests/unit/engine/test_smoke.py`:

```python
import engine


def test_engine_package_is_importable():
    assert engine is not None
```

- [ ] **Step 4: Install and run the tools**

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest tests/unit -q
```

Expected: 1 passed. Coverage will report 100 % of an empty package.

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 5: Add ruff to the pre-commit hooks**

Append to `.pre-commit-config.yaml`, keeping the existing entries untouched:

```yaml
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.8
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 6: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  test:
    name: Lint and unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6.0.2

      - name: Set up Python
        uses: actions/setup-python@v6.0.0
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: ruff check
        run: ruff check .

      - name: ruff format --check
        run: ruff format --check .

      - name: Unit tests
        run: PYTHONPATH=. pytest tests/unit
```

- [ ] **Step 7: Commit and confirm CI is green**

```bash
git add pyproject.toml requirements-dev.txt .github/workflows/ci.yml engine/__init__.py tests/unit/engine/test_smoke.py .pre-commit-config.yaml
git commit -m "chore: project scaffolding, lint and CI"
git push origin main
```

Then check the run: `gh run list --branch main --limit 1`. Expected: success.

---

### Task 2: Value objects

**Files:**
- Create: `engine/types.py`
- Test: covered by every later test file; no test file of its own

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Side.BUY`, `Side.SELL` — `str` enum
  - `CashPolicy.PRORATA`, `CashPolicy.REDUCE_DRIFT` — `str` enum
  - `Policy(allow_sells: bool, cash_policy: CashPolicy, min_drift_pct: Decimal, min_order_fiat: Decimal)`
  - `Leg(asset: str, side: Side, amount_fiat: Decimal)`
  - `Plan(legs: tuple[Leg, ...])` with an `is_empty` property
  - `UnpricedAsset(Exception)`

Holdings, prices and targets are passed as plain mappings keyed by asset code, so they need
no class of their own:

| Argument | Type | Meaning |
|---|---|---|
| `holdings` | `Mapping[str, Decimal]` | asset code to amount held, in base units |
| `prices` | `Mapping[str, Decimal]` | asset code to price, in the user's fiat |
| `targets` | `Mapping[str, Decimal]` | asset code to target percent, 0–100 |
| `cash` | `Decimal` | fiat balance |

- [ ] **Step 1: Write `engine/types.py`**

```python
"""Value objects for the reconciliation engine.

This module performs no I/O, reads no configuration and holds no state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class Side(str, Enum):
    """Which way an order goes."""

    BUY = "buy"
    SELL = "sell"


class CashPolicy(str, Enum):
    """How available cash is distributed across the managed assets."""

    PRORATA = "prorata"
    REDUCE_DRIFT = "reduce_drift"


class UnpricedAsset(Exception):
    """A managed asset has no price.

    Raised rather than skipped: an asset that is managed but cannot be valued makes
    every weight in the portfolio wrong, so it must not pass silently.
    """

    def __init__(self, asset: str) -> None:
        super().__init__(f"no price for managed asset {asset!r}")
        self.asset = asset


@dataclass(frozen=True)
class Policy:
    """The knobs one reconciliation runs with."""

    allow_sells: bool
    cash_policy: CashPolicy
    min_drift_pct: Decimal
    min_order_fiat: Decimal


@dataclass(frozen=True)
class Leg:
    """One order the plan asks for, denominated in fiat."""

    asset: str
    side: Side
    amount_fiat: Decimal


@dataclass(frozen=True)
class Plan:
    """The whole outcome of one reconciliation. Sells come before the buys they fund."""

    legs: tuple[Leg, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.legs
```

- [ ] **Step 2: Verify it imports and lints**

```bash
PYTHONPATH=. python -c "from engine.types import Plan, Policy, Side; print(Plan().is_empty)"
```

Expected: `True`.

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 3: Commit**

```bash
git add engine/types.py
git commit -m "feat(engine): value objects for the reconciliation engine"
```

---

### Task 3: Portfolio valuation

**Files:**
- Create: `engine/valuation.py`
- Test: `tests/unit/engine/test_valuation.py`

**Interfaces:**
- Consumes: `engine.types.UnpricedAsset`, `ZERO`, `HUNDRED`
- Produces:
  - `Valuation(asset_values: dict[str, Decimal], cash: Decimal, managed_value: Decimal, weights: dict[str, Decimal], cash_weight: Decimal)`
  - `value_portfolio(holdings, prices, targets, cash) -> Valuation`

**Rules this implements** (spec §3.1, §3.2, §3.3):
- Only assets present in `targets` are managed. Anything else the user holds is ignored
  here and never enters `managed_value`.
- `managed_value` is the sum of managed asset values plus cash.
- Weights are percentages of `managed_value`.
- A managed asset with no price raises `UnpricedAsset`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/engine/test_valuation.py`:

```python
from decimal import Decimal

import pytest

from engine.types import UnpricedAsset
from engine.valuation import value_portfolio

D = Decimal


def test_values_managed_assets_and_cash():
    v = value_portfolio(
        holdings={"BTC": D("2"), "ETH": D("10")},
        prices={"BTC": D("100"), "ETH": D("10")},
        targets={"BTC": D("60"), "ETH": D("30")},
        cash=D("100"),
    )

    assert v.asset_values == {"BTC": D("200"), "ETH": D("100")}
    assert v.cash == D("100")
    assert v.managed_value == D("400")


def test_weights_are_percentages_of_managed_value():
    v = value_portfolio(
        holdings={"BTC": D("2")},
        prices={"BTC": D("100")},
        targets={"BTC": D("80")},
        cash=D("300"),
    )

    assert v.weights == {"BTC": D("40")}
    assert v.cash_weight == D("60")


def test_unconfigured_holdings_are_ignored_entirely():
    """An asset with no target row is not managed: it never enters the denominator."""
    v = value_portfolio(
        holdings={"BTC": D("1"), "DOGE": D("1000")},
        prices={"BTC": D("100"), "DOGE": D("5")},
        targets={"BTC": D("100")},
        cash=D("0"),
    )

    assert "DOGE" not in v.asset_values
    assert v.managed_value == D("100")
    assert v.weights == {"BTC": D("100")}


def test_a_target_with_no_holding_is_valued_at_zero():
    v = value_portfolio(
        holdings={},
        prices={"BTC": D("100")},
        targets={"BTC": D("50")},
        cash=D("100"),
    )

    assert v.asset_values == {"BTC": D("0")}
    assert v.managed_value == D("100")


def test_managed_asset_without_a_price_raises():
    with pytest.raises(UnpricedAsset) as excinfo:
        value_portfolio(
            holdings={"BTC": D("1")},
            prices={},
            targets={"BTC": D("100")},
            cash=D("0"),
        )

    assert excinfo.value.asset == "BTC"


def test_empty_portfolio_has_zero_weights_and_does_not_divide_by_zero():
    v = value_portfolio(
        holdings={},
        prices={"BTC": D("100")},
        targets={"BTC": D("100")},
        cash=D("0"),
    )

    assert v.managed_value == D("0")
    assert v.weights == {"BTC": D("0")}
    assert v.cash_weight == D("0")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_valuation.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'engine.valuation'`

- [ ] **Step 3: Write `engine/valuation.py`**

```python
"""What the managed portfolio is worth, and how it is weighted."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from engine.types import HUNDRED, ZERO, UnpricedAsset


@dataclass(frozen=True)
class Valuation:
    """A snapshot of the managed portfolio at one set of prices."""

    asset_values: dict[str, Decimal]
    cash: Decimal
    managed_value: Decimal
    weights: dict[str, Decimal]
    cash_weight: Decimal


def value_portfolio(
    holdings: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
    targets: Mapping[str, Decimal],
    cash: Decimal,
) -> Valuation:
    """Value only the assets the user configured; everything else is not managed."""
    asset_values: dict[str, Decimal] = {}
    for asset in targets:
        price = prices.get(asset)
        if price is None:
            raise UnpricedAsset(asset)
        asset_values[asset] = holdings.get(asset, ZERO) * price

    managed_value = sum(asset_values.values(), ZERO) + cash

    if managed_value == ZERO:
        weights = dict.fromkeys(asset_values, ZERO)
        cash_weight = ZERO
    else:
        weights = {a: v / managed_value * HUNDRED for a, v in asset_values.items()}
        cash_weight = cash / managed_value * HUNDRED

    return Valuation(
        asset_values=asset_values,
        cash=cash,
        managed_value=managed_value,
        weights=weights,
        cash_weight=cash_weight,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_valuation.py -v --no-cov`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/valuation.py tests/unit/engine/test_valuation.py
git commit -m "feat(engine): value the managed portfolio and its weights"
```

---

### Task 4: Targets, deltas and drift

**Files:**
- Create: `engine/drift.py`
- Test: `tests/unit/engine/test_drift.py`

**Interfaces:**
- Consumes: `engine.valuation.Valuation`, `engine.types.ZERO`, `engine.types.HUNDRED`
- Produces:
  - `cash_target_pct(targets) -> Decimal`
  - `target_values(valuation, targets) -> dict[str, Decimal]`
  - `deltas(valuation, targets) -> dict[str, Decimal]` — fiat to add (positive) or remove (negative)
  - `drifts(valuation, targets) -> dict[str, Decimal]` — percentage points away from target, signed

**Rules this implements** (spec §3.2):
- Cash is the remainder: `cash_target_pct = 100 - sum(targets)`.
- A delta is expressed in fiat; a drift is expressed in percentage points.

- [ ] **Step 1: Write the failing tests**

`tests/unit/engine/test_drift.py`:

```python
from decimal import Decimal

from engine.drift import cash_target_pct, deltas, drifts, target_values
from engine.valuation import value_portfolio

D = Decimal


def _valuation(btc_amount, cash, btc_target):
    return value_portfolio(
        holdings={"BTC": D(btc_amount)},
        prices={"BTC": D("100")},
        targets={"BTC": D(btc_target)},
        cash=D(cash),
    )


def test_cash_target_is_whatever_the_assets_do_not_claim():
    assert cash_target_pct({"BTC": D("60"), "ETH": D("35")}) == D("5")


def test_cash_target_is_zero_when_assets_claim_everything():
    assert cash_target_pct({"BTC": D("60"), "ETH": D("40")}) == D("0")


def test_target_values_are_a_share_of_the_managed_value():
    v = _valuation("1", "100", "50")  # managed value 200

    assert target_values(v, {"BTC": D("50")}) == {"BTC": D("100")}


def test_delta_is_positive_when_the_asset_is_underweight():
    v = _valuation("1", "300", "50")  # BTC 100 of 400, target 200

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("100")}


def test_delta_is_negative_when_the_asset_is_overweight():
    v = _valuation("3", "100", "50")  # BTC 300 of 400, target 200

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("-100")}


def test_drift_is_signed_percentage_points_not_fiat():
    v = _valuation("3", "100", "50")  # BTC weighs 75 %, target 50 %

    assert drifts(v, {"BTC": D("50")}) == {"BTC": D("25")}


def test_a_portfolio_on_target_has_zero_delta_and_zero_drift():
    v = _valuation("2", "200", "50")  # BTC 200 of 400

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("0")}
    assert drifts(v, {"BTC": D("50")}) == {"BTC": D("0")}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_drift.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'engine.drift'`

- [ ] **Step 3: Write `engine/drift.py`**

```python
"""How far each managed asset sits from the weight the user asked for."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from engine.types import HUNDRED, ZERO
from engine.valuation import Valuation


def cash_target_pct(targets: Mapping[str, Decimal]) -> Decimal:
    """Cash is the remainder: whatever the asset weights do not claim."""
    return HUNDRED - sum(targets.values(), ZERO)


def target_values(valuation: Valuation, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """What each asset would be worth if the portfolio were exactly on target."""
    return {
        asset: valuation.managed_value * pct / HUNDRED for asset, pct in targets.items()
    }


def deltas(valuation: Valuation, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Fiat to add (positive) or to remove (negative) to reach the target."""
    wanted = target_values(valuation, targets)
    return {asset: wanted[asset] - valuation.asset_values[asset] for asset in targets}


def drifts(valuation: Valuation, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Signed percentage points the real weight sits away from the target weight."""
    return {asset: valuation.weights[asset] - pct for asset, pct in targets.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_drift.py -v --no-cov`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/drift.py tests/unit/engine/test_drift.py
git commit -m "feat(engine): target values, deltas and drift"
```

---

### Task 5: Cash allocation policies

**Files:**
- Create: `engine/allocation.py`
- Test: `tests/unit/engine/test_allocation.py`

**Interfaces:**
- Consumes: `engine.valuation.Valuation`, `engine.drift.cash_target_pct`, `engine.types.ZERO`, `engine.types.HUNDRED`
- Produces:
  - `investable_cash(valuation, targets) -> Decimal`
  - `allocate_prorata(amount, targets) -> dict[str, Decimal]`
  - `allocate_reduce_drift(amount, asset_deltas, targets) -> dict[str, Decimal]`

**Rules this implements** (spec §3.2, §7.1):
- Investable cash is whatever sits above the cash target, never negative.
- `PRORATA` splits by target weight and deliberately ignores current drift. That is the
  plain contribution behaviour: buy everything in proportion.
- `REDUCE_DRIFT` fills the most underweight asset first. Ties break on asset code, so the
  result is deterministic. If the cash exceeds every shortfall, the remainder is split
  pro rata rather than left idle.

- [ ] **Step 1: Write the failing tests**

`tests/unit/engine/test_allocation.py`:

```python
from decimal import Decimal

from engine.allocation import allocate_prorata, allocate_reduce_drift, investable_cash
from engine.valuation import value_portfolio

D = Decimal


def test_investable_cash_is_what_sits_above_the_cash_target():
    v = value_portfolio(
        holdings={"BTC": D("1")},
        prices={"BTC": D("100")},
        targets={"BTC": D("90")},
        cash=D("100"),
    )  # managed value 200, cash target 10 % = 20

    assert investable_cash(v, {"BTC": D("90")}) == D("80")


def test_investable_cash_is_never_negative():
    v = value_portfolio(
        holdings={"BTC": D("9")},
        prices={"BTC": D("100")},
        targets={"BTC": D("50")},
        cash=D("100"),
    )  # cash target is 50 % of 1000 = 500, cash is 100

    assert investable_cash(v, {"BTC": D("50")}) == D("0")


def test_prorata_splits_by_target_weight():
    result = allocate_prorata(D("100"), {"BTC": D("60"), "ETH": D("20")})

    assert result == {"BTC": D("75"), "ETH": D("25")}


def test_prorata_ignores_drift_and_buys_an_overweight_asset_anyway():
    """This is the difference between the two policies, not an oversight."""
    result = allocate_prorata(D("100"), {"BTC": D("50"), "ETH": D("50")})

    assert result == {"BTC": D("50"), "ETH": D("50")}


def test_prorata_skips_assets_targeted_at_zero():
    result = allocate_prorata(D("100"), {"BTC": D("100"), "ETH": D("0")})

    assert result == {"BTC": D("100")}


def test_prorata_of_nothing_is_nothing():
    assert allocate_prorata(D("0"), {"BTC": D("100")}) == {}
    assert allocate_prorata(D("-5"), {"BTC": D("100")}) == {}


def test_reduce_drift_fills_the_most_underweight_first():
    asset_deltas = {"BTC": D("30"), "ETH": D("90")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"ETH": D("90"), "BTC": D("10")}


def test_reduce_drift_closes_the_gap_first_then_spreads_what_is_left():
    """An overweight asset gets nothing until every shortfall is closed.

    Once they are closed the portfolio is on target, so the leftover goes in by target
    weight rather than sitting idle — which is why BTC receives something here despite
    starting overweight.
    """
    asset_deltas = {"BTC": D("-50"), "ETH": D("40")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"ETH": D("70"), "BTC": D("30")}


def test_reduce_drift_splits_the_leftover_pro_rata_instead_of_leaving_it_idle():
    asset_deltas = {"BTC": D("10"), "ETH": D("10")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("60"), "ETH": D("40")})

    assert result == {"BTC": D("58"), "ETH": D("42")}


def test_reduce_drift_breaks_ties_on_asset_code_so_the_result_is_deterministic():
    asset_deltas = {"ETH": D("50"), "BTC": D("50")}

    result = allocate_reduce_drift(D("50"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"BTC": D("50")}


def test_reduce_drift_of_nothing_is_nothing():
    assert allocate_reduce_drift(D("0"), {"BTC": D("10")}, {"BTC": D("100")}) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_allocation.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'engine.allocation'`

- [ ] **Step 3: Write `engine/allocation.py`**

```python
"""Where available cash goes.

Two policies, and the difference between them is the whole point: `PRORATA` buys in
proportion to the targets and ignores where the portfolio currently sits, while
`REDUCE_DRIFT` spends the same cash on whatever is furthest behind.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from engine.drift import cash_target_pct
from engine.types import HUNDRED, ZERO
from engine.valuation import Valuation


def investable_cash(valuation: Valuation, targets: Mapping[str, Decimal]) -> Decimal:
    """Cash above the cash target. Never negative: a cash shortfall is not a sell signal."""
    wanted = valuation.managed_value * cash_target_pct(targets) / HUNDRED
    excess = valuation.cash - wanted
    return excess if excess > ZERO else ZERO


def allocate_prorata(amount: Decimal, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Split `amount` across the targets in proportion to their weights."""
    total = sum(targets.values(), ZERO)
    if amount <= ZERO or total <= ZERO:
        return {}
    return {
        asset: amount * pct / total for asset, pct in targets.items() if pct > ZERO
    }


def allocate_reduce_drift(
    amount: Decimal,
    asset_deltas: Mapping[str, Decimal],
    targets: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    """Spend `amount` on the biggest shortfalls first, then split any leftover pro rata."""
    if amount <= ZERO:
        return {}

    shortfalls = {a: d for a, d in asset_deltas.items() if d > ZERO}
    allocated: dict[str, Decimal] = {}
    remaining = amount

    # Sorting on the negated shortfall puts the biggest first; the asset code breaks ties
    # so that two equal shortfalls always resolve the same way.
    for asset, shortfall in sorted(shortfalls.items(), key=lambda kv: (-kv[1], kv[0])):
        if remaining <= ZERO:
            break
        take = shortfall if shortfall <= remaining else remaining
        allocated[asset] = take
        remaining -= take

    if remaining > ZERO:
        for asset, extra in allocate_prorata(remaining, targets).items():
            allocated[asset] = allocated.get(asset, ZERO) + extra

    return allocated
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_allocation.py -v --no-cov`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/allocation.py tests/unit/engine/test_allocation.py
git commit -m "feat(engine): investable cash and the two allocation policies"
```

---

### Task 6: Reconcile

**Files:**
- Create: `engine/reconcile.py`
- Test: `tests/unit/engine/test_reconcile.py`

**Interfaces:**
- Consumes: everything from tasks 2 to 5
- Produces: `reconcile(holdings, prices, targets, cash, policy) -> Plan` — the single entry
  point the rest of the system will call

**Rules this implements** (spec §3.4, §7.1, §7.2, §7.3):
- `allow_sells=False` is an invest operation: it spends only the investable cash and can
  never produce a sell leg.
- `allow_sells=True` is a rebalance: every asset moves to its target, and an asset whose
  absolute drift is below `min_drift_pct` produces no leg at all.
- A leg worth less than `min_order_fiat` is dropped.
- Legs are ordered sells first, then buys, each group sorted by asset code. Sells fund the
  buys, so the order is part of the contract, not a cosmetic detail.

- [ ] **Step 1: Write the failing tests**

`tests/unit/engine/test_reconcile.py`:

```python
from decimal import Decimal

from engine.reconcile import reconcile
from engine.types import CashPolicy, Leg, Policy, Side

D = Decimal

PRICES = {"BTC": D("100"), "ETH": D("10")}


def _buy(asset: str, amount: Decimal) -> Leg:
    return Leg(asset=asset, side=Side.BUY, amount_fiat=amount)


def _sell(asset: str, amount: Decimal) -> Leg:
    return Leg(asset=asset, side=Side.SELL, amount_fiat=amount)


def _policy(
    *,
    allow_sells: bool,
    cash_policy: CashPolicy = CashPolicy.PRORATA,
    min_drift_pct: Decimal = D("0"),
    min_order_fiat: Decimal = D("0"),
) -> Policy:
    return Policy(
        allow_sells=allow_sells,
        cash_policy=cash_policy,
        min_drift_pct=min_drift_pct,
        min_order_fiat=min_order_fiat,
    )


def test_invest_spends_the_cash_and_never_sells():
    plan = reconcile(
        holdings={"BTC": D("1")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("100"),
        policy=_policy(allow_sells=False),
    )

    assert all(leg.side is Side.BUY for leg in plan.legs)
    assert sum(leg.amount_fiat for leg in plan.legs) == D("100")


def test_invest_with_no_spare_cash_produces_an_empty_plan():
    plan = reconcile(
        holdings={"BTC": D("1")},
        prices=PRICES,
        targets={"BTC": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=False),
    )

    assert plan.is_empty


def test_invest_reduce_drift_puts_the_cash_where_the_gap_is():
    plan = reconcile(
        holdings={"BTC": D("2"), "ETH": D("0")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("100"),
        policy=_policy(allow_sells=False, cash_policy=CashPolicy.REDUCE_DRIFT),
    )

    assert plan.legs == (_buy("ETH", D("100")),)


def test_rebalance_sells_the_overweight_and_buys_the_underweight():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )  # managed 400: BTC 300, ETH 100, target 200 each

    assert plan.legs == (_sell("BTC", D("100")), _buy("ETH", D("100")))


def test_rebalance_puts_sells_before_buys():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    sides = [leg.side for leg in plan.legs]
    assert sides == [Side.SELL, Side.BUY]


def test_an_asset_inside_the_drift_band_produces_no_leg():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True, min_drift_pct=D("30")),
    )  # each drifts 25 points, which is inside a 30-point band

    assert plan.is_empty


def test_a_leg_below_the_minimum_order_is_dropped():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True, min_order_fiat=D("150")),
    )  # both legs are worth 100

    assert plan.is_empty


def test_a_target_of_zero_asks_to_exit_the_position():
    plan = reconcile(
        holdings={"BTC": D("1"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("100"), "ETH": D("0")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )  # managed 200: ETH must go to zero

    assert _sell("ETH", D("100")) in plan.legs


def test_an_unconfigured_holding_is_never_touched():
    plan = reconcile(
        holdings={"BTC": D("1"), "DOGE": D("1000")},
        prices={"BTC": D("100"), "DOGE": D("5")},
        targets={"BTC": D("100")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    assert all(leg.asset != "DOGE" for leg in plan.legs)


def test_a_portfolio_on_target_produces_an_empty_plan():
    plan = reconcile(
        holdings={"BTC": D("2"), "ETH": D("20")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    assert plan.is_empty
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_reconcile.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'engine.reconcile'`

- [ ] **Step 3: Write `engine/reconcile.py`**

```python
"""The single entry point of the engine.

Everything arrives as an argument and a frozen `Plan` comes back. No I/O, no
configuration, no state.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from engine.allocation import allocate_prorata, allocate_reduce_drift, investable_cash
from engine.drift import deltas, drifts
from engine.types import ZERO, CashPolicy, Leg, Plan, Policy, Side
from engine.valuation import value_portfolio


def reconcile(
    holdings: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
    targets: Mapping[str, Decimal],
    cash: Decimal,
    policy: Policy,
) -> Plan:
    """Turn a portfolio and a set of targets into the orders that close the gap."""
    valuation = value_portfolio(holdings, prices, targets, cash)
    asset_deltas = deltas(valuation, targets)

    if policy.allow_sells:
        asset_drifts = drifts(valuation, targets)
        amounts = {
            asset: delta
            for asset, delta in asset_deltas.items()
            if abs(asset_drifts[asset]) >= policy.min_drift_pct
        }
    else:
        spendable = investable_cash(valuation, targets)
        if policy.cash_policy is CashPolicy.PRORATA:
            amounts = allocate_prorata(spendable, targets)
        else:
            amounts = allocate_reduce_drift(spendable, asset_deltas, targets)

    legs = []
    for asset, amount in amounts.items():
        side = Side.BUY if amount > ZERO else Side.SELL
        value = abs(amount)
        if value < policy.min_order_fiat or value == ZERO:
            continue
        legs.append(Leg(asset=asset, side=side, amount_fiat=value))

    # Sells first: they raise the money the buys spend. `Side.BUY` sorts as True, so
    # this puts every sell ahead of every buy, and the asset code orders within a group.
    legs.sort(key=lambda leg: (leg.side is Side.BUY, leg.asset))
    return Plan(legs=tuple(legs))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/engine/test_reconcile.py -v --no-cov`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/reconcile.py tests/unit/engine/test_reconcile.py
git commit -m "feat(engine): reconcile holdings toward target weights"
```

---

### Task 7: Phase gate — full suite, lint and CI

**Files:**
- Modify: `tests/unit/engine/test_smoke.py` (delete it; the package is well covered now)

**Interfaces:**
- Consumes: every module from tasks 2 to 6
- Produces: a verified phase 1. Nothing later depends on this task's output beyond the
  guarantee that the suite is green.

- [ ] **Step 1: Remove the smoke test**

It existed to prove the scaffolding worked. Four real test files now do that.

```bash
git rm tests/unit/engine/test_smoke.py
```

- [ ] **Step 2: Run the whole suite with coverage**

Run: `PYTHONPATH=. pytest tests/unit`
Expected: 34 passed, and `Required test coverage of 80% reached`.

If coverage falls below 80 %, find the uncovered lines in the report and add the missing
test to the file that owns that module. Do not lower the gate.

- [ ] **Step 3: Run lint and format**

```bash
ruff check . && ruff format --check .
```

Expected: both pass.

- [ ] **Step 4: Commit and push**

```bash
git add -A
git commit -m "test: drop the scaffolding smoke test"
git push origin main
```

- [ ] **Step 5: Confirm CI is green**

```bash
gh run list --branch main --limit 1
```

Expected: `success`.

---

## What you verify before phase 2

Phase 1 touches no money, no credentials and no network, so verification is reading and
running:

1. **The suite is green and CI agrees.** `PYTHONPATH=. pytest tests/unit` locally, and a
   green run on GitHub.
2. **The arithmetic matches your expectations.** Read
   `tests/unit/engine/test_reconcile.py` and check each case against what you would do by
   hand. This is the phase where a wrong rule is cheap to change, and the last phase where
   it is obvious.
3. **Two behaviours deserve a deliberate look**, because they are choices rather than
   consequences:
   - `PRORATA` buys an asset that is already overweight. That is the plain contribution
     behaviour; `REDUCE_DRIFT` exists for the other intention.
   - `min_drift_pct` filters per asset, not per portfolio. An asset inside the band
     produces no leg even when another asset is far outside it.
4. **The engine imports nothing outside itself.** Run
   ```bash
   grep -rh "^from \|^import " engine/ | grep -vE "engine\.|__future__|collections|dataclasses|decimal|enum"
   ```
   Expected: no output. That property is what keeps this code testable without mocks, and
   it is easy to lose by accident in a later phase.

---

## Departures taken during execution

The code blocks above are the plan as written. Three of them do not match what was
committed, and the difference is deliberate in each case. Trust the repository, not this
document, where the two disagree.

| Where | The plan said | What was committed | Why |
|---|---|---|---|
| `engine/types.py` | `class Side(str, Enum)` | `class Side(StrEnum)` | Rule `UP042` forbids the pair on Python 3.12. `StrEnum` also makes `str(Side.BUY)` return `"buy"`, which later serialisation needs. |
| `tests/unit/engine/test_reconcile.py` | `min_drift_pct: Decimal = D("0")` | `min_drift_pct: Decimal = ZERO` | Rule `B008` forbids a call in an argument default. `engine.types.ZERO` already exists for this. |
| `pyproject.toml` | no `extend-exclude` | `extend-exclude = ["docs"]` | Ruff 0.16 formats Python blocks inside Markdown, and wanted to rewrite this document. The formatter governs source code, not written records. |

Two code blocks were also joined onto one line by `ruff format`, which applies the
configured line length of 110 rather than the 88 the plan was typed at.
