"""Kraken's asset names and pairs, read at most once a day and shared by every request.

They change when Kraken lists or retires an asset, which is rare. Reading them on every
`PUT /assets` cost two public calls, and every public call in the process shares one
bucket paced at a call a second, so a burst of users queued behind each other while the
request held a database connection.

A copy up to a day old is accepted: an asset Kraken lists today may be refused until the
next read. Evaluations read names and pairs from here too (`core.public_market`). Prices
are never kept here: they are read live, or once per scheduler tick.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol

from exchange.types import PairMeta

CATALOG_TTL = timedelta(days=1)


class CatalogSource(Protocol):
    def assets(self) -> dict[str, str] | None: ...

    def asset_decimals(self) -> dict[str, int] | None: ...

    def asset_pairs(self) -> dict[str, PairMeta] | None: ...


class _Kept:
    """One copy and when it was read. A failed read keeps nothing."""

    def __init__(self, read: Callable[[], Mapping | None], now: Callable[[], datetime], ttl: timedelta):
        self._read = read
        self._now = now
        self._ttl = ttl
        self._copy: tuple[datetime, Mapping] | None = None

    def get(self) -> Mapping | None:
        # No lock: two requests that miss at once both read Kraken, once a day at most.
        # A lock held across the call would queue every request behind a slow Kraken.
        kept = self._copy
        if kept is not None and self._now() - kept[0] < self._ttl:
            return kept[1]
        fresh = self._read()
        if fresh is None:
            return None
        copy = MappingProxyType(dict(fresh))
        self._copy = (self._now(), copy)
        return copy


class MarketCatalog:
    def __init__(self, source: CatalogSource, now: Callable[[], datetime], ttl: timedelta = CATALOG_TTL):
        self._names = _Kept(source.assets, now, ttl)
        self._pairs = _Kept(source.asset_pairs, now, ttl)
        self._decimals = _Kept(source.asset_decimals, now, ttl)

    def asset_names(self) -> Mapping[str, str] | None:
        """Internal name to short name, as `KrakenClient.assets()`. `None` if Kraken did not answer."""
        return self._names.get()

    def pairs(self) -> Mapping[str, PairMeta] | None:
        """Every pair, as `KrakenClient.asset_pairs()`. `None` if Kraken did not answer."""
        return self._pairs.get()

    def decimals(self) -> Mapping[str, int] | None:
        """The ledger's places by short name, as `KrakenClient.asset_decimals()`."""
        return self._decimals.get()
