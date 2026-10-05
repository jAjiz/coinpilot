import base64
import logging
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import core.scheduler as scheduler_module
from api.app import create_app
from core.config import SchedulerConfig
from core.db.orders import record_attempt
from core.db.proposals import get_proposal
from core.db.settings import create_settings, get_settings, update_settings, upsert_asset
from core.db.telemetry import list_evaluations, start_evaluation
from core.db.types import OrderReason, ProposalStatus
from core.db.users import save_credentials
from core.rebalance import propose
from core.schedule import INVEST, next_run
from core.scheduler import Scheduler, TickReport
from engine.types import Side
from exchange.types import Credentials

D = Decimal
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
# 700 EUR of XBT and 300 EUR of ETH against 50/50: sell 200 of XBT, buy 200 of ETH.
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}
MINUTE = timedelta(minutes=1)


def _with(context, **changes):
    """The context with scheduler settings changed. One worker: the test's session is not thread-safe."""
    settings = replace(SchedulerConfig(workers=1), **changes)
    return replace(context, config=replace(context.config, scheduler=settings))


@pytest.fixture
def context(app_context):
    return _with(app_context)


@pytest.fixture
def scheduler(context):
    return Scheduler(context)


@pytest.fixture
def now(app_context):
    return app_context.now()


@pytest.fixture
def account(app_context, db_session, make_user, fake_kraken):
    """A user ready to be evaluated: EUR, XBT and ETH at 50 % each, and a sealed key.

    `key_owner` seals the key for another id, so it does not open for this user.
    """

    def _account(balance=DRIFTED, key_owner=None, **settings):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        upsert_asset(db_session, user.id, asset="XBT", pair="XXBTZEUR", target_pct=D("50"))
        upsert_asset(db_session, user.id, asset="ETH", pair="XETHZEUR", target_pct=D("50"))
        sealed = app_context.cipher.seal(key_owner or user.id, Credentials("TEST-KEY", SECRET))
        save_credentials(
            db_session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, app_context.now()
        )
        if settings:
            update_settings(db_session, user.id, **settings)
        fake_kraken.balance = dict(balance)
        return user

    return _account


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def _ours(caplog):
    """The scheduler's own records: the Kraken client logs each failed call as well."""
    return [record for record in caplog.records if record.name == "coinpilot.scheduler"]


def _unresolved(db_session, user, now):
    """An order attempted a moment ago whose answer never came back."""
    record_attempt(
        db_session,
        user.id,
        f"unresolved-{user.id.hex[:8]}",
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("10"),
        attempted_at=now,
    )


