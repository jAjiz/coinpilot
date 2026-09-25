"""Kraken's order vocabulary, and the identifier this system puts on every attempt."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from exchange.types import ExchangeOrderStatus, OrderLookup

ZERO = Decimal("0")

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


ABSENT = OrderLookup(txid=None, status=None, volume=ZERO, volume_executed=ZERO, price=ZERO, fee=ZERO)


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
