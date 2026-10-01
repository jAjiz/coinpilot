"""The vocabulary of the exchange boundary.

Every value here is frozen and carries no behaviour beyond reading itself. Kraken's words
are translated into these on the way in, and nothing outside this package ever sees a raw
Kraken field name.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class Credentials:
    """One user's Kraken key.

    It arrives already decrypted and is never logged, never put in an exception message,
    and never returned by anything in this package.
    """

    api_key: str
    api_secret: str


@dataclass(frozen=True)
class PairMeta:
    """What Kraken will accept for one tradable pair.

    `price_decimals` and `volume_decimals` are the rounding boundary: a number with more
    precision than this is rejected by the exchange, so it is rounded here and nowhere
    else.
    """

    pair: str
    altname: str
    base: str
    quote: str
    price_decimals: int
    volume_decimals: int
    order_min: Decimal
    cost_min: Decimal
    status: str
    # Decimal places of an amount in the quote currency. A buy in fiat is rounded to it.
    cost_decimals: int

    @property
    def tradable(self) -> bool:
        """Kraken publishes five statuses and only one of them accepts a market order."""
        return self.status == "online"


class ExchangeOrderStatus(StrEnum):
    """Kraken's order statuses, normalised.

    `NOT_FOUND` and `UNKNOWN` have no Kraken counterpart. The first means Kraken answered
    and does not know the id; the second means Kraken used a word this code does not
    model, which must fail loudly rather than be guessed at.
    """

    CANCELED = "canceled"
    CLOSED = "closed"
    NOT_FOUND = "not_found"
    OPEN = "open"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OrderLookup:
    """What one order looks like at the exchange.

    A lookup that resolved nothing carries `txid=None` and `status=None`. That is the
    answer *both endpoints replied and neither had it*, which is different from the
    lookup having failed — the caller gets `None` for that, never this.
    """

    txid: str | None
    status: ExchangeOrderStatus | None
    volume: Decimal
    volume_executed: Decimal
    price: Decimal
    fee: Decimal
    # As Kraken reports it. Whether a buy in fiat reports it in the quote currency is
    # verified on the first real order (phase 5 plan).
    cost: Decimal


class KeyRejection(StrEnum):
    """Why a key was refused. Never shown to anyone but its own owner."""

    FORBIDDEN_PERMISSIONS = "forbidden_permissions"
    INVALID_KEY = "invalid_key"
    LOCKED_OUT = "locked_out"
    MISSING_PERMISSIONS = "missing_permissions"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class KeyValidation:
    """The answer to *may this key be stored*.

    It names what is missing and what is forbidden so the user can fix their key without
    guessing. It carries no part of the key itself.
    """

    accepted: bool
    rejection: KeyRejection | None
    permissions: tuple[str, ...]
    missing: tuple[str, ...]
    forbidden: tuple[str, ...]
    ip_allowlist: tuple[str, ...]
    # Granted, neither required nor forbidden: never used, so better turned off. Advice only.
    unnecessary: tuple[str, ...] = ()


class PlacementOutcome(StrEnum):
    """What one `AddOrder` call achieved (spec §9.4).

    `UNKNOWN` is the lost answer of spec §9.2: the order may exist. `REFUSED` is Kraken
    saying it does not.
    """

    SENT = "sent"
    VALIDATED = "validated"
    REFUSED = "refused"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Placement:
    outcome: PlacementOutcome
    txid: str | None = None
    # Kraken's first error code, on a refusal only.
    error: str | None = None
