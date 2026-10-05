"""What became of an order: reading its fill, and resolving what is still unknown.

Spec §9.2 and §9.5. Used before every evaluation, and right after an order is sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import core.database as db
from core.db.types import OrderStatus
from engine.types import ZERO
from exchange.orders import find_order_by_cl_ord_id, find_order_by_txid
from exchange.types import ExchangeOrderStatus, OrderLookup

# Kraken may not list an order it accepted a moment ago. An absence read sooner than this
# after the attempt is not believed: failing the row would let the next plan buy again.
ABSENCE_GRACE = timedelta(minutes=2)

_FINISHED = (ExchangeOrderStatus.CLOSED, ExchangeOrderStatus.CANCELED)


def settle(session: Session, cl_ord_id: str, lookup: OrderLookup | None) -> OrderStatus:
    """Write down what Kraken says about one order, and return the row's status.

    `None` is a lookup that failed: nothing is decided. `ABSENT` is evidence the order
    does not exist. A finished order is `FILLED` if anything executed, in whatever unit
    Kraken reports it.
    """
    if lookup is None:
        return OrderStatus.PENDING
    if lookup.txid is None:
        db.mark_failed(session, cl_ord_id)
        return OrderStatus.FAILED
    if lookup.status in _FINISHED:
        if lookup.volume_executed > ZERO:
            db.mark_filled(
                session,
                cl_ord_id,
                txid=lookup.txid,
                executed_volume=lookup.volume_executed,
                executed_price=lookup.price,
                fee=lookup.fee,
                cost=lookup.cost,
            )
            return OrderStatus.FILLED
        db.mark_failed(session, cl_ord_id, error=f"{lookup.status.value} with nothing executed")
        return OrderStatus.FAILED
    # Open, pending, or a word nobody modelled: it exists, and it is not finished.
    db.mark_sent(session, cl_ord_id, lookup.txid)
    return OrderStatus.PENDING


@dataclass(frozen=True)
class Resolution:
    clear: bool
    messages: tuple[str, ...]
    # Kraken did not answer a lookup: the system failing, not an order still on its way.
    lookup_failed: bool = False


def resolve_pending(
    sessions: Callable[[], AbstractContextManager[Session]],
    private,
    user_id: uuid.UUID,
    now: datetime,
) -> Resolution:
    """Resolve every `PENDING` attempt of one user. `clear` is false while any is unknown.

    A row with a txid is read by it: the order exists. A row without one is looked up by
    its client id, and an absence counts only once `ABSENCE_GRACE` has passed.
    """
    with sessions() as session:
        pending = [(o.cl_ord_id, o.txid, o.attempted_at) for o in db.pending_orders(session, user_id)]

    clear = True
    lookup_failed = False
    messages: list[str] = []
    for cl_ord_id, txid, attempted_at in pending:
        if txid is not None:
            lookup = find_order_by_txid(private, txid)
        else:
            lookup = find_order_by_cl_ord_id(private, cl_ord_id)
        if lookup is None:
            lookup_failed = True
        if lookup is not None and lookup.txid is None and now - attempted_at < ABSENCE_GRACE:
            clear = False
            messages.append(f"order {cl_ord_id}: not listed yet; absence is believed after the grace period")
            continue
        with sessions() as session:
            status = settle(session, cl_ord_id, lookup)
        if status is OrderStatus.PENDING:
            clear = False
            messages.append(f"order {cl_ord_id}: still unresolved")
        else:
            messages.append(f"order {cl_ord_id}: resolved as {status.value}")
    return Resolution(clear=clear, messages=tuple(messages), lookup_failed=lookup_failed)
