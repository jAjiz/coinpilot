import base64
import uuid

import pytest

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
DRIFTED = {"ZEUR": "0", "XXBT": "0.014", "XETH": "0.12"}


@pytest.fixture
def headers(api, make_user, login, fake_kraken):
    signed_in = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=signed_in)
    api.put("/assets/XBT", json={"target_pct": "50"}, headers=signed_in)
    api.put("/assets/ETH", json={"target_pct": "50"}, headers=signed_in)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=signed_in)
    fake_kraken.balance = dict(DRIFTED)
    return signed_in


def _sent(fake_kraken):
    return [form for form in fake_kraken.placed if form.get("validate") != "true"]


def test_rebalancing_needs_a_signed_in_user(api):
    assert api.post("/rebalance").status_code == 401
    assert api.get("/proposal").status_code == 401
    assert api.post("/proposal/approve", json={"version": 1}).status_code == 401
    assert api.delete("/proposal").status_code == 401


def test_rebalancing_needs_settings_first(api, make_user, login):
    response = api.post("/rebalance", headers=login(make_user()))

    assert response.status_code == 409
    assert "fiat" in response.json()["detail"]


def test_a_rebalance_answers_with_its_proposal_and_sends_nothing(api, headers, fake_kraken):
    response = api.post("/rebalance", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROPOSED"
    assert body["legs"] == []
    proposal = body["proposal"]
    assert (proposal["version"], proposal["status"], proposal["fiat"]) == (1, "LIVE", "EUR")
    assert [
        (leg["asset"], leg["side"], leg["amount_fiat"], leg["minimum_fiat"]) for leg in proposal["legs"]
    ] == [
        ("XBT", "sell", "200", "5"),
        ("ETH", "buy", "200", "0.5"),
    ]
    assert fake_kraken.placed == []


def test_the_live_proposal_can_be_read(api, headers):
    assert api.get("/proposal", headers=headers).status_code == 404
    api.post("/rebalance", headers=headers)

    response = api.get("/proposal", headers=headers)

    assert response.status_code == 200
    assert response.json()["version"] == 1


def test_approving_the_version_read_executes_the_rebalance(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DONE"
    assert body["proposal"] is None
    assert [(leg["asset"], leg["side"], leg["status"]) for leg in body["legs"]] == [
        ("XBT", "sell", "FILLED"),
        ("ETH", "buy", "FILLED"),
    ]
    assert body["legs"][0]["volume"] == "0.004"
    assert {order["reason"] for order in api.get("/orders", headers=headers).json()} == {"REBALANCE"}
    assert api.get("/proposal", headers=headers).status_code == 404


def test_approving_another_version_is_a_409_with_the_live_proposal(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)

    response = api.post("/proposal/approve", json={"version": 7}, headers=headers)

    assert response.status_code == 409
    assert response.json()["proposal"]["version"] == 1
    assert fake_kraken.placed == []


def test_an_approval_that_meets_a_changed_plan_is_a_409_with_the_new_version(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)
    fake_kraken.prices["XXBTZEUR"] = "51000"

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 409
    assert response.json()["proposal"]["version"] == 2
    assert _sent(fake_kraken) == []
    # Both evaluations start at the test's fixed clock, so their order is not defined.
    assert {e["status"] for e in api.get("/sessions", headers=headers).json()} == {"PROPOSED", "SUPERSEDED"}


def test_there_is_nothing_to_approve_without_a_proposal(api, headers):
    assert api.post("/proposal/approve", json={"version": 1}, headers=headers).status_code == 404


def test_an_approval_names_its_version(api, headers):
    assert api.post("/proposal/approve", json={}, headers=headers).status_code == 422
    assert api.post("/proposal/approve", json={"version": 0}, headers=headers).status_code == 422


def test_a_proposal_can_be_withdrawn(api, headers):
    api.post("/rebalance", headers=headers)

    assert api.delete("/proposal", headers=headers).status_code == 204
    assert api.get("/proposal", headers=headers).status_code == 404
    assert api.delete("/proposal", headers=headers).status_code == 404


def test_a_rebalance_already_running_is_a_409(api, headers, user_locks):
    user_locks.held.add(uuid.UUID(api.get("/auth/me", headers=headers).json()["id"]))

    response = api.post("/rebalance", headers=headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_kraken_down_is_a_503_and_the_proposal_is_untouched(api, headers, fake_kraken):
    api.post("/rebalance", headers=headers)
    fake_kraken.down.add("Balance")

    response = api.post("/proposal/approve", json={"version": 1}, headers=headers)

    assert response.status_code == 503
    assert api.get("/proposal", headers=headers).json()["version"] == 1
