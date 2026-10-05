"""The executor with sells allowed, driven directly. `core/rebalance.py` decides when to
call it; here the decision is a plain function, so the sending is tested on its own."""

import base64
from decimal import Decimal

import pytest

from core.db.orders import list_orders
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import latest_snapshot, list_evaluations
from core.db.types import Operation, OrderReason, Trigger
from core.db.users import save_credentials
from core.execution import EvaluationStatus, LegStatus, evaluate, invest
from engine.types import Side
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
HALF_HALF = (("XBT", "XXBTZEUR", "50"), ("ETH", "XETHZEUR", "50"))
# At 50 000 and 2 500: 700 EUR of XBT and 300 EUR of ETH, no cash. Against 50/50 the
# plan sells 200 EUR of XBT and buys 200 EUR of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}


@pytest.fixture
def ready(app_context, db_session, make_user, fake_kraken):
    def _ready(weights=HALF_HALF, balance=DRIFTED):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        for asset, pair, pct in weights:
            upsert_asset(db_session, user.id, asset=asset, pair=pair, target_pct=D(pct))
        sealed = app_context.cipher.seal(user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(
            db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
        )
        fake_kraken.balance = dict(balance)
        return user

    return _ready


def _send(planned, log):
    return None


def _rebalance(app_context, user, decide=_send):
    return evaluate(
        app_context,
        user.id,
        allow_sells=True,
        reason=OrderReason.REBALANCE,
        decide=decide,
        operation=Operation.REBALANCE,
        trigger=Trigger.API,
    )


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_the_sell_goes_first_and_its_proceeds_fund_the_buy(app_context, fake_kraken, ready):
    """The sell raises 200 and pays 0.80 of fee: the buy shrinks from 200 to 199.20."""
    user = ready()

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.DONE
    sell, buy = _sent(fake_kraken)
    assert (sell["type"], sell["pair"], D(sell["volume"]), sell["oflags"]) == (
        "sell",
        "XXBTZEUR",
        D("0.004"),
        "fciq",
    )
    assert (buy["type"], buy["pair"], D(buy["volume"]), buy["oflags"]) == (
        "buy",
        "XETHZEUR",
        D("199.2"),
        "viqc,fcib",
    )
    assert [(leg.asset, leg.side, leg.status) for leg in result.legs] == [
        ("XBT", Side.SELL, LegStatus.FILLED),
        ("ETH", Side.BUY, LegStatus.FILLED),
    ]


def test_the_buy_spends_what_the_ledger_credited_not_what_the_sell_reported(app_context, fake_kraken, ready):
    """The sell reports 200 and a fee of 0.80005. The ledger keeps four places for EUR,
    so it charges 0.8001 and credits 199.1999. A buy of 199.19995 would be refused."""
    user = ready()
    fake_kraken.fee_rate = D("0.00400025")

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.DONE
    _, buy = _sent(fake_kraken)
    assert D(buy["volume"]) == D("199.1999")


def test_a_refused_buy_after_a_filled_sell_is_partial(app_context, db_session, fake_kraken, ready):
    user = ready()

    def refuse_buys(form):
        fake_kraken.add_order_errors = ["EOrder:Insufficient funds"] if form["type"] == "buy" else []

    fake_kraken.on_add_order = refuse_buys

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.PARTIAL
    assert [(leg.asset, leg.status) for leg in result.legs] == [
        ("XBT", LegStatus.FILLED),
        ("ETH", LegStatus.FAILED),
    ]
    assert [e.status for e in list_evaluations(db_session, user.id)] == ["PARTIAL"]


def test_a_rebalance_writes_its_orders_with_its_reason(app_context, db_session, ready):
    user = ready()

    _rebalance(app_context, user)

    orders = {order.asset: order for order in list_orders(db_session, user.id)}
    assert (orders["XBT"].side, orders["XBT"].reason) == (Side.SELL, OrderReason.REBALANCE)
    assert orders["XBT"].requested_fiat == D("200")
    assert orders["XBT"].cost == D("200")
    assert orders["XBT"].fee == D("0.8")
    assert (orders["ETH"].side, orders["ETH"].requested_fiat) == (Side.BUY, D("199.2"))


def test_an_exit_sells_the_whole_balance(app_context, fake_kraken, ready):
    """XBT at 0 % is an exit. 0.0123456789 rounds down to the pair's eight places."""
    user = ready(
        weights=(("XBT", "XXBTZEUR", "0"), ("ETH", "XETHZEUR", "100")),
        balance={"ZEUR": "0", "XXBT": "0.0123456789", "XETH": "0.4"},
    )

    _rebalance(app_context, user)

    sell = next(form for form in _sent(fake_kraken) if form["type"] == "sell")
    assert D(sell["volume"]) == D("0.01234567")


def test_free_cash_above_the_target_is_spent_with_the_proceeds(app_context, fake_kraken, ready):
    """1000 of XBT and 1000 of cash at 50/50 with no cash target: sell 0, buy ETH 1000."""
    user = ready(balance={"ZEUR": "1000", "XXBT": "0.02", "XETH": "0"})

    _rebalance(app_context, user)

    (buy,) = _sent(fake_kraken)
    assert (buy["pair"], D(buy["volume"])) == ("XETHZEUR", D("1000"))


def test_a_refused_sell_leaves_nothing_to_buy_with(app_context, fake_kraken, ready):
    user = ready()

    def refuse_sells(form):
        fake_kraken.add_order_errors = ["EOrder:Insufficient funds"] if form["type"] == "sell" else []

    fake_kraken.on_add_order = refuse_sells

    result = _rebalance(app_context, user)

    legs = {leg.asset: leg for leg in result.legs}
    assert legs["XBT"].status is LegStatus.FAILED
    assert legs["ETH"].status is LegStatus.SKIPPED
    assert "after the sells" in legs["ETH"].note
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell"]


def test_after_an_unknown_answer_to_a_sell_no_buy_is_sent(app_context, fake_kraken, ready):
    user = ready()
    fake_kraken.lose_add_order = "dropped"

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.STOPPED
    assert [leg.status for leg in result.legs] == [LegStatus.PENDING, LegStatus.SKIPPED]
    assert len(_sent(fake_kraken)) == 1


def test_a_decision_that_says_no_sends_nothing_and_is_recorded(app_context, db_session, fake_kraken, ready):
    user = ready()
    seen = []

    def hold(planned, log):
        seen.append(planned)
        log.append("held for approval")
        return EvaluationStatus.PROPOSED

    result = _rebalance(app_context, user, decide=hold)

    assert result.status is EvaluationStatus.PROPOSED
    assert fake_kraken.placed == []
    (planned,) = seen
    assert [(leg.asset, leg.side, leg.amount) for leg in planned.legs] == [
        ("XBT", Side.SELL, D("200")),
        ("ETH", Side.BUY, D("200")),
    ]
    assert planned.legs[0].volume == D("0.004")
    assert planned.free_cash == D("0")
    (evaluation,) = list_evaluations(db_session, user.id)
    assert evaluation.status == "PROPOSED"
    assert "held for approval" in evaluation.log_messages
    assert latest_snapshot(db_session, user.id) is not None


def test_a_users_floor_is_the_minimum_of_a_sell_too(app_context, db_session, fake_kraken, ready):
    user = ready()
    update_settings(db_session, user.id, min_order_fiat=D("250"))

    result = _rebalance(app_context, user)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert {leg.status for leg in result.legs} == {LegStatus.SKIPPED}
    assert fake_kraken.placed == []


def test_investing_never_sells_however_far_a_weight_has_drifted(app_context, fake_kraken, ready):
    user = ready(balance={"ZEUR": "100", "XXBT": "0.014", "XETH": "0.12"})

    invest(app_context, user.id)

    assert {form["type"] for form in _sent(fake_kraken)} == {"buy"}
