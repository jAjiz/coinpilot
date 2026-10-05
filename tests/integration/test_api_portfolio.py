import base64
from datetime import UTC, datetime
from decimal import Decimal

from core.db.orders import record_attempt
from core.db.telemetry import latest_snapshot, start_evaluation
from core.db.types import OrderReason
from core.db.users import get_credentials
from engine.types import Side

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()


def _ready(api, headers, *, weights=(("XBT", "50"),)):
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    for asset, pct in weights:
        api.put(f"/assets/{asset}", json={"target_pct": pct}, headers=headers)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=headers)


def test_there_is_no_portfolio_until_the_first_refresh(api, make_user, login):
    assert api.get("/portfolio", headers=login(make_user())).status_code == 404


def test_a_refresh_needs_settings(api, make_user, login):
    assert api.post("/portfolio/refresh", headers=login(make_user())).status_code == 409


def test_a_refresh_needs_a_registered_key(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.post("/portfolio/refresh", headers=headers).status_code == 409


def test_a_refresh_values_the_real_account_and_records_it(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "1000", "XXBT": "0.01", "XBT.F": "0.01", "XETH": "0", "DOT.S": "5"}

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["total_value"]) == Decimal("2000")
    assert Decimal(body["cash"]) == Decimal("1000")
    assets = body["holdings"]["assets"]
    assert assets["XBT"]["weight_pct"] == "50.00"
    assert assets["DOT.S"]["locked"] is True
    assert "ETH" not in assets
    assert body["as_of"].startswith("2026-09-29T12:00:00")
    assert latest_snapshot(db_session, user.id) is not None


def test_the_last_snapshot_is_read_back_without_calling_kraken(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100"}
    refreshed = api.post("/portfolio/refresh", headers=headers).json()
    fake_kraken.calls.clear()

    assert api.get("/portfolio", headers=headers).json() == refreshed
    assert fake_kraken.calls == []


def test_a_failed_read_records_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.down.add("Balance")

    assert api.post("/portfolio/refresh", headers=headers).status_code == 503
    assert latest_snapshot(db_session, user.id) is None


def test_a_managed_asset_with_no_price_records_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100", "XXBT": "1"}
    del fake_kraken.prices["XXBTZEUR"]

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 503
    assert "XBT" in response.json()["detail"]
    assert latest_snapshot(db_session, user.id) is None


def test_a_stored_key_that_no_longer_opens_is_reported(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    record = get_credentials(db_session, user.id)
    record.ciphertext = bytes([record.ciphertext[0] ^ 1]) + record.ciphertext[1:]
    db_session.flush()

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 500
    assert "register" in response.json()["detail"]


def test_the_history_is_empty_before_anything_happened(api, make_user, login):
    headers = login(make_user())

    assert api.get("/orders", headers=headers).json() == []
    assert api.get("/sessions", headers=headers).json() == []


def test_the_history_shows_this_users_orders_and_evaluations(api, db_session, make_user, login):
    user = make_user()
    record_attempt(
        db_session,
        user.id,
        cl_ord_id="a" * 32,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=Decimal("100"),
    )
    start_evaluation(db_session, user.id, started_at=datetime(2026, 9, 29, 11, 0, tzinfo=UTC))
    headers = login(user)

    orders = api.get("/orders", headers=headers).json()
    sessions = api.get("/sessions", headers=headers).json()

    assert [order["cl_ord_id"] for order in orders] == ["a" * 32]
    assert Decimal(orders[0]["requested_fiat"]) == Decimal("100")
    assert len(sessions) == 1


def test_a_history_page_is_bounded(api, make_user, login):
    headers = login(make_user())

    assert api.get("/orders", params={"limit": 201}, headers=headers).status_code == 422
    assert api.get("/sessions", params={"limit": 0}, headers=headers).status_code == 422


def test_a_refresh_reads_names_and_pairs_from_the_catalog(api, make_user, login, fake_kraken):
    """Every public call shares one bucket at a call a second. Names and pairs change when
    Kraken lists an asset, not on every refresh."""
    headers = login(make_user())
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100", "XETH": "1"}
    fake_kraken.calls.clear()

    api.post("/portfolio/refresh", headers=headers)
    api.post("/portfolio/refresh", headers=headers)

    assert "Assets" not in fake_kraken.calls
    assert "AssetPairs" not in fake_kraken.calls
    assert fake_kraken.calls.count("Balance") == 2
