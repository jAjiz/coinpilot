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
