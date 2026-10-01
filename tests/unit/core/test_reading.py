from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.reading import PortfolioUnavailable, read_portfolio
from exchange.types import PairMeta

D = Decimal
NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "SOL": "SOL"}


def _pair(name, base, quote):
    return PairMeta(name, name, base, quote, 1, 8, D("0.0001"), D("0.5"), "online")


@dataclass
class Configured:
    asset: str
    pair: str
    target_pct: Decimal


# `None` is what a failed read returns, so the default needs a marker of its own.
DEFAULT = object()


class FakePublic:
    def __init__(self, names=NAMES, pairs=DEFAULT, prices=DEFAULT):
        self.names = names
        self.pairs = {"XETHZEUR": _pair("XETHZEUR", "XETH", "ZEUR")} if pairs is DEFAULT else pairs
        self.prices = {"XXBTZEUR": D("50000"), "XETHZEUR": D("2500")} if prices is DEFAULT else prices
        self.calls = []

    def assets(self):
        self.calls.append("assets")
        return self.names

    def asset_pairs(self):
        self.calls.append("asset_pairs")
        return self.pairs

    def ticker(self, pairs):
        self.calls.append(("ticker", tuple(pairs)))
        return None if self.prices is None else {p: self.prices[p] for p in pairs if p in self.prices}


class FakePrivate:
    def __init__(self, balance):
        self._balance = balance

    def balance(self):
        return self._balance


XBT_60 = [Configured("XBT", "XXBTZEUR", D("60"))]


def test_a_portfolio_is_read_and_valued():
    view = read_portfolio(FakePublic(), FakePrivate({"XXBT": D("0.02"), "ZEUR": D("1000")}), "EUR", XBT_60)

    assert view.managed_value == D("2000")
    assert view.cash == D("1000")


def test_a_managed_asset_is_priced_through_its_stored_pair():
    public = FakePublic()

    read_portfolio(public, FakePrivate({"ZEUR": D("1")}), "EUR", XBT_60)

    assert ("ticker", ("XXBTZEUR",)) in public.calls


def test_pairs_are_only_read_when_something_unmanaged_is_held():
    public = FakePublic()

    read_portfolio(public, FakePrivate({"XXBT": D("1"), "ZEUR": D("1")}), "EUR", XBT_60)

    assert "asset_pairs" not in public.calls


def test_an_unmanaged_asset_is_priced_when_it_has_a_pair_to_the_fiat():
    view = read_portfolio(FakePublic(), FakePrivate({"XETH": D("2"), "ZEUR": D("1")}), "EUR", [])

    eth = next(h for h in view.holdings if h.asset == "ETH")
    assert eth.value == D("5000")


def test_an_unmanaged_asset_with_no_pair_is_shown_unvalued_and_does_not_fail():
    view = read_portfolio(FakePublic(), FakePrivate({"SOL": D("3"), "ZEUR": D("1")}), "EUR", [])

    sol = next(h for h in view.holdings if h.asset == "SOL")
    assert sol.value is None


@pytest.mark.parametrize(
    ("public", "private", "what"),
    [
        (FakePublic(names=None), FakePrivate({}), "asset names"),
        (FakePublic(), FakePrivate(None), "balance"),
        (FakePublic(prices=None), FakePrivate({"ZEUR": D("1")}), "prices"),
        (FakePublic(pairs=None), FakePrivate({"XETH": D("1")}), "asset pairs"),
    ],
)
def test_any_read_that_fails_fails_the_whole_view(public, private, what):
    targets = XBT_60 if what != "asset pairs" else []

    with pytest.raises(PortfolioUnavailable, match=what):
        read_portfolio(public, private, "EUR", targets)


def test_a_managed_asset_with_no_price_fails_the_view_and_names_it():
    public = FakePublic(prices={})

    with pytest.raises(PortfolioUnavailable, match="XBT"):
        read_portfolio(public, FakePrivate({"XXBT": D("1"), "ZEUR": D("1")}), "EUR", XBT_60)
