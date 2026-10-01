from decimal import Decimal

import pytest

from core.portfolio import build_view
from engine.types import UnpricedAsset

D = Decimal
NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "SOL": "SOL"}
PRICES = {"XBT": D("50000"), "ETH": D("2500"), "SOL": D("100")}


def _view(balances, targets, prices=PRICES):
    return build_view(balances, NAMES, "EUR", targets, prices)


def _holding(view, asset):
    return next(h for h in view.holdings if h.asset == asset)


def test_an_internal_name_is_shown_under_its_short_name():
    view = _view({"XXBT": D("0.02"), "ZEUR": D("1000")}, {"XBT": D("50")})

    xbt = _holding(view, "XBT")
    assert xbt.amount == D("0.02")
    assert xbt.value == D("1000")
    assert xbt.managed is True
    assert xbt.weight_pct == D("50")


def test_a_rewards_balance_counts_as_holdings_of_its_asset():
    """Kraken trades `XBT.F` through `XBT`. Leaving it out would understate the weight."""
    view = _view({"XXBT": D("0.01"), "XBT.F": D("0.01"), "ZEUR": D("1000")}, {"XBT": D("50")})

    assert _holding(view, "XBT").amount == D("0.02")
    assert view.managed_value == D("2000")


def test_a_staked_balance_is_shown_locked_and_counts_for_nothing():
    view = _view({"ZEUR": D("100"), "DOT.S": D("5")}, {})

    dot = _holding(view, "DOT.S")
    assert dot.locked is True
    assert dot.managed is False
    assert dot.value is None
    assert view.managed_value == D("100")


def test_the_fiat_is_cash_and_not_a_holding():
    view = _view({"ZEUR": D("250.5")}, {})

    assert view.cash == D("250.5")
    assert all(h.asset != "EUR" for h in view.holdings)


def test_fiat_on_hold_is_not_spendable_cash():
    view = _view({"ZEUR": D("100"), "EUR.HOLD": D("40")}, {})

    assert view.cash == D("100")
    assert _holding(view, "EUR.HOLD").locked is True


def test_an_unmanaged_asset_is_shown_valued_but_outside_the_denominator():
    view = _view({"ZEUR": D("100"), "XETH": D("1")}, {})

    eth = _holding(view, "ETH")
    assert eth.managed is False
    assert eth.value == D("2500")
    assert eth.weight_pct is None
    assert view.managed_value == D("100")


def test_an_unmanaged_asset_with_no_price_is_shown_unvalued():
    view = _view({"ZEUR": D("100"), "XETH": D("1")}, {}, prices={})

    assert _holding(view, "ETH").value is None


def test_an_unmanaged_asset_with_nothing_left_is_not_shown():
    """Kraken keeps reporting a zero for every asset the account ever held."""
    view = _view({"ZEUR": D("100"), "XETH": D("0")}, {})

    assert all(h.asset != "ETH" for h in view.holdings)


def test_a_managed_asset_with_nothing_held_is_still_shown():
    view = _view({"ZEUR": D("100")}, {"SOL": D("10")})

    sol = _holding(view, "SOL")
    assert sol.amount == D("0")
    assert sol.weight_pct == D("0")


def test_a_managed_asset_with_no_price_raises():
    """Every weight would be wrong. The caller records nothing instead."""
    with pytest.raises(UnpricedAsset):
        _view({"ZEUR": D("100"), "XXBT": D("1")}, {"XBT": D("50")}, prices={})


def test_the_cash_target_is_what_the_weights_leave():
    view = _view({"ZEUR": D("100")}, {"XBT": D("60"), "SOL": D("35")})

    assert view.cash_target_pct == D("5")


def test_an_empty_account_has_no_value_and_no_weights():
    view = _view({}, {"XBT": D("50")})

    assert view.managed_value == D("0")
    assert _holding(view, "XBT").weight_pct == D("0")


def test_the_snapshot_holds_strings_never_floats():
    """JSON has no decimal type. A float here loses money silently."""
    view = _view({"XXBT": D("0.00000001"), "ZEUR": D("1000"), "DOT.S": D("5")}, {"XBT": D("50")})
    snapshot = view.snapshot_json()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        else:
            assert value is None or isinstance(value, (str, bool))

    walk(snapshot)
    assert snapshot["assets"]["XBT"]["amount"] == "0.00000001"


def test_snapshot_amounts_carry_no_trailing_zeros():
    """Kraken's strings carry padding (`74232.30000`, `0.0484176100`) and their product
    carries both. One amount is written one way, as `total_value` and `cash` already are."""
    view = _view(
        {"XXBT": D("0.0484176100"), "XETH": D("0.0000596879"), "ZEUR": D("0")},
        {"XBT": D("100")},
        {"XBT": D("74232.30000"), "ETH": D("2384.95000")},
    )
    assets = view.snapshot_json()["assets"]

    assert assets["XBT"] == {**assets["XBT"], "amount": "0.04841761", "price": "74232.3"}
    assert assets["XBT"]["value"] == "3594.150550803"
    assert assets["ETH"]["value"] == "0.142352657105"


def test_a_whole_amount_is_not_written_in_scientific_notation():
    """`Decimal("100").normalize()` is `1E+2`."""
    view = _view({"XXBT": D("2.00"), "ZEUR": D("0")}, {"XBT": D("100")}, {"XBT": D("50.00")})

    assert view.snapshot_json()["assets"]["XBT"]["value"] == "100"
