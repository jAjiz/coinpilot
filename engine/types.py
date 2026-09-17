"""Value objects for the reconciliation engine.

This module performs no I/O, reads no configuration and holds no state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class Side(StrEnum):
    """Which way an order goes."""

    BUY = "buy"
    SELL = "sell"


class CashPolicy(StrEnum):
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
