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
    return {asset: amount * pct / total for asset, pct in targets.items() if pct > ZERO}


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
