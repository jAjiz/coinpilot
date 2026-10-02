import base64
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from core.db.orders import get_by_cl_ord_id, list_orders
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import latest_snapshot, list_evaluations
from core.db.types import OrderStatus
from core.db.users import save_credentials
from core.execution import (
    EvaluationBusy,
    EvaluationStatus,
    LegStatus,
    NotReady,
    invest,
)
from core.settlement import ABSENCE_GRACE
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
XBT_ETH = (("XBT", "XXBTZEUR", "60"), ("ETH", "XETHZEUR", "40"))


@pytest.fixture
def ready(app_context, db_session, make_user, fake_kraken):
    """A user with EUR, the weights given, a sealed key, and 1000 EUR of free cash."""

    def _ready(weights=XBT_ETH, cash="1000"):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        for asset, pair, pct in weights:
            upsert_asset(db_session, user.id, asset=asset, pair=pair, target_pct=D(pct))
        sealed = app_context.cipher.seal(user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(
            db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
        )
        fake_kraken.balance = {"ZEUR": cash}
        return user

    return _ready


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_free_cash_is_invested_pro_rata_in_fiat(app_context, fake_kraken, ready):
    user = ready()

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert [(leg.asset, leg.status) for leg in result.legs] == [
        ("ETH", LegStatus.FILLED),
        ("XBT", LegStatus.FILLED),
    ]
    forms = {form["pair"]: form for form in _sent(fake_kraken)}
    assert D(forms["XXBTZEUR"]["volume"]) == D("600")
    assert D(forms["XETHZEUR"]["volume"]) == D("400")
    assert {form["oflags"] for form in forms.values()} == {"viqc,fcib"}
    assert {form["type"] for form in forms.values()} == {"buy"}


def test_every_order_is_in_the_ledger_with_what_it_cost(app_context, db_session, fake_kraken, ready):
    user = ready()

    invest(app_context, user.id)

    orders = {order.asset: order for order in list_orders(db_session, user.id)}
    assert orders["XBT"].status == OrderStatus.FILLED
    assert orders["XBT"].requested_fiat == D("600")
    assert orders["XBT"].cost == D("600")
    assert orders["XBT"].txid is not None
    assert orders["XBT"].attempted_at == app_context.now()


def test_the_evaluation_and_a_snapshot_are_recorded(app_context, db_session, ready):
    user = ready()

    invest(app_context, user.id)

    (evaluation,) = list_evaluations(db_session, user.id)
    assert evaluation.status == "DONE"
    assert "XBT" in evaluation.log_messages
    assert latest_snapshot(db_session, user.id).cash == D("1000")


def test_the_cash_target_is_kept(app_context, fake_kraken, ready):
    """XBT at 50 % leaves a 50 % cash target: half of 1000 stays as cash."""
    user = ready(weights=(("XBT", "XXBTZEUR", "50"),))

    invest(app_context, user.id)

    (form,) = _sent(fake_kraken)
    assert D(form["volume"]) == D("500")


def test_drift_policy_spends_on_what_is_furthest_behind(app_context, db_session, fake_kraken, ready):
    """600 EUR of XBT and 400 EUR of cash at 50/50: all of the cash goes to ETH."""
    user = ready(weights=(("XBT", "XXBTZEUR", "50"), ("ETH", "XETHZEUR", "50")), cash="400")
    fake_kraken.balance = {"ZEUR": "400", "XXBT": "0.012"}
    update_settings(db_session, user.id, cash_rebalance_enabled=True)

    invest(app_context, user.id)

    (form,) = _sent(fake_kraken)
    assert (form["pair"], D(form["volume"])) == ("XETHZEUR", D("400"))


def test_no_free_cash_is_nothing_to_do(app_context, fake_kraken, ready):
    user = ready(cash="0")

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert fake_kraken.placed == []


def test_a_leg_under_krakens_minimum_is_skipped_and_the_rest_is_sent(app_context, fake_kraken, ready):
    """6 EUR at 60/40: XBT gets 3.60, under 0.0001 XBT at 50 000 = 5. ETH gets 2.40, over 0.5."""
    user = ready(cash="6")

    result = invest(app_context, user.id)

    legs = {leg.asset: leg for leg in result.legs}
    assert legs["XBT"].status is LegStatus.SKIPPED
    assert legs["XBT"].minimum_fiat == D("5")
    assert "below the minimum" in legs["XBT"].note
    assert legs["ETH"].status is LegStatus.FILLED
    assert [form["pair"] for form in _sent(fake_kraken)] == ["XETHZEUR"]


def test_a_floor_of_the_users_own_skips_what_kraken_would_take(app_context, db_session, fake_kraken, ready):
    user = ready(cash="15")
    update_settings(db_session, user.id, min_order_fiat=D("10"))

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert {leg.status for leg in result.legs} == {LegStatus.SKIPPED}
    assert fake_kraken.placed == []


def test_a_refused_leg_fails_with_krakens_code_and_the_others_are_still_sent(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.add_order_errors = ["EOrder:Insufficient funds"]

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.PARTIAL
    assert {leg.status for leg in result.legs} == {LegStatus.FAILED}
    assert {leg.error for leg in result.legs} == {"EOrder:Insufficient funds"}
    assert len(_sent(fake_kraken)) == 2


def test_after_an_unknown_answer_no_further_leg_is_sent(app_context, db_session, fake_kraken, ready):
    user = ready()
    fake_kraken.lose_add_order = "dropped"

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.STOPPED
    assert [leg.status for leg in result.legs] == [LegStatus.PENDING, LegStatus.SKIPPED]
    assert len(_sent(fake_kraken)) == 1
    (order,) = list_orders(db_session, user.id)
    assert (order.status, order.txid) == (OrderStatus.PENDING, None)


def test_the_next_investment_waits_out_the_grace_then_retries_an_order_that_never_arrived(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "dropped"
    invest(app_context, user.id)
    fake_kraken.lose_add_order = None

    soon = invest(app_context, user.id)
    later = invest(replace(app_context, now=lambda: app_context.now() + ABSENCE_GRACE), user.id)

    assert soon.status is EvaluationStatus.UNRESOLVED
    assert later.status is EvaluationStatus.DONE
    assert sorted(o.status for o in list_orders(db_session, user.id)) == [
        OrderStatus.FAILED,
        OrderStatus.FILLED,
        OrderStatus.FILLED,
    ]


def test_an_order_that_executed_but_whose_answer_was_lost_is_adopted_not_repeated(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "executed"
    invest(app_context, user.id)
    fake_kraken.lose_add_order = None
    fake_kraken.balance = {"ZEUR": "0"}

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    (order,) = list_orders(db_session, user.id)
    assert order.status == OrderStatus.FILLED
    assert len(_sent(fake_kraken)) == 1


def test_an_order_not_yet_filled_is_read_again_by_its_txid(app_context, db_session, fake_kraken, ready):
    user = ready(weights=(("XBT", "XXBTZEUR", "100"),))
    fake_kraken.fill_status = "open"
    first = invest(app_context, user.id)
    (txid,) = fake_kraken.orders
    fake_kraken.orders[txid].update(status="closed", vol_exec="0.02", cost="1000")
    fake_kraken.balance = {"ZEUR": "0"}

    invest(app_context, user.id)

    assert first.legs[0].status is LegStatus.PENDING
    assert get_by_cl_ord_id(db_session, fake_kraken.orders[txid]["cl_ord_id"]).status == OrderStatus.FILLED


def test_the_attempt_is_committed_before_the_order_is_sent(app_context, db_session, fake_kraken, ready):
    """Spec §9.2: a row still inside an open transaction does not survive the process."""
    user = ready(weights=(("XBT", "XXBTZEUR", "100"),))
    events = []

    @contextmanager
    def sessions():
        with app_context.sessions() as session:
            yield session
        events.append("commit")

    def on_add_order(form):
        row = get_by_cl_ord_id(db_session, form["cl_ord_id"])
        events.append(("AddOrder", None if row is None else row.status))

    fake_kraken.on_add_order = on_add_order
    invest(replace(app_context, sessions=sessions), user.id)

    sent_at = next(i for i, event in enumerate(events) if isinstance(event, tuple))
    assert events[sent_at] == ("AddOrder", OrderStatus.PENDING)
    assert events[sent_at - 1] == "commit"


def test_a_second_evaluation_of_the_same_user_is_refused(app_context, fake_kraken, ready, user_locks):
    user = ready()
    user_locks.held.add(user.id)

    with pytest.raises(EvaluationBusy):
        invest(app_context, user.id)
    assert fake_kraken.placed == []


def test_settings_come_first(app_context, make_user):
    with pytest.raises(NotReady, match="fiat"):
        invest(app_context, make_user().id)


def test_a_key_comes_next(app_context, db_session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(NotReady, match="key"):
        invest(app_context, user.id)


def test_an_unreadable_balance_sends_nothing_and_is_recorded(app_context, db_session, fake_kraken, ready):
    user = ready()
    fake_kraken.down.add("Balance")

    result = invest(app_context, user.id)

    assert result.status is EvaluationStatus.KRAKEN_UNAVAILABLE
    assert fake_kraken.placed == []
    assert list_evaluations(db_session, user.id)[0].status == "KRAKEN_UNAVAILABLE"


def test_a_preview_has_kraken_validate_and_records_nothing(app_context, db_session, fake_kraken, ready):
    user = ready()

    result = invest(app_context, user.id, preview=True)

    assert result.status is EvaluationStatus.PREVIEW
    assert {leg.status for leg in result.legs} == {LegStatus.VALIDATED}
    assert {form["validate"] for form in fake_kraken.placed} == {"true"}
    assert list_orders(db_session, user.id) == []
    assert list_evaluations(db_session, user.id) == []
    assert latest_snapshot(db_session, user.id) is None


def test_a_preview_shows_what_kraken_would_refuse(app_context, fake_kraken, ready):
    user = ready()
    fake_kraken.add_order_errors = ["EOrder:Insufficient funds"]

    result = invest(app_context, user.id, preview=True)

    assert {(leg.status, leg.error) for leg in result.legs} == {
        (LegStatus.REJECTED, "EOrder:Insufficient funds")
    }


def test_a_preview_with_something_unresolved_says_so_and_resolves_nothing(
    app_context, db_session, fake_kraken, ready
):
    user = ready()
    fake_kraken.lose_add_order = "dropped"
    invest(app_context, user.id)
    fake_kraken.placed.clear()

    result = invest(
        replace(app_context, now=lambda: app_context.now() + timedelta(days=1)), user.id, preview=True
    )

    assert result.status is EvaluationStatus.UNRESOLVED
    assert fake_kraken.placed == []
    (order,) = list_orders(db_session, user.id)
    assert order.status == OrderStatus.PENDING
