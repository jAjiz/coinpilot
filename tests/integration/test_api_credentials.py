import base64
import logging

from api.app import create_app
from core.crypto import Sealed
from core.db.users import get_credentials
from exchange.types import Credentials

# Built at run time, so no literal that looks like a secret sits in the repository.
KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
OTHER_SECRET = base64.b64encode(b"alice-second-secret").decode()


def _register(api, headers, key=KEY, secret=SECRET):
    return api.post("/credentials", json={"api_key": key, "api_secret": secret}, headers=headers)


def test_an_accepted_key_is_stored_encrypted(api, db_session, make_user, login, app_context):
    user = make_user()

    response = _register(api, login(user))

    assert response.status_code == 201
    record = get_credentials(db_session, user.id)
    assert SECRET.encode() not in record.ciphertext
    assert KEY.encode() not in record.ciphertext
    sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
    assert app_context.cipher.unseal(user.id, sealed) == Credentials(KEY, SECRET)


def test_the_answer_carries_the_permissions_and_never_the_key(api, make_user, login, fake_kraken):
    fake_kraken.ip_allowlist = ["203.0.113.7"]

    response = _register(api, login(make_user()))

    assert response.json()["ip_allowlist"] == ["203.0.113.7"]
    assert "query-funds" in response.json()["permissions"]
    assert KEY not in response.text
    assert SECRET not in response.text


def test_an_accepted_key_names_the_permissions_to_turn_off(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.permissions += ["query-ledger", "close-trades"]

    response = _register(api, login(user))

    assert response.status_code == 201
    assert response.json()["unnecessary"] == ["close-trades", "query-ledger"]
    assert get_credentials(db_session, user.id) is not None


def test_a_key_with_exactly_what_is_needed_has_nothing_to_turn_off(api, make_user, login):
    assert _register(api, login(make_user())).json()["unnecessary"] == []


def test_a_key_that_can_withdraw_is_refused_and_not_stored(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.permissions.append("withdraw-funds")

    response = _register(api, login(user))

    assert response.status_code == 422
    assert response.json()["detail"]["rejection"] == "forbidden_permissions"
    assert response.json()["detail"]["forbidden"] == ["withdraw-funds"]
    assert get_credentials(db_session, user.id) is None


def test_a_key_missing_a_permission_is_refused_and_says_which(api, make_user, login, fake_kraken):
    fake_kraken.permissions.remove("query-closed-trades")

    response = _register(api, login(make_user()))

    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == ["query-closed-trades"]
    assert response.json()["detail"]["unnecessary"] == []


def test_a_key_kraken_refuses_is_invalid(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.refuse_key = True

    response = _register(api, login(user))

    assert response.status_code == 422
    assert response.json()["detail"]["rejection"] == "invalid_key"
    assert get_credentials(db_session, user.id) is None


def test_a_locked_out_key_says_to_wait_and_stores_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.locked_out = True

    response = _register(api, login(user))

    assert response.status_code == 429
    assert "wait" in response.json()["detail"]
    assert get_credentials(db_session, user.id) is None


def test_an_unreachable_kraken_stores_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.down.add("GetApiKeyInfo")

    response = _register(api, login(user))

    assert response.status_code == 503
    assert get_credentials(db_session, user.id) is None


def test_a_refused_replacement_leaves_the_working_key_in_place(
    api, db_session, make_user, login, fake_kraken, app_context
):
    user = make_user()
    headers = login(user)
    _register(api, headers)
    fake_kraken.permissions.append("withdraw-funds")

    assert _register(api, headers, secret=OTHER_SECRET).status_code == 422

    record = get_credentials(db_session, user.id)
    sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
    assert app_context.cipher.unseal(user.id, sealed).api_secret == SECRET


def test_the_status_says_whether_a_key_is_registered(api, make_user, login):
    headers = login(make_user())

    assert api.get("/credentials/status", headers=headers).json()["registered"] is False
    _register(api, headers)
    status = api.get("/credentials/status", headers=headers).json()
    assert status["registered"] is True
    assert status["key_version"] == 1
    assert status["validated_at"].startswith("2026-09-29T12:00:00")


def test_a_key_can_be_deleted_once(api, make_user, login):
    headers = login(make_user())
    _register(api, headers)

    assert api.delete("/credentials", headers=headers).status_code == 204
    assert api.delete("/credentials", headers=headers).status_code == 404
    assert api.get("/credentials/status", headers=headers).json()["registered"] is False


def test_registering_needs_a_signed_in_user(api):
    assert _register(api, {}).status_code == 401


def test_a_malformed_body_is_refused_without_echoing_it(api, make_user, login):
    """FastAPI's default 422 carries the rejected input. Here that input is a credential."""
    headers = login(make_user())

    missing_secret = api.post("/credentials", json={"api_key": KEY}, headers=headers)
    too_long = api.post("/credentials", json={"api_key": KEY, "api_secret": "x" * 600}, headers=headers)

    assert missing_secret.status_code == 422
    assert KEY not in missing_secret.text
    assert too_long.status_code == 422
    assert "x" * 600 not in too_long.text
    assert KEY not in too_long.text


def test_no_log_line_carries_the_key_or_the_secret(api, make_user, login, fake_kraken, caplog):
    headers = login(make_user())

    with caplog.at_level(logging.DEBUG):
        _register(api, headers)
        fake_kraken.refuse_key = True
        _register(api, headers)

    assert KEY not in caplog.text
    assert SECRET not in caplog.text


def test_no_response_model_has_a_field_for_a_credential(app_context):
    for route in create_app(app_context).routes:
        model = getattr(route, "response_model", None)
        fields = getattr(model, "model_fields", {})
        assert not any("secret" in name or name == "api_key" for name in fields), route.path
