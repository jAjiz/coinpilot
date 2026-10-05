import base64
from decimal import Decimal

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()


def _ready(api, headers, fake_kraken, *, cash="1000"):
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/ETH", json={"target_pct": "40"}, headers=headers)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": cash}


def test_investing_needs_a_signed_in_user(api):
    assert api.post("/invest").status_code == 401


def test_investing_needs_settings_first(api, make_user, login):
    response = api.post("/invest", headers=login(make_user()))

    assert response.status_code == 409
    assert "fiat" in response.json()["detail"]


def test_free_cash_is_invested_and_every_amount_is_a_plain_string(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/invest", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DONE"
    assert body["preview"] is False
    legs = {leg["asset"]: leg for leg in body["legs"]}
    assert legs["XBT"]["status"] == "FILLED"
    assert legs["XBT"]["side"] == "buy"
    assert legs["XBT"]["volume"] is None
    assert legs["XBT"]["amount_fiat"] == "600"
    assert legs["XBT"]["cost"] == "600"
    assert legs["XBT"]["minimum_fiat"] == "5"


def test_the_orders_appear_in_the_history_with_their_cost(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    api.post("/invest", headers=headers)

    orders = api.get("/orders", headers=headers).json()

    assert {order["status"] for order in orders} == {"FILLED"}
    assert {Decimal(order["cost"]) for order in orders} == {Decimal("600"), Decimal("400")}


def test_a_preview_is_validated_by_kraken_and_leaves_no_history(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/invest", params={"preview": "true"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "PREVIEW"
    assert {leg["status"] for leg in response.json()["legs"]} == {"VALIDATED"}
    assert api.get("/orders", headers=headers).json() == []
    assert api.get("/sessions", headers=headers).json() == []


def test_an_evaluation_already_running_is_a_409(api, make_user, login, fake_kraken, user_locks):
    user = make_user()
    headers = login(user)
    _ready(api, headers, fake_kraken)
    user_locks.held.add(user.id)

    response = api.post("/invest", headers=headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_an_unresolved_order_is_a_409_and_is_recorded(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.lose_add_order = "dropped"
    api.post("/invest", headers=headers)
    fake_kraken.lose_add_order = None

    response = api.post("/invest", headers=headers)

    assert response.status_code == 409
    assert "unresolved" in response.json()["detail"]
    # Both evaluations start at the fixed test time, so their order in the list is not.
    assert "UNRESOLVED" in {row["status"] for row in api.get("/sessions", headers=headers).json()}


def test_kraken_down_is_a_503_and_nothing_is_sent(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.down.add("Balance")

    response = api.post("/invest", headers=headers)

    assert response.status_code == 503
    assert [form for form in fake_kraken.placed if form.get("validate") != "true"] == []
    assert [row["status"] for row in api.get("/sessions", headers=headers).json()] == ["KRAKEN_UNAVAILABLE"]


def test_the_history_says_what_each_evaluation_was(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    api.post("/invest", headers=headers)

    [entry] = api.get("/sessions", headers=headers).json()
    assert (entry["operation"], entry["trigger"]) == ("INVEST", "API")
