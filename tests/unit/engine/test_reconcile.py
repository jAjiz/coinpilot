from decimal import Decimal

from engine.reconcile import reconcile
from engine.types import ZERO, CashPolicy, Leg, Policy, Side

D = Decimal

PRICES = {"BTC": D("100"), "ETH": D("10")}


def _buy(asset: str, amount: Decimal) -> Leg:
    return Leg(asset=asset, side=Side.BUY, amount_fiat=amount)


def _sell(asset: str, amount: Decimal) -> Leg:
    return Leg(asset=asset, side=Side.SELL, amount_fiat=amount)


def _policy(
    *,
    allow_sells: bool,
    cash_policy: CashPolicy = CashPolicy.PRORATA,
    min_drift_pct: Decimal = ZERO,
    min_order_fiat: Decimal = ZERO,
) -> Policy:
    return Policy(
        allow_sells=allow_sells,
        cash_policy=cash_policy,
        min_drift_pct=min_drift_pct,
        min_order_fiat=min_order_fiat,
    )


def test_invest_spends_the_cash_and_never_sells():
    plan = reconcile(
        holdings={"BTC": D("1")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("100"),
        policy=_policy(allow_sells=False),
    )

    assert all(leg.side is Side.BUY for leg in plan.legs)
    assert sum(leg.amount_fiat for leg in plan.legs) == D("100")


def test_invest_with_no_spare_cash_produces_an_empty_plan():
    plan = reconcile(
        holdings={"BTC": D("1")},
        prices=PRICES,
        targets={"BTC": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=False),
    )

    assert plan.is_empty


def test_invest_reduce_drift_puts_the_cash_where_the_gap_is():
    plan = reconcile(
        holdings={"BTC": D("2"), "ETH": D("0")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("100"),
        policy=_policy(allow_sells=False, cash_policy=CashPolicy.REDUCE_DRIFT),
    )

    assert plan.legs == (_buy("ETH", D("100")),)


def test_rebalance_sells_the_overweight_and_buys_the_underweight():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )  # managed 400: BTC 300, ETH 100, target 200 each

    assert plan.legs == (_sell("BTC", D("100")), _buy("ETH", D("100")))


def test_rebalance_puts_sells_before_buys():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    sides = [leg.side for leg in plan.legs]
    assert sides == [Side.SELL, Side.BUY]


def test_an_asset_inside_the_drift_band_produces_no_leg():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True, min_drift_pct=D("30")),
    )  # each drifts 25 points, which is inside a 30-point band

    assert plan.is_empty


def test_a_leg_below_the_minimum_order_is_dropped():
    plan = reconcile(
        holdings={"BTC": D("3"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True, min_order_fiat=D("150")),
    )  # both legs are worth 100

    assert plan.is_empty


def test_a_target_of_zero_asks_to_exit_the_position():
    plan = reconcile(
        holdings={"BTC": D("1"), "ETH": D("10")},
        prices=PRICES,
        targets={"BTC": D("100"), "ETH": D("0")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )  # managed 200: ETH must go to zero

    assert _sell("ETH", D("100")) in plan.legs


def test_an_unconfigured_holding_is_never_touched():
    plan = reconcile(
        holdings={"BTC": D("1"), "DOGE": D("1000")},
        prices={"BTC": D("100"), "DOGE": D("5")},
        targets={"BTC": D("100")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    assert all(leg.asset != "DOGE" for leg in plan.legs)


def test_a_portfolio_on_target_produces_an_empty_plan():
    plan = reconcile(
        holdings={"BTC": D("2"), "ETH": D("20")},
        prices=PRICES,
        targets={"BTC": D("50"), "ETH": D("50")},
        cash=D("0"),
        policy=_policy(allow_sells=True),
    )

    assert plan.is_empty
