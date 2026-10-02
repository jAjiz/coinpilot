from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core.catalog import CATALOG_TTL, MarketCatalog
from exchange.types import PairMeta

START = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
NAMES = {"XXBT": "XBT", "ZEUR": "EUR"}


def _pair(name):
    return PairMeta(
        pair=name,
        altname=name,
        base="XXBT",
        quote="ZEUR",
        price_decimals=1,
        volume_decimals=8,
        order_min=Decimal("0.0001"),
        cost_min=Decimal("0.5"),
        status="online",
        cost_decimals=5,
    )


class FakeSource:
    def __init__(self):
        self.names = dict(NAMES)
        self.pairs = {"XXBTZEUR": _pair("XXBTZEUR")}
        self.calls = []

    def assets(self):
        self.calls.append("Assets")
        return None if self.names is None else dict(self.names)

    def asset_pairs(self):
        self.calls.append("AssetPairs")
        return None if self.pairs is None else dict(self.pairs)


def _catalog(source):
    clock = {"now": START}
    return MarketCatalog(source, lambda: clock["now"]), clock


def test_the_ttl_is_one_day():
    assert timedelta(days=1) == CATALOG_TTL


def test_the_names_are_read_once_within_a_day():
    source = FakeSource()
    catalog, clock = _catalog(source)

    assert catalog.asset_names() == NAMES
    clock["now"] += CATALOG_TTL - timedelta(seconds=1)
    assert catalog.asset_names() == NAMES
    assert source.calls == ["Assets"]


def test_the_names_are_read_again_after_a_day():
    source = FakeSource()
    catalog, clock = _catalog(source)
    catalog.asset_names()
    source.names["SOL"] = "SOL"

    clock["now"] += CATALOG_TTL

    assert catalog.asset_names()["SOL"] == "SOL"
    assert source.calls == ["Assets", "Assets"]


def test_a_failed_read_is_none_and_is_not_kept():
    source = FakeSource()
    source.names = None
    catalog, _ = _catalog(source)

    assert catalog.asset_names() is None
    source.names = dict(NAMES)
    assert catalog.asset_names() == NAMES
    assert source.calls == ["Assets", "Assets"]


def test_a_failed_refresh_does_not_serve_the_expired_copy():
    """Up to a day old is the promise. An older copy is not served in an outage."""
    source = FakeSource()
    catalog, clock = _catalog(source)
    catalog.asset_names()
    source.names = None

    clock["now"] += CATALOG_TTL

    assert catalog.asset_names() is None


def test_the_pairs_are_kept_apart_from_the_names():
    source = FakeSource()
    catalog, clock = _catalog(source)

    assert list(catalog.pairs()) == ["XXBTZEUR"]
    assert list(catalog.pairs()) == ["XXBTZEUR"]
    assert source.calls == ["AssetPairs"]
    clock["now"] += CATALOG_TTL
    catalog.pairs()
    assert source.calls == ["AssetPairs", "AssetPairs"]


def test_a_caller_cannot_change_the_shared_copy():
    catalog, _ = _catalog(FakeSource())

    with pytest.raises(TypeError):
        catalog.asset_names()["XXBT"] = "BTC"

    assert catalog.asset_names()["XXBT"] == "XBT"
