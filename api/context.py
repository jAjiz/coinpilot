"""Everything the application needs, built once and handed to `create_app`.

The entry point builds it from the environment. A test builds it with fake transports
and a session that rolls back. Nothing under `api/` constructs a dependency of its own.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from core.catalog import MarketCatalog
from core.config import AppConfig
from core.crypto import CredentialCipher
from core.public_market import Market
from core.tokens import TokenSigner
from exchange.client import KrakenClient
from exchange.limits import KeyLimiter
from exchange.types import Credentials


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    # One unit of work per request: commits on success, rolls back on any exception.
    sessions: Callable[[], AbstractContextManager[Session]]
    kraken_http: httpx.Client
    google_http: httpx.Client
    limiter: KeyLimiter
    cipher: CredentialCipher
    signer: TokenSigner
    # Kraken's asset names and pairs, shared by every request for a day.
    catalog: MarketCatalog
    # One evaluation per user at a time (spec §9.6). Yields whether the lock was taken.
    user_lock: Callable[[uuid.UUID], AbstractContextManager[bool]]
    now: Callable[[], datetime]

    def public_kraken(self) -> Market:
        """Kraken's public side: names and pairs from the catalog, prices live."""
        return Market(self.catalog, KrakenClient(self.kraken_http, self.limiter))

    def kraken_for(self, credentials: Credentials) -> KrakenClient:
        """A client for one request. The limiter is shared, so pacing still counts per key."""
        return KrakenClient(self.kraken_http, self.limiter, credentials=credentials)
