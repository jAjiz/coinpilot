from decimal import Decimal

from engine.allocation import allocate_prorata, allocate_reduce_drift, investable_cash
from engine.valuation import value_portfolio

D = Decimal


def test_investable_cash_is_what_sits_above_the_cash_target():
    v = value_portfolio(
        holdings={"BTC": D("1")},
        prices={"BTC": D("100")},
        targets={"BTC": D("90")},
        cash=D("100"),
    )  # managed value 200, cash target 10 % = 20

    assert investable_cash(v, {"BTC": D("90")}) == D("80")


def test_investable_cash_is_never_negative():
    v = value_portfolio(
        holdings={"BTC": D("9")},
        prices={"BTC": D("100")},
        targets={"BTC": D("50")},
        cash=D("100"),
    )  # cash target is 50 % of 1000 = 500, cash is 100

    assert investable_cash(v, {"BTC": D("50")}) == D("0")


def test_prorata_splits_by_target_weight():
    result = allocate_prorata(D("100"), {"BTC": D("60"), "ETH": D("20")})

    assert result == {"BTC": D("75"), "ETH": D("25")}


def test_prorata_ignores_drift_and_buys_an_overweight_asset_anyway():
    """This is the difference between the two policies, not an oversight."""
    result = allocate_prorata(D("100"), {"BTC": D("50"), "ETH": D("50")})

    assert result == {"BTC": D("50"), "ETH": D("50")}


def test_prorata_skips_assets_targeted_at_zero():
    result = allocate_prorata(D("100"), {"BTC": D("100"), "ETH": D("0")})

    assert result == {"BTC": D("100")}


def test_prorata_of_nothing_is_nothing():
    assert allocate_prorata(D("0"), {"BTC": D("100")}) == {}
    assert allocate_prorata(D("-5"), {"BTC": D("100")}) == {}


def test_reduce_drift_fills_the_most_underweight_first():
    asset_deltas = {"BTC": D("30"), "ETH": D("90")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"ETH": D("90"), "BTC": D("10")}


def test_reduce_drift_closes_the_gap_first_then_spreads_what_is_left():
    """An overweight asset gets nothing until every shortfall is closed.

    Once they are closed the portfolio is on target, so the leftover goes in by target
    weight rather than sitting idle — which is why BTC receives something here despite
    starting overweight.
    """
    asset_deltas = {"BTC": D("-50"), "ETH": D("40")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"ETH": D("70"), "BTC": D("30")}


def test_reduce_drift_splits_the_leftover_pro_rata_instead_of_leaving_it_idle():
    asset_deltas = {"BTC": D("10"), "ETH": D("10")}

    result = allocate_reduce_drift(D("100"), asset_deltas, {"BTC": D("60"), "ETH": D("40")})

    assert result == {"BTC": D("58"), "ETH": D("42")}


def test_reduce_drift_breaks_ties_on_asset_code_so_the_result_is_deterministic():
    asset_deltas = {"ETH": D("50"), "BTC": D("50")}

    result = allocate_reduce_drift(D("50"), asset_deltas, {"BTC": D("50"), "ETH": D("50")})

    assert result == {"BTC": D("50")}


def test_reduce_drift_of_nothing_is_nothing():
    assert allocate_reduce_drift(D("0"), {"BTC": D("10")}, {"BTC": D("100")}) == {}
