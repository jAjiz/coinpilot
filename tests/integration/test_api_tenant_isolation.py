"""User A must never read or change user B's data through the API.

Every route here would pass its own tests with one user. This file is the only place a
second user exists.
"""

import base64
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.db.orders import record_attempt
from core.db.settings import list_assets
from core.db.telemetry import start_evaluation
from core.db.types import OrderReason
from engine.types import Side

SECRET = base64.b64encode(b"alice-test-secret-value").decode()


@pytest.fixture
def alice(make_user):
    return make_user(email="alice@example.test")


@pytest.fixture
def bob(make_user):
    return make_user(email="bob@example.test")


@pytest.fixture
def alice_ready(api, login, alice, fake_kraken):
    headers = login(alice)
    api.patch("/api/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/api/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.post("/api/credentials", json={"api_key": "ALICE-KEY", "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": "100"}
    api.post("/api/portfolio/refresh", headers=headers)
    return headers


def test_settings_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/api/config", headers=login(bob)).status_code == 404


def test_weights_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/api/assets", headers=login(bob)).json()["assets"] == []


def test_deleting_a_weight_touches_only_ones_own(api, db_session, login, alice, bob, alice_ready):
    assert api.delete("/api/assets/XBT", headers=login(bob)).status_code == 404
    assert [row.asset for row in list_assets(db_session, alice.id)] == ["XBT"]


def test_a_key_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/api/credentials/status", headers=login(bob)).json()["registered"] is False


def test_deleting_a_key_touches_only_ones_own(api, login, bob, alice_ready):
    assert api.delete("/api/credentials", headers=login(bob)).status_code == 404
    assert api.get("/api/credentials/status", headers=alice_ready).json()["registered"] is True


def test_a_refresh_never_borrows_another_users_key(api, login, bob):
    headers = login(bob)
    api.patch("/api/config", json={"fiat": "EUR"}, headers=headers)

    assert api.post("/api/portfolio/refresh", headers=headers).status_code == 409


def test_a_snapshot_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/api/portfolio", headers=login(bob)).status_code == 404


def test_orders_are_not_shared(api, db_session, login, alice, bob):
    record_attempt(
        db_session,
        alice.id,
        cl_ord_id="b" * 32,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=Decimal("10"),
    )

    assert api.get("/api/orders", headers=login(bob)).json() == []


def test_investing_never_borrows_another_users_key(api, login, bob, alice_ready, fake_kraken):
    """Bob has no key of his own. Alice's must not be the one that answers."""
    response = api.post("/api/invest", headers=login(bob))

    assert response.status_code == 409
    assert fake_kraken.placed == []


def test_a_proposal_is_not_shared(api, login, bob, alice_ready, fake_kraken):
    fake_kraken.balance = {"ZEUR": "100", "XXBT": "0.01"}
    assert api.post("/api/rebalance", headers=alice_ready).status_code == 200

    assert api.get("/api/proposal", headers=login(bob)).status_code == 404
    assert api.post("/api/proposal/approve", json={"version": 1}, headers=login(bob)).status_code == 404
    assert api.delete("/api/proposal", headers=login(bob)).status_code == 404
    assert api.get("/api/proposal", headers=alice_ready).json()["version"] == 1


def test_another_users_session_lists_no_orders(api, db_session, login, alice, bob):
    evaluation = start_evaluation(db_session, alice.id, started_at=datetime(2026, 10, 27, tzinfo=UTC))
    record_attempt(
        db_session,
        alice.id,
        cl_ord_id="c" * 32,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=Decimal("10"),
        session_id=evaluation.id,
    )

    assert api.get("/api/orders", params={"session": str(evaluation.id)}, headers=login(alice)).json() != []
    assert api.get("/api/orders", params={"session": str(evaluation.id)}, headers=login(bob)).json() == []
