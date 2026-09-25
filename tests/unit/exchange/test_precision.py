from decimal import Decimal

import pytest

from exchange.precision import (
    format_decimal,
    is_orderable,
    round_price,
    round_volume,
    volume_from_fiat,
)
from exchange.types import PairMeta

D = Decimal

BTC = PairMeta(
    pair="XXBTZEUR",
    altname="XBTEUR",
    base="XXBT",
    quote="ZEUR",
    price_decimals=1,
    volume_decimals=8,
    order_min=D("0.00005"),
    cost_min=D("5"),
    status="online",
)

# A pair whose price is a fraction of a cent. A rounding rule taken from a constant
# instead of from the pair destroys this one and leaves Bitcoin looking fine.
CHEAP = PairMeta(
    pair="XDGEUR",
    altname="XDGEUR",
    base="XDG",
    quote="ZEUR",
    price_decimals=7,
    volume_decimals=8,
    order_min=D("20"),
    cost_min=D("5"),
    status="online",
)


def test_a_small_decimal_is_written_in_full_not_in_scientific_notation():
    """`str` would give "1E-8" here, and Kraken rejects it."""
    assert format_decimal(D("0.00000001")) == "0.00000001"


def test_format_leaves_an_ordinary_number_alone():
    assert format_decimal(D("1.25")) == "1.25"
    assert format_decimal(D("12345.6")) == "12345.6"


def test_format_keeps_trailing_zeros_because_they_carry_the_precision():
    assert format_decimal(D("0.00100000")) == "0.00100000"


def test_a_price_rounds_to_the_precision_of_its_own_pair():
    assert round_price(BTC, D("47123.456")) == D("47123.5")
    assert round_price(CHEAP, D("0.08213456")) == D("0.0821346")


def test_a_fraction_of_a_cent_survives_rounding():
    """The precision comes from the pair, so a cheap pair is not flattened to zero."""
    assert round_price(CHEAP, D("0.0000821")) == D("0.0000821")


def test_a_volume_always_rounds_down():
    """Rounding up would overspend on a buy and oversell on a sell."""
    assert round_volume(BTC, D("0.123456789")) == D("0.12345678")


def test_a_volume_below_the_pairs_precision_rounds_to_zero():
    """It is not an error here. `is_orderable` is what refuses it."""
    assert round_volume(BTC, D("0.000000001")) == D("0")


def test_volume_is_the_money_divided_by_the_price_rounded_down():
    volume = volume_from_fiat(BTC, D("100"), D("47000"))

    assert volume == D("0.00212765")


def test_a_price_of_zero_raises_instead_of_dividing():
    """A zero price is not a market state. Returning zero would silently drop the leg."""
    with pytest.raises(ValueError, match="price"):
        volume_from_fiat(BTC, D("100"), D("0"))


def test_a_negative_price_raises():
    with pytest.raises(ValueError, match="price"):
        volume_from_fiat(BTC, D("100"), D("-1"))


def test_an_order_below_the_pairs_minimum_volume_is_refused():
    assert is_orderable(BTC, volume=D("0.00001"), cost=D("100")) is False


def test_an_order_below_the_pairs_minimum_cost_is_refused():
    assert is_orderable(BTC, volume=D("1"), cost=D("4.99")) is False


def test_an_order_exactly_at_both_minimums_is_accepted():
    assert is_orderable(BTC, volume=D("0.00005"), cost=D("5")) is True


def test_a_pair_that_is_not_online_is_not_tradable():
    """Kraken publishes five statuses and only one of them accepts a market order."""
    frozen = PairMeta(
        pair="XXBTZEUR",
        altname="XBTEUR",
        base="XXBT",
        quote="ZEUR",
        price_decimals=1,
        volume_decimals=8,
        order_min=D("0.00005"),
        cost_min=D("5"),
        status="cancel_only",
    )

    assert BTC.tradable is True
    assert frozen.tradable is False
