import base64
import uuid
from decimal import Decimal

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()


def _ready(api, headers, fake_kraken, *, cash="1000"):
    api.patch("/api/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/api/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/api/assets/ETH", json={"target_pct": "40"}, headers=headers)
    api.post("/api/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": cash}


def test_investing_needs_a_signed_in_user(api):
    assert api.post("/api/invest").status_code == 401


def test_investing_needs_settings_first(api, make_user, login):
    response = api.post("/api/invest", headers=login(make_user()))

    assert response.status_code == 409
    assert "fiat" in response.json()["detail"]


def test_free_cash_is_invested_and_every_amount_is_a_plain_string(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/api/invest", headers=headers)

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
    api.post("/api/invest", headers=headers)

    orders = api.get("/api/orders", headers=headers).json()

    assert {order["status"] for order in orders} == {"FILLED"}
    assert {Decimal(order["cost"]) for order in orders} == {Decimal("600"), Decimal("400")}


def test_a_preview_is_validated_by_kraken_and_leaves_no_history(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    response = api.post("/api/invest", params={"preview": "true"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "PREVIEW"
    assert {leg["status"] for leg in response.json()["legs"]} == {"VALIDATED"}
    assert api.get("/api/orders", headers=headers).json() == []
    assert api.get("/api/sessions", headers=headers).json() == []


def test_an_evaluation_already_running_is_a_409(api, make_user, login, fake_kraken, user_locks):
    user = make_user()
    headers = login(user)
    _ready(api, headers, fake_kraken)
    user_locks.held.add(user.id)

    response = api.post("/api/invest", headers=headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_an_unresolved_order_is_a_409_and_is_recorded(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.lose_add_order = "dropped"
    api.post("/api/invest", headers=headers)
    fake_kraken.lose_add_order = None

    response = api.post("/api/invest", headers=headers)

    assert response.status_code == 409
    assert "unresolved" in response.json()["detail"]
    # Both evaluations start at the fixed test time, so their order in the list is not.
    assert "UNRESOLVED" in {row["status"] for row in api.get("/api/sessions", headers=headers).json()}


def test_kraken_down_is_a_503_and_nothing_is_sent(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    fake_kraken.down.add("Balance")

    response = api.post("/api/invest", headers=headers)

    assert response.status_code == 503
    assert [form for form in fake_kraken.placed if form.get("validate") != "true"] == []
    assert [row["status"] for row in api.get("/api/sessions", headers=headers).json()] == [
        "KRAKEN_UNAVAILABLE"
    ]


def test_the_history_says_what_each_evaluation_was(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)

    api.post("/api/invest", headers=headers)

    [entry] = api.get("/api/sessions", headers=headers).json()
    assert (entry["operation"], entry["trigger"]) == ("INVEST", "API")


def test_orders_of_a_session_are_oldest_first(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    sent = [leg["cl_ord_id"] for leg in api.post("/api/invest", headers=headers).json()["legs"]]
    [entry] = api.get("/api/sessions", headers=headers).json()

    orders = api.get("/api/orders", params={"session": entry["id"]}, headers=headers).json()

    assert [order["cl_ord_id"] for order in orders] == sent
    assert {order["session_id"] for order in orders} == {entry["id"]}


def test_sessions_carry_their_id(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers, fake_kraken)
    api.post("/api/invest", headers=headers)

    [entry] = api.get("/api/sessions", headers=headers).json()

    assert uuid.UUID(entry["id"])


def _history(db_session, user, statuses, at=None):
    from datetime import UTC, datetime, timedelta

    from core.db.telemetry import finish_evaluation, start_evaluation

    base = at or datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    rows = []
    for n, status in enumerate(statuses):
        record = start_evaluation(db_session, user.id, started_at=base - timedelta(hours=n))
        finish_evaluation(db_session, record.id, status=status, finished_at=base)
        rows.append(record)
    return rows


def test_the_api_never_lists_nothing_to_do(api, db_session, make_user, login):
    user = make_user()
    _history(db_session, user, ["DONE", "NOTHING_TO_DO", "PARTIAL"])

    listed = api.get("/api/sessions", headers=login(user)).json()

    assert [row["status"] for row in listed] == ["DONE", "PARTIAL"]


def test_an_idle_query_parameter_is_ignored(api, db_session, make_user, login):
    user = make_user()
    _history(db_session, user, ["DONE", "NOTHING_TO_DO", "PARTIAL"])

    listed = api.get("/api/sessions", params={"idle": "true"}, headers=login(user)).json()

    assert [row["status"] for row in listed] == ["DONE", "PARTIAL"]


def test_pages_follow_the_cursor_without_repeating_or_skipping(api, db_session, make_user, login):
    from datetime import UTC, datetime, timedelta

    from core.db.telemetry import start_evaluation

    user = make_user()
    headers = login(user)
    now = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    for at in [now, now, now, now - timedelta(hours=1), now - timedelta(hours=2)]:
        start_evaluation(db_session, user.id, started_at=at)
    everything = [row["id"] for row in api.get("/api/sessions", headers=headers).json()]

    seen, before = [], None
    while True:
        params = {"limit": 2, **({"before": before} if before else {})}
        page = api.get("/api/sessions", params=params, headers=headers).json()
        if not page:
            break
        seen += [row["id"] for row in page]
        before = page[-1]["id"]

    assert len(everything) == 5
    assert seen == everything


def test_an_unknown_cursor_is_404(api, make_user, login):
    import uuid

    response = api.get("/api/sessions", params={"before": str(uuid.uuid4())}, headers=login(make_user()))

    assert response.status_code == 404
    assert response.json()["detail"] == "that session no longer exists"
