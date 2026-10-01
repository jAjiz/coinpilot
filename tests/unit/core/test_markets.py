from decimal import Decimal

import pytest

from core.markets import kraken_key, resolve_pair, short_name, split_balance_key
from exchange.types import PairMeta

NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "ZUSD": "USD", "SOL": "SOL"}


def _pair(name, base, quote, status="online"):
    return PairMeta(
        pair=name,
        altname=name,
        base=base,
        quote=quote,
        price_decimals=1,
        volume_decimals=8,
        order_min=Decimal("0.0001"),
        cost_min=Decimal("0.5"),
        status=status,
        cost_decimals=5,
    )


PAIRS = {
    "XXBTZEUR": _pair("XXBTZEUR", "XXBT", "ZEUR"),
    "XXBTZUSD": _pair("XXBTZUSD", "XXBT", "ZUSD"),
    "SOLEUR": _pair("SOLEUR", "SOL", "ZEUR"),
}


@pytest.mark.parametrize(
    ("code", "expected"), [("XBT", "XBT"), ("xbt", "XBT"), ("XXBT", "XBT"), (" sol ", "SOL")]
)
def test_an_asset_is_known_by_its_short_name_or_its_internal_one(code, expected):
    assert short_name(code, NAMES) == expected


@pytest.mark.parametrize("code", ["BTC", "", "NOPE"])
def test_a_name_kraken_does_not_list_is_none(code):
    assert short_name(code, NAMES) is None


def test_the_internal_name_is_found_from_the_short_one():
    assert kraken_key("xbt", NAMES) == "XXBT"
    assert kraken_key("BTC", NAMES) is None


@pytest.mark.parametrize(
    ("key", "expected"),
    [("XXBT", ("XBT", "")), ("XBT.F", ("XBT", "F")), ("DOT.S", ("DOT", "S")), ("ZEUR", ("EUR", ""))],
)
def test_a_balance_key_splits_into_the_asset_and_its_suffix(key, expected):
    assert split_balance_key(key, NAMES) == expected


def test_an_asset_resolves_to_its_pair_against_the_fiat():
    assert resolve_pair("XBT", "EUR", NAMES, PAIRS).pair == "XXBTZEUR"
    assert resolve_pair("XBT", "USD", NAMES, PAIRS).pair == "XXBTZUSD"


def test_a_pair_whose_internal_name_is_its_short_name_resolves_too():
    assert resolve_pair("SOL", "EUR", NAMES, PAIRS).pair == "SOLEUR"


def test_a_dark_pool_pair_is_never_the_answer():
    """Same base and quote as the lit pair, and it does not take market orders."""
    only_dark = {"XXBTZEUR.d": _pair("XXBTZEUR.d", "XXBT", "ZEUR")}

    assert resolve_pair("XBT", "EUR", NAMES, only_dark) is None


def test_the_lit_pair_wins_when_both_are_listed():
    both = {**PAIRS, "XXBTZEUR.d": _pair("XXBTZEUR.d", "XXBT", "ZEUR")}

    assert resolve_pair("XBT", "EUR", NAMES, both).pair == "XXBTZEUR"


def test_a_pair_that_is_not_online_is_refused_now_rather_than_at_order_time():
    halted = {"XXBTZEUR": _pair("XXBTZEUR", "XXBT", "ZEUR", status="cancel_only")}

    assert resolve_pair("XBT", "EUR", NAMES, halted) is None


def test_an_asset_with_no_pair_against_this_fiat_is_none():
    assert resolve_pair("ETH", "EUR", NAMES, PAIRS) is None


def test_the_fiat_is_not_an_asset_of_itself():
    assert resolve_pair("EUR", "EUR", NAMES, PAIRS) is None
