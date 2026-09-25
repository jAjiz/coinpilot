"""Where a number meets the precision its pair will accept.

Every rounding rule comes from the pair, never from a constant. A constant is invisible
on a pair worth tens of thousands and destroys one worth a fraction of a cent.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from exchange.types import PairMeta


def format_decimal(value: Decimal) -> str:
    """The string form Kraken accepts.

    `str` switches to scientific notation below a millionth, so `Decimal("0.00000001")`
    becomes `"1E-8"` and the request is rejected. Bitcoin rounds to eight places, which
    puts that inside the ordinary range of a real order.
    """
    return format(value, "f")


def _quantum(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


def round_price(meta: PairMeta, price: Decimal) -> Decimal:
    """To the pair's price precision. Half up, because a price is a reading."""
    return price.quantize(_quantum(meta.price_decimals), rounding=ROUND_HALF_UP)


def round_volume(meta: PairMeta, volume: Decimal) -> Decimal:
    """To the pair's volume precision, always down.

    Down is not a preference. Rounding a buy up spends more than was allocated, and
    rounding a sell up asks to sell coins the user does not hold.
    """
    return volume.quantize(_quantum(meta.volume_decimals), rounding=ROUND_DOWN)


def volume_from_fiat(meta: PairMeta, amount_fiat: Decimal, price: Decimal) -> Decimal:
    """How much of the base asset `amount_fiat` buys, rounded down.

    Raises on a price that is not positive. Returning zero instead would drop the leg
    silently, and a missing order is harder to notice than a refused one.
    """
    if price <= 0:
        raise ValueError(f"cannot size an order at a price of {price}")
    return round_volume(meta, amount_fiat / price)


def is_orderable(meta: PairMeta, volume: Decimal, cost: Decimal) -> bool:
    """Whether Kraken will accept an order of this size on this pair.

    Both minimums are the pair's own. A volume that rounded down to zero fails here,
    which is the point of checking after rounding rather than before.
    """
    return volume >= meta.order_min and cost >= meta.cost_min
