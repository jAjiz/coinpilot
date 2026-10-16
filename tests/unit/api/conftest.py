"""An `AppContext` with no database, no Kraken and no Google behind it."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from api.context import AppContext
from core.catalog import MarketCatalog
from core.config import AppConfig, GoogleConfig
from core.crypto import CredentialCipher
from core.tokens import TokenSigner
from exchange.client import KrakenClient
from exchange.limits import KeyLimiter

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def make_context() -> Callable[[Callable[[], AbstractContextManager]], AppContext]:
    """Builds a context around `sessions`, the one dependency a test chooses."""

    def build(sessions: Callable[[], AbstractContextManager]) -> AppContext:
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
        http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
        limiter = KeyLimiter(0.0)
        return AppContext(
            config=config,
            sessions=sessions,
            kraken_http=http,
            google_http=http,
            limiter=limiter,
            cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
            signer=TokenSigner(config.jwt_secret, config.jwt_ttl, now=lambda: NOW),
            catalog=MarketCatalog(KrakenClient(http, limiter), lambda: NOW),
            user_lock=lambda user_id: nullcontext(True),
            scheduler_lock=lambda: nullcontext(False),
            now=lambda: NOW,
        )

    return build
