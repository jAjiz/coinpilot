import base64
from datetime import timedelta

import pytest

from core.config import ConfigError, database_url, load_config


def test_a_missing_database_url_raises_rather_than_defaulting(monkeypatch):
    """A silent default would point production at a local database, and the failure would
    look like an empty account."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_the_url_that_is_set_is_the_one_returned(monkeypatch):
    """This test sets the environment because the reader is what is under test. Every
    other test states its inputs instead."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db")

    assert database_url() == "postgresql+psycopg://u:p@host:5432/db"


MASTER_KEY = bytes(range(32))


def _env(**overrides):
    """A complete environment. `None` removes a variable."""
    env = {
        "DATABASE_URL": "postgresql+psycopg://user:dbpassword@host:5432/db",
        "JWT_SECRET": "j" * 32,
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/auth/callback/google",
        "CREDENTIAL_KEYS": "1:" + base64.b64encode(MASTER_KEY).decode(),
        "CREDENTIAL_KEY_VERSION": "1",
    }
    env.update(overrides)
    return {name: value for name, value in env.items() if value is not None}


def test_a_complete_environment_loads_with_its_defaults():
    config = load_config(_env())

    assert config.jwt_ttl == timedelta(minutes=15)
    assert config.refresh_ttl == timedelta(days=30)
    assert config.cookie_secure is True
    assert config.credential_keys == {1: MASTER_KEY}
    assert config.credential_key_version == 1
    assert config.google.client_id == "client-id"


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_URL",
        "JWT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "CREDENTIAL_KEYS",
        "CREDENTIAL_KEY_VERSION",
    ],
)
def test_every_required_variable_is_named_when_it_is_missing(name):
    with pytest.raises(ConfigError, match=name):
        load_config(_env(**{name: None}))


def test_a_short_signing_secret_is_refused():
    """A short HMAC key can be brute-forced offline from one captured token."""
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_config(_env(JWT_SECRET="j" * 31))


def test_a_master_key_of_the_wrong_length_is_refused():
    short = base64.b64encode(bytes(16)).decode()

    with pytest.raises(ConfigError, match="32 bytes"):
        load_config(_env(CREDENTIAL_KEYS=f"1:{short}"))


def test_the_active_version_must_be_one_of_the_keys():
    with pytest.raises(ConfigError, match="CREDENTIAL_KEY_VERSION"):
        load_config(_env(CREDENTIAL_KEY_VERSION="2"))


def test_several_key_versions_are_kept_for_rotation():
    second = bytes(range(32, 64))
    listed = f"1:{base64.b64encode(MASTER_KEY).decode()},2:{base64.b64encode(second).decode()}"

    config = load_config(_env(CREDENTIAL_KEYS=listed, CREDENTIAL_KEY_VERSION="2"))

    assert config.credential_keys == {1: MASTER_KEY, 2: second}


@pytest.mark.parametrize("listed", ["no-colon-here", "one:AAAA", "1:not base64!"])
def test_a_malformed_key_list_is_refused(listed):
    with pytest.raises(ConfigError, match="CREDENTIAL_KEYS"):
        load_config(_env(CREDENTIAL_KEYS=listed))


def test_a_version_listed_twice_is_refused():
    encoded = base64.b64encode(MASTER_KEY).decode()

    with pytest.raises(ConfigError, match="twice"):
        load_config(_env(CREDENTIAL_KEYS=f"1:{encoded},1:{encoded}"))


def test_the_cookie_can_be_sent_over_plain_http_for_local_development():
    assert load_config(_env(COOKIE_SECURE="false")).cookie_secure is False


@pytest.mark.parametrize("name", ["JWT_TTL_MINUTES", "REFRESH_TTL_DAYS"])
def test_a_token_lifetime_of_zero_is_refused(name):
    with pytest.raises(ConfigError, match=name):
        load_config(_env(**{name: "0"}))


def test_the_lifetimes_can_be_set():
    config = load_config(_env(JWT_TTL_MINUTES="5", REFRESH_TTL_DAYS="7"))

    assert config.jwt_ttl == timedelta(minutes=5)
    assert config.refresh_ttl == timedelta(days=7)


def test_the_repr_carries_no_secret():
    """A config object that reaches a log line through a repr must not carry its secrets."""
    text = repr(load_config(_env()))

    assert "google-client-secret" not in text
    assert "j" * 32 not in text
    assert "dbpassword" not in text
    assert repr(MASTER_KEY) not in text
