from decimal import Decimal

from engine.drift import cash_target_pct, deltas, drifts, target_values
from engine.valuation import value_portfolio

D = Decimal


def _valuation(btc_amount, cash, btc_target):
    return value_portfolio(
        holdings={"BTC": D(btc_amount)},
        prices={"BTC": D("100")},
        targets={"BTC": D(btc_target)},
        cash=D(cash),
    )


def test_cash_target_is_whatever_the_assets_do_not_claim():
    assert cash_target_pct({"BTC": D("60"), "ETH": D("35")}) == D("5")


def test_cash_target_is_zero_when_assets_claim_everything():
    assert cash_target_pct({"BTC": D("60"), "ETH": D("40")}) == D("0")


def test_target_values_are_a_share_of_the_managed_value():
    v = _valuation("1", "100", "50")  # managed value 200

    assert target_values(v, {"BTC": D("50")}) == {"BTC": D("100")}


def test_delta_is_positive_when_the_asset_is_underweight():
    v = _valuation("1", "300", "50")  # BTC 100 of 400, target 200

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("100")}


def test_delta_is_negative_when_the_asset_is_overweight():
    v = _valuation("3", "100", "50")  # BTC 300 of 400, target 200

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("-100")}


def test_drift_is_signed_percentage_points_not_fiat():
    v = _valuation("3", "100", "50")  # BTC weighs 75 %, target 50 %

    assert drifts(v, {"BTC": D("50")}) == {"BTC": D("25")}


def test_a_portfolio_on_target_has_zero_delta_and_zero_drift():
    v = _valuation("2", "200", "50")  # BTC 200 of 400

    assert deltas(v, {"BTC": D("50")}) == {"BTC": D("0")}
    assert drifts(v, {"BTC": D("50")}) == {"BTC": D("0")}
