"""User A must never read or change user B's data through the API.

Every route here would pass its own tests with one user. This file is the only place a
second user exists.
"""

import base64
from decimal import Decimal

import pytest

from core.db.orders import record_attempt
from core.db.settings import list_assets
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
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.post("/credentials", json={"api_key": "ALICE-KEY", "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": "100"}
    api.post("/portfolio/refresh", headers=headers)
    return headers


def test_settings_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/config", headers=login(bob)).status_code == 404


def test_weights_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/assets", headers=login(bob)).json()["assets"] == []


def test_deleting_a_weight_touches_only_ones_own(api, db_session, login, alice, bob, alice_ready):
    assert api.delete("/assets/XBT", headers=login(bob)).status_code == 404
    assert [row.asset for row in list_assets(db_session, alice.id)] == ["XBT"]


def test_a_key_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/credentials/status", headers=login(bob)).json()["registered"] is False


def test_deleting_a_key_touches_only_ones_own(api, login, bob, alice_ready):
    assert api.delete("/credentials", headers=login(bob)).status_code == 404
    assert api.get("/credentials/status", headers=alice_ready).json()["registered"] is True


def test_a_refresh_never_borrows_another_users_key(api, login, bob):
    headers = login(bob)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.post("/portfolio/refresh", headers=headers).status_code == 409


def test_a_snapshot_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/portfolio", headers=login(bob)).status_code == 404


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

    assert api.get("/orders", headers=login(bob)).json() == []


def test_investing_never_borrows_another_users_key(api, login, bob, alice_ready, fake_kraken):
    """Bob has no key of his own. Alice's must not be the one that answers."""
    response = api.post("/invest", headers=login(bob))

    assert response.status_code == 409
    assert fake_kraken.placed == []
