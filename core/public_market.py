"""Kraken's public side as an evaluation reads it (spec §10.1).

Every public call in the process shares one bucket, paced at a call a second, because
Kraken counts public calls per address. An evaluation that read `Assets` and `AssetPairs`
itself spent two of those seconds on data that changes only when Kraken lists an asset,
so `Market` reads them from the daily catalog. A tick goes further: `TickMarket` reads
the prices of its whole batch in one call and shares them.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Protocol

from core.catalog import MarketCatalog
from exchange.types import PairMeta


class PublicReads(Protocol):
    """What `core.reading.read_portfolio` reads from Kraken's public side."""

    def assets(self) -> Mapping[str, str] | None: ...

    def asset_pairs(self) -> Mapping[str, PairMeta] | None: ...

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None: ...


class Market:
    """Names and pairs from the catalog; prices from Kraken, on every call."""

    def __init__(self, catalog: MarketCatalog, public) -> None:
        self._catalog = catalog
        self._public = public

    def assets(self) -> Mapping[str, str] | None:
        return self._catalog.asset_names()

    def asset_pairs(self) -> Mapping[str, PairMeta] | None:
        return self._catalog.pairs()

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None:
        return self._public.ticker(pairs)


class TickMarket:
    """One tick's prices, read once and shared by every evaluation in it.

    A price is at most a tick old when it is used, and it only sizes the plan: the orders
    are market orders, and Kraken's minimum is computed from the same price, as before.
    """

    def __init__(self, source: PublicReads) -> None:
        self._source = source
        self._prices: dict[str, Decimal] = {}
        self._guard = threading.Lock()

    def assets(self) -> Mapping[str, str] | None:
        return self._source.assets()

    def asset_pairs(self) -> Mapping[str, PairMeta] | None:
        return self._source.asset_pairs()

    def preload(self, pairs: Iterable[str]) -> None:
        """One call for every pair the batch is configured with. A failure keeps nothing,
        and each evaluation then asks for its own pairs."""
        self.ticker(sorted(set(pairs)))

    def ticker(self, pairs: list[str]) -> Mapping[str, Decimal] | None:
        # The guard is held across the call: two evaluations missing the same pair would
        # otherwise both ask, and the public bucket makes them wait in turn anyway.
        with self._guard:
            missing = [pair for pair in pairs if pair not in self._prices]
            if missing:
                fetched = self._source.ticker(missing)
                if fetched is None:
                    return None
                self._prices.update(fetched)
            return {pair: self._prices[pair] for pair in pairs if pair in self._prices}
