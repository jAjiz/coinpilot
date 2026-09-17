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
    return {asset: valuation.managed_value * pct / HUNDRED for asset, pct in targets.items()}


def deltas(valuation: Valuation, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Fiat to add (positive) or to remove (negative) to reach the target."""
    wanted = target_values(valuation, targets)
    return {asset: wanted[asset] - valuation.asset_values[asset] for asset in targets}


def drifts(valuation: Valuation, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Signed percentage points the real weight sits away from the target weight."""
    return {asset: valuation.weights[asset] - pct for asset, pct in targets.items()}
