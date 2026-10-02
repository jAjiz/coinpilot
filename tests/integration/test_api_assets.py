from decimal import Decimal

from core.db.settings import create_settings, list_assets, upsert_asset


def _with_fiat(api, headers, fiat="EUR"):
    api.patch("/config", json={"fiat": fiat}, headers=headers)


def test_a_weight_needs_a_fiat_first(api, make_user, login):
    assert api.put("/assets/XBT", json={"target_pct": "60"}, headers=login(make_user())).status_code == 409


def test_an_asset_is_stored_with_its_resolved_pair(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)

    response = api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["asset"] == "XBT"
    assert response.json()["pair"] == "XXBTZEUR"
    assert Decimal(response.json()["target_pct"]) == Decimal("60")
    assert [row.asset for row in list_assets(db_session, user.id)] == ["XBT"]


def test_the_internal_name_and_lower_case_both_mean_the_same_asset(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)

    api.put("/assets/xxbt", json={"target_pct": "30"}, headers=headers)
    api.put("/assets/xbt", json={"target_pct": "40"}, headers=headers)

    rows = list_assets(db_session, user.id)
    assert [(row.asset, row.target_pct) for row in rows] == [("XBT", Decimal("40"))]


def test_an_asset_kraken_does_not_list_is_refused(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/BTC", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_the_fiat_cannot_also_be_an_asset(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/EUR", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_weights_above_one_hundred_in_total_are_refused(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    response = api.put("/assets/ETH", json={"target_pct": "40.01"}, headers=headers)

    assert response.status_code == 422
    assert [row.asset for row in list_assets(db_session, user.id)] == ["XBT"]


def test_changing_one_weight_does_not_count_it_twice(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert api.put("/assets/XBT", json={"target_pct": "100"}, headers=headers).status_code == 200


def test_a_weight_of_zero_is_accepted_because_it_means_exit(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/SOL", json={"target_pct": "0"}, headers=headers).status_code == 200


def test_an_asset_with_no_pair_against_the_fiat_is_refused_now(api, make_user, login):
    """Refused at configuration time, not discovered at order time (spec §3.1)."""
    headers = login(make_user())
    _with_fiat(api, headers, fiat="USD")

    assert api.put("/assets/SOL", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_an_unreachable_kraken_stores_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)
    fake_kraken.down.add("Assets")

    assert api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers).status_code == 503
    assert list_assets(db_session, user.id) == []


def test_a_weight_with_three_decimals_is_refused(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/XBT", json={"target_pct": "10.005"}, headers=headers).status_code == 422


def test_the_list_carries_the_cash_target(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/SOL", json={"target_pct": "35"}, headers=headers)

    body = api.get("/assets", headers=headers).json()

    assert [row["asset"] for row in body["assets"]] == ["SOL", "XBT"]
    assert Decimal(body["cash_target_pct"]) == Decimal("5")


def test_an_asset_can_be_removed_once(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert api.delete("/assets/xbt", headers=headers).status_code == 204
    assert api.delete("/assets/XBT", headers=headers).status_code == 404


def test_a_weight_without_a_fiat_is_refused_before_asking_kraken(api, make_user, login, fake_kraken):
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=login(make_user()))

    assert fake_kraken.calls == []


def test_asset_names_and_pairs_are_read_once_for_every_user(api, make_user, login, fake_kraken):
    """Kraken's catalog is shared: a second user's weight costs no public call."""
    for _ in range(2):
        headers = login(make_user())
        _with_fiat(api, headers)
        assert api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers).status_code == 200

    assert fake_kraken.calls == ["Assets", "AssetPairs"]


def test_an_asset_is_removed_by_the_internal_name_it_was_set_with(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)
    api.put("/assets/XXBT", json={"target_pct": "60"}, headers=headers)

    assert api.delete("/assets/XXBT", headers=headers).status_code == 204
    assert list_assets(db_session, user.id) == []


def test_an_asset_is_removed_by_its_stored_name_when_kraken_is_down(
    api, db_session, make_user, login, fake_kraken
):
    """Written straight to the table, so the catalog has never been read."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    upsert_asset(db_session, user.id, asset="XBT", pair="XXBTZEUR", target_pct=Decimal("60"))
    fake_kraken.down.add("Assets")

    assert api.delete("/assets/xbt", headers=login(user)).status_code == 204
    assert list_assets(db_session, user.id) == []


def test_each_weight_shows_krakens_current_minimum(api, make_user, login):
    """XBT: 0.0001 at 50 000 is 5, over the 0.5 cost minimum. ETH: 0.0001 at 2 500 is
    0.25, under it."""
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/ETH", json={"target_pct": "40"}, headers=headers)

    body = api.get("/assets", headers=headers).json()

    minimums = {row["asset"]: row["kraken_min_fiat"] for row in body["assets"]}
    assert minimums == {"XBT": "5", "ETH": "0.5"}


def test_the_weights_are_shown_even_when_prices_cannot_be_read(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    fake_kraken.down.add("Ticker")

    response = api.get("/assets", headers=headers)

    assert response.status_code == 200
    assert response.json()["assets"][0]["kraken_min_fiat"] is None
