"""Kraken's order vocabulary, and the identifier this system puts on every attempt."""

from __future__ import annotations

import uuid

from exchange.types import ExchangeOrderStatus

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
