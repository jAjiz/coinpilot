"""The process entry point: `uvicorn --factory api.main:build`.

The only place that reads the environment for the web process. Nothing imports this
module, and no test runs it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from api.app import create_app
from api.context import AppContext
from core.catalog import MarketCatalog
from core.config import load_config
from core.crypto import CredentialCipher
from core.db.session import configure, session_scope
from core.tokens import TokenSigner
from exchange.client import KrakenClient, build_http_client
from exchange.limits import KeyLimiter

# Kraken's private counter allows more; one call a second per key is what phase 3 tested.
KRAKEN_MIN_INTERVAL_SECONDS = 1.0


def build() -> FastAPI:
    config = load_config(os.environ)
    configure(config.database_url)

    def now() -> datetime:
        return datetime.now(UTC)

    kraken_http = build_http_client()
    limiter = KeyLimiter(KRAKEN_MIN_INTERVAL_SECONDS)
    context = AppContext(
        config=config,
        sessions=session_scope,
        kraken_http=kraken_http,
        google_http=httpx.Client(timeout=10.0),
        limiter=limiter,
        cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
        signer=TokenSigner(config.jwt_secret, config.jwt_ttl, now=now),
        catalog=MarketCatalog(KrakenClient(kraken_http, limiter), now),
        now=now,
    )
    return create_app(context)
