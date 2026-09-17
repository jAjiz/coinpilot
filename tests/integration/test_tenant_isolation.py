"""User A must never read or change user B's rows.

This is its own file because it is its own class of bug. It cannot exist until a system
is multi-tenant, and no test that uses a single user will ever find it.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

import core.database as db
from core.db.types import OrderReason, ProposalTrigger
from engine.types import Side

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
PLAN = {"legs": [{"asset": "BTC", "side": "sell", "amount_fiat": "100.00"}]}


@pytest.fixture
def alice(make_user):
    return make_user(email="alice@example.test")


@pytest.fixture
def bob(make_user):
    return make_user(email="bob@example.test")


def test_settings_are_not_shared(db_session: Session, alice, bob):
    db.create_settings(db_session, alice.id, fiat="EUR")

    assert db.get_settings(db_session, bob.id) is None


def test_changing_one_users_settings_leaves_the_other_alone(db_session: Session, alice, bob):
    db.create_settings(db_session, alice.id, fiat="EUR")
    db.create_settings(db_session, bob.id, fiat="EUR")

    db.update_settings(db_session, alice.id, min_drift_pct=D("5.0"))

    assert db.get_settings(db_session, bob.id).min_drift_pct == D("0")


def test_one_users_assets_never_appear_in_anothers(db_session: Session, alice, bob):
    db.upsert_asset(db_session, alice.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert db.list_assets(db_session, bob.id) == []
    assert db.targets_for(db_session, bob.id) == {}


def test_deleting_an_asset_only_reaches_your_own(db_session: Session, alice, bob):
    db.upsert_asset(db_session, alice.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert db.delete_asset(db_session, bob.id, "BTC") is False
    assert db.targets_for(db_session, alice.id) == {"BTC": D("60.00")}


def test_credentials_cannot_be_read_across_users(db_session: Session, alice, bob):
    db.save_credentials(db_session, alice.id, b"secret", b"nonce", 1, NOW)

    assert db.get_credentials(db_session, bob.id) is None
    assert db.delete_credentials(db_session, bob.id) is False


def test_the_order_history_is_scoped(db_session: Session, alice, bob):
    db.record_attempt(
        db_session,
        alice.id,
        "cl-iso-1",
        pair="XBTEUR",
        asset="BTC",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
    )

    assert db.list_orders(db_session, bob.id, limit=10) == []
    assert db.pending_orders(db_session, bob.id) == []


def test_one_users_unresolved_attempt_does_not_block_another(db_session: Session, alice, bob):
    """The gate stops one tenant, never the whole population."""
    db.record_attempt(
        db_session,
        alice.id,
        "cl-iso-2",
        pair="XBTEUR",
        asset="BTC",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
    )

    assert db.has_unresolved(db_session, alice.id) is True
    assert db.has_unresolved(db_session, bob.id) is False


def test_a_proposal_belongs_to_exactly_one_user(db_session: Session, alice, bob):
    db.save_proposal(db_session, alice.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)

    assert db.get_proposal(db_session, bob.id) is None
    assert db.withdraw(db_session, bob.id) is False
    assert db.get_live_proposal(db_session, alice.id) is not None


def test_snapshots_and_evaluations_are_scoped(db_session: Session, alice, bob):
    db.record_snapshot(
        db_session,
        alice.id,
        as_of=NOW,
        fiat="EUR",
        total_value=D("100"),
        cash=D("10"),
        holdings={},
    )
    db.start_evaluation(db_session, alice.id, started_at=NOW)

    assert db.latest_snapshot(db_session, bob.id) is None
    assert db.list_evaluations(db_session, bob.id, limit=10) == []


def test_removing_one_user_leaves_the_other_untouched(db_session: Session, alice, bob):
    """The cascade must reach everything of theirs and nothing of anybody else's."""
    for user in (alice, bob):
        db.create_settings(db_session, user.id, fiat="EUR")
        db.save_credentials(db_session, user.id, b"secret", b"nonce", 1, NOW)
        db.upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    db_session.delete(db.get_user(db_session, alice.id))
    db_session.flush()

    assert db.get_settings(db_session, alice.id) is None
    assert db.get_credentials(db_session, alice.id) is None
    assert db.targets_for(db_session, alice.id) == {}
    assert db.get_settings(db_session, bob.id) is not None
    assert db.get_credentials(db_session, bob.id) is not None
    assert db.targets_for(db_session, bob.id) == {"BTC": D("60.00")}
