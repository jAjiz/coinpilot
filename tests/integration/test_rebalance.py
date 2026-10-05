import base64
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal

import pytest

from core.db.orders import list_orders, record_attempt
from core.db.proposals import get_proposal
from core.db.settings import create_settings, update_settings, upsert_asset
from core.db.telemetry import list_evaluations
from core.db.types import OrderReason, ProposalStatus, Trigger
from core.db.users import save_credentials
from core.execution import EvaluationStatus
from core.rebalance import NoProposal, StaleVersion, approve, current, propose, rebalance_now, withdraw
from engine.types import Side
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
# 700 EUR of XBT and 300 EUR of ETH against 50/50: sell 200 of XBT, buy 200 of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}
ON_TARGET = {"ZEUR": "0", "XXBT": "0.01", "XETH": "0.2"}


@pytest.fixture
def user(app_context, db_session, make_user, fake_kraken):
    person = make_user()
    create_settings(db_session, person.id, fiat="EUR")
    upsert_asset(db_session, person.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
    upsert_asset(db_session, person.id, asset="ETH", pair="XETHZEUR", target_pct=D("50"))
    sealed = app_context.cipher.seal(person.id, Credentials("TEST-KEY", SECRET))
    save_credentials(
        db_session, person.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
    )
    fake_kraken.balance = dict(DRIFTED)
    return person


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def _legs(state):
    return [(leg["asset"], leg["side"], leg["amount_fiat"]) for leg in state.plan["legs"]]


def test_a_rebalance_is_proposed_and_nothing_is_sent(app_context, db_session, fake_kraken, user):
    result = propose(app_context, user.id)

    assert result.evaluation.status is EvaluationStatus.PROPOSED
    assert (result.proposal.version, result.proposal.status, result.proposal.trigger) == (1, "LIVE", "MANUAL")
    assert _legs(result.proposal) == [("XBT", "sell", "200"), ("ETH", "buy", "200")]
    assert fake_kraken.placed == []
    assert list_orders(db_session, user.id) == []
    assert [e.status for e in list_evaluations(db_session, user.id)] == ["PROPOSED"]


def test_proposing_with_automatic_rebalancing_on_still_sends_nothing(
    app_context, db_session, fake_kraken, user
):
    update_settings(db_session, user.id, auto_rebalance_enabled=True)

    propose(app_context, user.id)

    assert fake_kraken.placed == []


def test_proposing_again_on_the_same_plan_keeps_the_version(app_context, user):
    propose(app_context, user.id)

    again = propose(app_context, user.id)

    assert again.proposal.version == 1


def test_a_move_within_the_minimum_keeps_the_version_and_the_plan_the_user_read(
    app_context, db_session, fake_kraken, user
):
    """A floor of 10. XBT at 50 100 moves each leg by 0.70: not material."""
    update_settings(db_session, user.id, min_order_fiat=D("10"))
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "50100"

    again = propose(app_context, user.id)

    assert again.proposal.version == 1
    assert _legs(again.proposal) == [("XBT", "sell", "200"), ("ETH", "buy", "200")]


def test_a_material_move_is_a_new_version(app_context, fake_kraken, user):
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    again = propose(app_context, user.id)

    assert again.proposal.version == 2
    assert _legs(again.proposal) == [("XBT", "sell", "207"), ("ETH", "buy", "207")]


def test_a_proposal_is_withdrawn_when_the_drift_is_gone(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)
    fake_kraken.balance = dict(ON_TARGET)

    result = propose(app_context, user.id)

    assert result.evaluation.status is EvaluationStatus.NOTHING_TO_DO
    assert result.proposal is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN


def test_a_proposal_after_a_withdrawn_one_takes_the_next_version(app_context, user):
    propose(app_context, user.id)
    withdraw(app_context, user.id)

    again = propose(app_context, user.id)

    assert again.proposal.version == 2


def test_withdrawing_says_whether_there_was_a_live_proposal(app_context, user):
    assert withdraw(app_context, user.id) is False
    propose(app_context, user.id)

    assert withdraw(app_context, user.id) is True
    assert current(app_context, user.id) is None
    assert withdraw(app_context, user.id) is False


def test_approving_the_live_version_executes_it(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.DONE
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    orders = list_orders(db_session, user.id)
    assert {order.reason for order in orders} == {OrderReason.REBALANCE}
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTED
    assert result.proposal is None


def test_a_proposal_after_an_executed_one_takes_the_next_version(app_context, fake_kraken, user):
    propose(app_context, user.id)
    approve(app_context, user.id, 1)

    again = propose(app_context, user.id)

    assert again.proposal.version == 2


def test_an_approval_of_another_version_is_refused_before_kraken_is_read(
    app_context, db_session, fake_kraken, user
):
    propose(app_context, user.id)
    fake_kraken.calls.clear()

    with pytest.raises(StaleVersion) as refused:
        approve(app_context, user.id, 2)

    assert refused.value.current.version == 1
    assert fake_kraken.calls == []
    assert len(list_evaluations(db_session, user.id)) == 1


def test_there_is_nothing_to_approve_without_a_live_proposal(app_context, fake_kraken, user):
    with pytest.raises(NoProposal):
        approve(app_context, user.id, 1)

    assert fake_kraken.calls == []


def test_an_approval_that_meets_a_material_change_sends_nothing_and_offers_the_new_version(
    app_context, db_session, fake_kraken, user
):
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.SUPERSEDED
    assert result.proposal.version == 2
    assert _sent(fake_kraken) == []
    assert list_orders(db_session, user.id) == []


def test_an_approval_within_the_minimum_executes_todays_amounts(app_context, db_session, fake_kraken, user):
    """Approved at 200; at 50 100 the sell is 200.70, and that is what is sent."""
    update_settings(db_session, user.id, min_order_fiat=D("10"))
    propose(app_context, user.id)
    fake_kraken.prices["XXBTZEUR"] = "50100"

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.DONE
    sell = next(order for order in list_orders(db_session, user.id) if order.side == Side.SELL)
    assert sell.requested_fiat == D("200.7")


def test_an_approval_that_finds_the_drift_gone_withdraws_the_proposal(
    app_context, db_session, fake_kraken, user
):
    propose(app_context, user.id)
    fake_kraken.balance = dict(ON_TARGET)

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.SUPERSEDED
    assert result.proposal is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert _sent(fake_kraken) == []
    assert result.evaluation.messages[-1] == "the drift is below the threshold; the proposal was withdrawn"


def test_an_approval_that_raises_while_executing_still_leaves_the_proposal_executed(
    app_context, db_session, monkeypatch, user
):
    propose(app_context, user.id)

    def broken(*args, **kwargs):
        raise RuntimeError("lost mid-execution")

    monkeypatch.setattr("core.execution._send_all", broken)

    with pytest.raises(RuntimeError):
        approve(app_context, user.id, 1)

    db_session.expire_all()
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTED


def test_an_approval_waits_for_an_unresolved_order(app_context, db_session, fake_kraken, user):
    propose(app_context, user.id)
    record_attempt(
        db_session,
        user.id,
        "unresolved-1",
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("10"),
        attempted_at=app_context.now(),
    )

    result = approve(app_context, user.id, 1)

    assert result.evaluation.status is EvaluationStatus.UNRESOLVED
    assert result.proposal.version == 1
    assert result.proposal.status == "LIVE"
    assert _sent(fake_kraken) == []


def test_a_scheduled_proposal_is_marked_scheduled(app_context, db_session, user):
    result = propose(app_context, user.id, trigger=Trigger.SCHEDULER)

    assert result.proposal.trigger == "SCHEDULED"
    record = list_evaluations(db_session, user.id)[0]
    assert (record.operation, record.trigger) == ("PROPOSE", "SCHEDULER")


def test_an_approval_is_recorded_as_one(app_context, db_session, user):
    propose(app_context, user.id)

    approve(app_context, user.id, 1)

    assert {(e.operation, e.trigger) for e in list_evaluations(db_session, user.id)} == {
        ("PROPOSE", "API"),
        ("APPROVE", "API"),
    }


def test_an_automatic_rebalance_executes_without_an_approval(app_context, db_session, fake_kraken, user):
    update_settings(db_session, user.id, auto_rebalance_enabled=True)

    result = rebalance_now(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    assert {order.reason for order in list_orders(db_session, user.id)} == {OrderReason.REBALANCE}
    assert get_proposal(db_session, user.id) is None
    record = list_evaluations(db_session, user.id)[0]
    assert (record.operation, record.trigger) == ("REBALANCE", "SCHEDULER")


def test_an_automatic_rebalance_withdraws_the_live_proposal_first(app_context, db_session, fake_kraken, user):
    """What executes is today's plan. A proposal left live would offer an approval of
    something already done."""
    update_settings(db_session, user.id, auto_rebalance_enabled=True)
    propose(app_context, user.id)

    result = rebalance_now(app_context, user.id)

    assert result.status is EvaluationStatus.DONE
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert any("proposal version 1 was withdrawn" in message for message in result.messages)


def test_an_automatic_rebalance_sends_nothing_with_automatic_rebalancing_off(
    app_context, db_session, fake_kraken, user
):
    update_settings(db_session, user.id, auto_rebalance_enabled=False)

    result = rebalance_now(app_context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert any("switched off" in message for message in result.messages)
    assert fake_kraken.placed == []
    assert list_orders(db_session, user.id) == []
    record = list_evaluations(db_session, user.id)[0]
    assert (record.operation, record.trigger, record.status) == ("REBALANCE", "SCHEDULER", "NOTHING_TO_DO")


def test_switching_it_off_after_the_evaluation_started_stops_the_rebalance(
    app_context, db_session, fake_kraken, user, user_locks
):
    """The setting is read again under the lock, just before anything is sent: a user who
    switched it off after the scheduler chose them is not sold from. The switch lands the
    moment the lock is taken, which is after `rebalance_now` was called."""
    update_settings(db_session, user.id, auto_rebalance_enabled=True)

    @contextmanager
    def switched_off_on_entry(user_id):
        with user_locks(user_id) as taken:
            update_settings(db_session, user_id, auto_rebalance_enabled=False)
            yield taken

    context = replace(app_context, user_lock=switched_off_on_entry)

    result = rebalance_now(context, user.id)

    assert result.status is EvaluationStatus.NOTHING_TO_DO
    assert any("switched off" in message for message in result.messages)
    assert fake_kraken.placed == []
    assert list_orders(db_session, user.id) == []
