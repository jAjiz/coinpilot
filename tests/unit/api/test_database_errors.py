"""A database that cannot be reached is a 503 the client may retry, not a bare 500."""

import uuid
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from api.app import create_app
from api.context import AppContext
from core.catalog import MarketCatalog
from core.config import AppConfig, GoogleConfig
from core.crypto import CredentialCipher
from core.tokens import TokenSigner
from exchange.client import KrakenClient
from exchange.limits import KeyLimiter

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
UNREACHABLE = OperationalError("SELECT 1", {}, psycopg.errors.ConnectionTimeout("connection timeout expired"))
# A server-side error carries a SQLSTATE: the database answered, so it is not an outage.
LOCK_REFUSED = OperationalError("SELECT 1", {}, psycopg.errors.LockNotAvailable("could not obtain lock"))
POOL_EXHAUSTED = PoolTimeout("QueuePool limit reached")


def _api(error: Exception) -> TestClient:
    config = AppConfig(
        database_url="postgresql+psycopg://unused",
        jwt_secret="t" * 32,
        jwt_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=30),
        cookie_secure=False,
        google=GoogleConfig(client_id="c", client_secret="s", redirect_uri="http://testserver/cb"),
        credential_keys={1: bytes(range(32))},
        credential_key_version=1,
    )

    @contextmanager
    def sessions():
        raise error
        yield

    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    limiter = KeyLimiter(0.0)
    signer = TokenSigner(config.jwt_secret, config.jwt_ttl, now=lambda: NOW)
    context = AppContext(
        config=config,
        sessions=sessions,
        kraken_http=http,
        google_http=http,
        limiter=limiter,
        cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
        signer=signer,
        catalog=MarketCatalog(KrakenClient(http, limiter), lambda: NOW),
        user_lock=lambda user_id: nullcontext(True),
        scheduler_lock=lambda: nullcontext(False),
        now=lambda: NOW,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {signer.issue(uuid.uuid4()).value}"
    return client


@pytest.mark.parametrize("error", [UNREACHABLE, POOL_EXHAUSTED])
def test_an_unreachable_database_is_a_503_the_client_may_retry(error):
    response = _api(error).get("/auth/me")

    assert response.status_code == 503
    assert "database" in response.json()["detail"]


def test_the_503_does_not_carry_the_drivers_message():
    response = _api(UNREACHABLE).get("/auth/me")

    assert "timeout" not in response.text
    assert "5432" not in response.text


def test_an_error_the_database_answered_with_is_still_a_500():
    assert _api(LOCK_REFUSED).get("/auth/me").status_code == 500
