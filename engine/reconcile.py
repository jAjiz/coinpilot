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
