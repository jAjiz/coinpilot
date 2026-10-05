from datetime import UTC, datetime
from decimal import Decimal

from core.catalog import MarketCatalog
from core.public_market import Market, TickMarket

D = Decimal
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class FakeKraken:
    """The catalog's source and the public client at once, recording every call."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.prices = {"XXBTZEUR": D("50000"), "XETHZEUR": D("2500")}

    def assets(self):
        self.calls.append("Assets")
        return {"XXBT": "XBT", "ZEUR": "EUR"}

    def asset_decimals(self):
        self.calls.append("Assets")
        return {"EUR": 4}

    def asset_pairs(self):
        self.calls.append("AssetPairs")
        return {}

    def ticker(self, pairs):
        self.calls.append(("Ticker", tuple(pairs)))
        if self.down:
            return None
        return {pair: self.prices[pair] for pair in pairs if pair in self.prices}


def _market(kraken):
    return Market(MarketCatalog(kraken, lambda: NOW), kraken)


def _tickers(kraken):
    return [call[1] for call in kraken.calls if isinstance(call, tuple)]


def test_names_and_pairs_come_from_the_catalog_and_are_read_once():
    kraken = FakeKraken()
    market = _market(kraken)

    market.assets()
    names = market.assets()
    market.asset_pairs()
    market.asset_pairs()

    assert dict(names) == {"XXBT": "XBT", "ZEUR": "EUR"}
    assert kraken.calls == ["Assets", "AssetPairs"]


def test_a_market_reads_prices_live_on_every_call():
    kraken = FakeKraken()
    market = _market(kraken)

    market.ticker(["XXBTZEUR"])
    market.ticker(["XXBTZEUR"])

    assert _tickers(kraken) == [("XXBTZEUR",), ("XXBTZEUR",)]


def test_a_tick_reads_the_batchs_prices_in_one_call():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    tick.preload(["XXBTZEUR", "XETHZEUR", "XXBTZEUR"])

    assert tick.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("50000")}
    assert tick.ticker(["XETHZEUR", "XXBTZEUR"]) == {"XETHZEUR": D("2500"), "XXBTZEUR": D("50000")}
    assert _tickers(kraken) == [("XETHZEUR", "XXBTZEUR")]


def test_a_pair_the_preload_missed_is_read_once_and_kept():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))
    tick.preload(["XXBTZEUR"])

    tick.ticker(["XXBTZEUR", "XETHZEUR"])
    tick.ticker(["XETHZEUR"])

    assert _tickers(kraken) == [("XXBTZEUR",), ("XETHZEUR",)]


def test_a_failed_read_is_none_and_the_next_call_asks_again():
    kraken = FakeKraken()
    kraken.down = True
    tick = TickMarket(_market(kraken))
    tick.preload(["XXBTZEUR"])

    assert tick.ticker(["XXBTZEUR"]) is None
    kraken.down = False
    assert tick.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("50000")}
    assert len(_tickers(kraken)) == 3


def test_nothing_is_read_for_no_pairs():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    tick.preload([])

    assert tick.ticker([]) == {}
    assert _tickers(kraken) == []


def test_a_tick_reads_names_and_pairs_through_its_source():
    kraken = FakeKraken()
    tick = TickMarket(_market(kraken))

    assert dict(tick.assets()) == {"XXBT": "XBT", "ZEUR": "EUR"}
    assert dict(tick.asset_pairs()) == {}
