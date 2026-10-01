"""Fixtures for the tests that need a real PostgreSQL.

Every one of them is skipped unless RUN_DB_INTEGRATION is true, so a developer with no
database still runs the unit suite.

Reading DATABASE_URL here is deliberate, and it is not what the global rule forbids: it
says where the test runs, not what the code under test is given.
"""

from __future__ import annotations

import os
import urllib.parse
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from api.app import create_app
from api.context import AppContext
from core.catalog import MarketCatalog
from core.config import AppConfig, GoogleConfig
from core.crypto import CredentialCipher
from core.db.models import User
from core.db.session import create_engine_from_url
from core.db.users import create_user
from core.tokens import TokenSigner
from exchange.client import KRAKEN_BASE_URL, KrakenClient
from exchange.limits import KeyLimiter

_ROOT = Path(__file__).resolve().parents[2]


def _migrate(url: str) -> None:
    """Bring the test database to head.

    Running the real migrations rather than `create_all` means every test run also proves
    the migrations still apply.
    """
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "scripts" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _enabled() -> bool:
    return os.environ.get("RUN_DB_INTEGRATION", "").lower() == "true"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    if not _enabled():
        pytest.skip("RUN_DB_INTEGRATION is not true")
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    built = create_engine_from_url(url)
    _migrate(url)
    yield built
    built.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back.

    No test cleans up after itself, and no test can leak a row into the next one.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    """Create a user with an identity nothing else will collide with.

    Every later test file builds its rows on top of this, because every table in the
    system needs a user before it can hold anything.
    """

    def _make(email: str = "someone@example.test") -> User:
        return create_user(db_session, provider="google", subject=str(uuid.uuid4()), email=email)

    return _make


FIXED_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
REQUIRED = ["query-funds", "modify-trades", "query-open-trades", "query-closed-trades"]


def _raw_pair(altname, base, quote, status="online"):
    return {
        "altname": altname,
        "base": base,
        "quote": quote,
        "pair_decimals": 1,
        "lot_decimals": 8,
        "ordermin": "0.0001",
        "costmin": "0.5",
        "cost_decimals": 5,
        "status": status,
    }


def _ok(result):
    return httpx.Response(200, json={"error": [], "result": result})


class FakeKraken:
    """Answers Kraken from attributes a test sets. Nothing reaches the network."""

    def __init__(self):
        self.permissions = list(REQUIRED)
        self.ip_allowlist = []
        self.refuse_key = False
        self.locked_out = False
        self.down = set()
        self.assets = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "ZUSD": "USD", "SOL": "SOL"}
        self.pairs = {
            "XXBTZEUR": _raw_pair("XBTEUR", "XXBT", "ZEUR"),
            "XETHZEUR": _raw_pair("ETHEUR", "XETH", "ZEUR"),
            "SOLEUR": _raw_pair("SOLEUR", "SOL", "ZEUR"),
        }
        self.balance = {}
        self.prices = {"XXBTZEUR": "50000", "XETHZEUR": "2500", "SOLEUR": "100"}
        self.calls = []

    def __call__(self, request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(endpoint)
        if endpoint in self.down:
            return httpx.Response(503)
        if endpoint == "GetApiKeyInfo":
            if self.locked_out:
                return httpx.Response(200, json={"error": ["EGeneral:Temporary lockout"], "result": {}})
            if self.refuse_key:
                return httpx.Response(200, json={"error": ["EAPI:Invalid key"], "result": {}})
            return _ok({"permissions": self.permissions, "ipAllowlist": self.ip_allowlist})
        if endpoint == "Assets":
            return _ok({name: {"altname": short} for name, short in self.assets.items()})
        if endpoint == "AssetPairs":
            return _ok(self.pairs)
        if endpoint == "Balance":
            return _ok({name: str(amount) for name, amount in self.balance.items()})
        if endpoint == "Ticker":
            wanted = request.url.params.get("pair", "").split(",")
            return _ok({pair: {"c": [self.prices[pair], "1"]} for pair in wanted if pair in self.prices})
        return httpx.Response(404)


class FakeGoogle:
    """Answers Google's token and userinfo endpoints."""

    def __init__(self):
        self.subject = "google-subject-1"
        self.email = "alice@example.test"
        self.email_verified = True
        self.refuse_code = False
        self.token_requests = []

    def __call__(self, request):
        if request.url.host == "oauth2.googleapis.com":
            self.token_requests.append(dict(urllib.parse.parse_qsl(request.content.decode())))
            if self.refuse_code:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "google-access", "token_type": "Bearer"})
        if request.url.host == "openidconnect.googleapis.com":
            return httpx.Response(
                200, json={"sub": self.subject, "email": self.email, "email_verified": self.email_verified}
            )
        return httpx.Response(404)


@pytest.fixture
def fake_kraken() -> FakeKraken:
    return FakeKraken()


class FakeLocks:
    """The per-user lock, without a second connection. A test puts a user in `held` to
    stand for an evaluation already running."""

    def __init__(self):
        self.held = set()

    @contextmanager
    def __call__(self, user_id):
        if user_id in self.held:
            yield False
            return
        self.held.add(user_id)
        try:
            yield True
        finally:
            self.held.discard(user_id)


@pytest.fixture
def user_locks() -> FakeLocks:
    return FakeLocks()


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def app_context(
    db_session: Session, fake_kraken: FakeKraken, fake_google: FakeGoogle, user_locks: FakeLocks
) -> AppContext:
    """The application's dependencies, with every provider fake and the database real."""
    config = AppConfig(
        database_url="postgresql+psycopg://unused",
        jwt_secret="t" * 32,
        jwt_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=30),
        cookie_secure=False,
        google=GoogleConfig(
            client_id="test-client",
            client_secret="test-client-secret",
            redirect_uri="http://testserver/auth/callback/google",
        ),
        credential_keys={1: bytes(range(32))},
        credential_key_version=1,
    )

    @contextmanager
    def sessions():
        # A savepoint per request, so a request that fails rolls back exactly as it
        # would in production, and the test's own transaction still discards everything.
        nested = db_session.begin_nested()
        try:
            yield db_session
        except Exception:
            nested.rollback()
            raise
        else:
            nested.commit()

    kraken_http = httpx.Client(base_url=KRAKEN_BASE_URL, transport=httpx.MockTransport(fake_kraken))
    limiter = KeyLimiter(0.0)
    return AppContext(
        config=config,
        sessions=sessions,
        kraken_http=kraken_http,
        google_http=httpx.Client(transport=httpx.MockTransport(fake_google)),
        limiter=limiter,
        cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
        # One clock for the whole application: the tokens expire on the time the test fixes.
        signer=TokenSigner(config.jwt_secret, config.jwt_ttl, now=lambda: FIXED_NOW),
        catalog=MarketCatalog(KrakenClient(kraken_http, limiter), lambda: FIXED_NOW),
        user_lock=user_locks,
        now=lambda: FIXED_NOW,
    )


@pytest.fixture
def api(app_context: AppContext) -> TestClient:
    return TestClient(create_app(app_context))


@pytest.fixture
def login(app_context: AppContext) -> Callable[[User], dict[str, str]]:
    """Headers that authenticate as `user`, without going through Google."""

    def _headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {app_context.signer.issue(user.id).value}"}

    return _headers
