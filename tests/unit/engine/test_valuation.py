from decimal import Decimal

import pytest

from engine.types import UnpricedAsset
from engine.valuation import value_portfolio

D = Decimal


def test_values_managed_assets_and_cash():
    v = value_portfolio(
        holdings={"BTC": D("2"), "ETH": D("10")},
        prices={"BTC": D("100"), "ETH": D("10")},
        targets={"BTC": D("60"), "ETH": D("30")},
        cash=D("100"),
    )

    assert v.asset_values == {"BTC": D("200"), "ETH": D("100")}
    assert v.cash == D("100")
    assert v.managed_value == D("400")


def test_weights_are_percentages_of_managed_value():
    v = value_portfolio(
        holdings={"BTC": D("2")},
        prices={"BTC": D("100")},
        targets={"BTC": D("80")},
        cash=D("300"),
    )

    assert v.weights == {"BTC": D("40")}
    assert v.cash_weight == D("60")


def test_unconfigured_holdings_are_ignored_entirely():
    """An asset with no target row is not managed: it never enters the denominator."""
    v = value_portfolio(
        holdings={"BTC": D("1"), "DOGE": D("1000")},
        prices={"BTC": D("100"), "DOGE": D("5")},
        targets={"BTC": D("100")},
        cash=D("0"),
    )

    assert "DOGE" not in v.asset_values
    assert v.managed_value == D("100")
    assert v.weights == {"BTC": D("100")}


def test_a_target_with_no_holding_is_valued_at_zero():
    v = value_portfolio(
        holdings={},
        prices={"BTC": D("100")},
        targets={"BTC": D("50")},
        cash=D("100"),
    )

    assert v.asset_values == {"BTC": D("0")}
    assert v.managed_value == D("100")


def test_managed_asset_without_a_price_raises():
    with pytest.raises(UnpricedAsset) as excinfo:
        value_portfolio(
            holdings={"BTC": D("1")},
            prices={},
            targets={"BTC": D("100")},
            cash=D("0"),
        )

    assert excinfo.value.asset == "BTC"


def test_empty_portfolio_has_zero_weights_and_does_not_divide_by_zero():
    v = value_portfolio(
        holdings={},
        prices={"BTC": D("100")},
        targets={"BTC": D("100")},
        cash=D("0"),
    )

    assert v.managed_value == D("0")
    assert v.weights == {"BTC": D("0")}
    assert v.cash_weight == D("0")
