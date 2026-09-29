"""What the account holds, valued and weighted, as one view.

Pure: the balances, names, prices and targets arrive as arguments. The engine's own
valuation produces the weights, so this view and a reconciliation can never disagree
about what the portfolio is worth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from core.markets import TRADABLE_SUFFIXES, split_balance_key
from engine.types import HUNDRED, ZERO
from engine.valuation import value_portfolio
from exchange.precision import format_decimal

PERCENT_STEP = Decimal("0.01")


@dataclass(frozen=True)
class Holding:
    asset: str
    amount: Decimal
    price: Decimal | None
    value: Decimal | None
    managed: bool
    locked: bool
    target_pct: Decimal | None
    weight_pct: Decimal | None


@dataclass(frozen=True)
class PortfolioView:
    fiat: str
    cash: Decimal
    cash_target_pct: Decimal
    cash_weight_pct: Decimal
    # Managed assets plus cash: the denominator of every weight (spec §3.2).
    managed_value: Decimal
    holdings: tuple[Holding, ...]

    def snapshot_json(self) -> dict[str, object]:
        """The `holdings` column of a snapshot. Every number is a string."""
        return {
            "cash_target_pct": _pct(self.cash_target_pct),
            "cash_weight_pct": _pct(self.cash_weight_pct),
            "assets": {holding.asset: _holding_json(holding) for holding in self.holdings},
        }


def build_view(
    balances: Mapping[str, Decimal],
    asset_names: Mapping[str, str],
    fiat: str,
    targets: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
) -> PortfolioView:
    """Raises `UnpricedAsset` when a managed asset has no price."""
    tradable: dict[str, Decimal] = {}
    locked: dict[str, Decimal] = {}
    for key, amount in balances.items():
        name, suffix = split_balance_key(key, asset_names)
        if suffix in TRADABLE_SUFFIXES:
            tradable[name] = tradable.get(name, ZERO) + amount
        else:
            label = f"{name}.{suffix}"
            locked[label] = locked.get(label, ZERO) + amount

    cash = tradable.pop(fiat, ZERO)
    valuation = value_portfolio(tradable, prices, targets, cash)

    holdings: list[Holding] = [
        Holding(
            asset=asset,
            amount=tradable.get(asset, ZERO),
            price=prices[asset],
            value=valuation.asset_values[asset],
            managed=True,
            locked=False,
            target_pct=targets[asset],
            weight_pct=valuation.weights[asset],
        )
        for asset in sorted(targets)
    ]
    for asset in sorted(set(tradable) - set(targets)):
        amount = tradable[asset]
        if amount == ZERO:
            continue
        price = prices.get(asset)
        holdings.append(
            Holding(
                asset=asset,
                amount=amount,
                price=price,
                value=None if price is None else amount * price,
                managed=False,
                locked=False,
                target_pct=None,
                weight_pct=None,
            )
        )
    for label in sorted(locked):
        if locked[label] == ZERO:
            continue
        holdings.append(
            Holding(
                asset=label,
                amount=locked[label],
                price=None,
                value=None,
                managed=False,
                locked=True,
                target_pct=None,
                weight_pct=None,
            )
        )

    return PortfolioView(
        fiat=fiat,
        cash=cash,
        cash_target_pct=HUNDRED - sum(targets.values(), ZERO),
        cash_weight_pct=valuation.cash_weight,
        managed_value=valuation.managed_value,
        holdings=tuple(holdings),
    )


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value.quantize(PERCENT_STEP))


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _holding_json(holding: Holding) -> dict[str, object]:
    return {
        "amount": _amount(holding.amount),
        "price": _amount(holding.price),
        "value": _amount(holding.value),
        "managed": holding.managed,
        "locked": holding.locked,
        "target_pct": _pct(holding.target_pct),
        "weight_pct": _pct(holding.weight_pct),
    }