def test_a_due_investment_is_sent_and_its_next_run_moves_forward(
    scheduler, context, db_session, fake_kraken, account, now
):
    user = account(balance={"ZEUR": "1000"}, invest_cash_enabled=True, next_invest_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report == TickReport(ran=True, users=1, swept=True)
    assert {form["type"] for form in _sent(fake_kraken)} == {"buy"}
    record = list_evaluations(db_session, user.id)[0]
    assert (record.status, record.operation, record.trigger) == ("DONE", "INVEST", "SCHEDULER")
    settings = get_settings(db_session, user.id)
    assert settings.next_invest_at > now
    assert settings.next_invest_at == next_run(settings, INVEST, now, context.config.scheduler)


def test_a_user_not_yet_due_is_left_alone(scheduler, fake_kraken, account, now):
    account(next_rebalance_at=now + MINUTE)

    report = scheduler.tick(now)

    assert report.users == 0
    assert "Balance" not in fake_kraken.calls


def test_a_scheduled_rebalance_only_proposes_while_automatic_rebalancing_is_off(
    scheduler, db_session, fake_kraken, account, now
):
    user = account(next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert _sent(fake_kraken) == []
    proposal = get_proposal(db_session, user.id)
    assert (proposal.status, proposal.trigger, proposal.version) == ("LIVE", "SCHEDULED", 1)
    assert list_evaluations(db_session, user.id)[0].operation == "PROPOSE"


def test_automatic_rebalancing_executes_and_withdraws_the_live_proposal(
    app_context, scheduler, db_session, fake_kraken, account, now
):
    user = account()
    propose(app_context, user.id)
    update_settings(db_session, user.id, auto_rebalance_enabled=True, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert [form["type"] for form in _sent(fake_kraken)] == ["sell", "buy"]
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN
    assert {e.operation for e in list_evaluations(db_session, user.id)} == {"PROPOSE", "REBALANCE"}


def test_when_both_are_due_the_investment_runs_first(scheduler, monkeypatch, account, now):
    order = []
    real_invest, real_propose = scheduler_module.invest, scheduler_module.propose
    monkeypatch.setattr(
        "core.scheduler.invest",
        lambda *args, **kwargs: order.append("invest") or real_invest(*args, **kwargs),
    )
    monkeypatch.setattr(
        "core.scheduler.propose",
        lambda *args, **kwargs: order.append("propose") or real_propose(*args, **kwargs),
    )
    account(invest_cash_enabled=True, next_invest_at=now - MINUTE, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert order == ["invest", "propose"]


def test_one_users_failure_does_not_stop_the_next(scheduler, db_session, account, now, caplog):
    broken = account(key_owner=uuid.uuid4(), next_rebalance_at=now - timedelta(hours=1))
    healthy = account(next_rebalance_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report.users == 2
    assert list_evaluations(db_session, healthy.id)[0].status == "PROPOSED"
    settings = get_settings(db_session, broken.id)
    assert settings.failure_streak == 1
    assert settings.next_rebalance_at > now
    assert any(str(broken.id) in record.getMessage() for record in caplog.records)


def test_failures_warn_once_at_the_threshold_and_the_recovery_is_noted(
    scheduler, db_session, fake_kraken, account, now, caplog
):
    caplog.set_level(logging.INFO, logger="coinpilot.scheduler")
    user = account()
    fake_kraken.down.add("Balance")

    for _ in range(4):
        update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)
        scheduler.tick(now)

    assert get_settings(db_session, user.id).failure_streak == 4
    warnings = [record for record in _ours(caplog) if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(user.id) in warnings[0].getMessage()

    fake_kraken.down.clear()
    update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)
    scheduler.tick(now)

    assert get_settings(db_session, user.id).failure_streak == 0
    assert any("recovered" in record.getMessage() for record in _ours(caplog))


def test_a_lookup_kraken_did_not_answer_counts_as_a_failure(scheduler, db_session, fake_kraken, account, now):
    """Spec §9.2: an unknown order Kraken could not be asked about is the system failing."""
    user = account(next_rebalance_at=now - MINUTE)
    _unresolved(db_session, user, now)
    fake_kraken.down.add("OpenOrders")

    scheduler.tick(now)

    assert list_evaluations(db_session, user.id)[0].status == "UNRESOLVED"
    assert get_settings(db_session, user.id).failure_streak == 1


def test_an_order_not_listed_yet_is_a_wait_not_a_failure(scheduler, db_session, account, now):
    user = account(next_rebalance_at=now - MINUTE)
    _unresolved(db_session, user, now)

    scheduler.tick(now)

    assert list_evaluations(db_session, user.id)[0].status == "UNRESOLVED"
    assert get_settings(db_session, user.id).failure_streak == 0


def test_a_busy_user_is_tried_again_on_the_next_tick(scheduler, user_locks, db_session, account, now):
    due = now - MINUTE
    user = account(next_rebalance_at=due)
    user_locks.held.add(user.id)

    scheduler.tick(now)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at == due
    assert settings.failure_streak == 0
    assert list_evaluations(db_session, user.id) == []


def test_a_user_without_a_key_moves_forward_without_counting_a_failure(scheduler, db_session, make_user, now):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at > now
    assert settings.failure_streak == 0
    assert list_evaluations(db_session, user.id) == []


def test_an_investment_switched_off_is_not_run_and_leaves_no_next_run(
    scheduler, db_session, fake_kraken, account, now
):
    user = account(balance={"ZEUR": "1000"}, next_invest_at=now - MINUTE)

    scheduler.tick(now)

    assert _sent(fake_kraken) == []
    assert get_settings(db_session, user.id).next_invest_at is None


def test_a_tick_another_process_holds_does_nothing(
    scheduler, scheduler_lock, db_session, fake_kraken, account, now
):
    due = now - MINUTE
    user = account(next_rebalance_at=due)
    scheduler_lock.held = True

    assert scheduler.tick(now) == TickReport(ran=False)
    assert fake_kraken.calls == []
    assert get_settings(db_session, user.id).next_rebalance_at == due


def test_the_batch_is_bounded_and_the_most_overdue_goes_first(app_context, db_session, account, now):
    scheduler = Scheduler(_with(app_context, batch=1))
    late = account(next_rebalance_at=now - timedelta(hours=1))
    recent = account(next_rebalance_at=now - MINUTE)

    report = scheduler.tick(now)

    assert report.users == 1
    assert len(list_evaluations(db_session, late.id)) == 1
    assert list_evaluations(db_session, recent.id) == []


def test_one_ticker_call_serves_the_whole_batch(scheduler, fake_kraken, account, now):
    account(next_rebalance_at=now - 2 * MINUTE)
    account(next_rebalance_at=now - MINUTE)

    scheduler.tick(now)

    assert fake_kraken.calls.count("Balance") == 2
    assert fake_kraken.calls.count("Ticker") == 1
    assert fake_kraken.calls.count("AssetPairs") == 1


def test_retention_runs_on_the_first_tick_of_each_day(scheduler, db_session, make_user, now):
    user = make_user()
    start_evaluation(db_session, user.id, started_at=now - timedelta(days=400))

    assert scheduler.tick(now).swept is True
    assert list_evaluations(db_session, user.id) == []
    assert scheduler.tick(now + timedelta(hours=1)).swept is False
    assert scheduler.tick(now + timedelta(days=1)).swept is True


def test_a_tick_that_raises_does_not_end_the_loop(app_context, monkeypatch):
    scheduler = Scheduler(_with(app_context, tick=timedelta(0)))
    calls = []

    def tick(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        scheduler.stop()

    monkeypatch.setattr(scheduler, "tick", tick)

    scheduler.run()

    assert len(calls) == 2


def test_the_application_starts_and_stops_the_scheduler(app_context, scheduler_lock):
    # Every tick finds the tick taken, so the thread touches nothing while the test runs.
    scheduler_lock.held = True
    app = create_app(_with(app_context, enabled=True, tick=timedelta(hours=1)))

    with TestClient(app):
        scheduler = app.state.scheduler
        assert scheduler.running

    assert not scheduler.running


def test_the_application_starts_no_scheduler_when_it_is_off(app_context):
    app = create_app(app_context)

    with TestClient(app):
        assert app.state.scheduler is None


def test_starting_fills_the_next_runs_that_are_missing(
    app_context, db_session, scheduler_lock, make_user, now
):
    scheduler_lock.held = True
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    scheduler = Scheduler(_with(app_context, tick=timedelta(hours=1)))

    scheduler.start()
    scheduler.stop()

    assert get_settings(db_session, user.id).next_rebalance_at > now
