from decimal import Decimal

from core.db.settings import get_settings


def test_there_are_no_settings_until_the_first_patch(api, make_user, login):
    assert api.get("/config", headers=login(make_user())).status_code == 404


def test_the_first_patch_must_choose_the_fiat(api, make_user, login):
    assert api.patch("/config", json={"paused": True}, headers=login(make_user())).status_code == 409


def test_the_first_patch_creates_the_settings_with_their_defaults(api, make_user, login):
    response = api.patch("/config", json={"fiat": "eur"}, headers=login(make_user()))

    assert response.status_code == 200
    body = response.json()
    assert body["fiat"] == "EUR"
    assert body["invest_cash_enabled"] is False
    assert body["invest_cadence_mode"] == "MIN"
    assert Decimal(body["min_order_fiat"]) == 0


def test_a_fiat_this_system_does_not_support_is_refused(api, make_user, login):
    assert api.patch("/config", json={"fiat": "BTC"}, headers=login(make_user())).status_code == 422


def test_the_fiat_cannot_change_once_chosen(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"fiat": "USD"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"fiat": "EUR", "paused": True}, headers=headers).status_code == 200


def test_amounts_come_back_as_strings(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    body = api.patch("/config", json={"min_drift_pct": "5.5", "min_order_fiat": "10"}, headers=headers).json()

    assert isinstance(body["min_drift_pct"], str)
    assert Decimal(body["min_drift_pct"]) == Decimal("5.5")
    assert Decimal(body["min_order_fiat"]) == Decimal("10")


def test_a_drift_threshold_the_column_cannot_hold_is_refused(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"min_drift_pct": "5.55"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"min_drift_pct": "101"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"min_order_fiat": "-1"}, headers=headers).status_code == 422


def test_an_interval_cadence_needs_a_length_and_an_anchor(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    no_anchor = api.patch(
        "/config", json={"invest_cadence_mode": "INTERVAL", "invest_interval_months": 1}, headers=headers
    )
    no_length = api.patch(
        "/config",
        json={"invest_cadence_mode": "INTERVAL", "invest_cadence_anchor": "2026-10-01T09:00:00+00:00"},
        headers=headers,
    )

    assert no_anchor.status_code == 422
    assert no_length.status_code == 422
    assert get_settings(db_session, user.id).invest_cadence_mode == "MIN"


def test_a_complete_interval_cadence_is_accepted(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch(
        "/config",
        json={
            "rebalance_cadence_mode": "INTERVAL",
            "rebalance_interval_months": 3,
            "rebalance_cadence_anchor": "2026-01-15T09:00:00+00:00",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["rebalance_interval_months"] == 3


def test_an_anchor_without_a_timezone_is_refused(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch("/config", json={"invest_cadence_anchor": "2026-10-01T09:00:00"}, headers=headers)

    assert response.status_code == 422


def test_a_required_setting_cannot_be_set_to_null(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"paused": None}, headers=headers).status_code == 422


def test_the_times_the_scheduler_owns_cannot_be_patched(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch("/config", json={"next_invest_at": "2026-10-01T09:00:00+00:00"}, headers=headers)

    assert response.status_code == 422
