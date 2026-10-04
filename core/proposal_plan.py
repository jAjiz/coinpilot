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
