"""The Kraken reads a portfolio view needs, through clients the caller hands in.

Used by `POST /portfolio/refresh` now and by the scheduler in phase 7. Every read is
required: one that fails raises, and nothing is recorded from a partial answer.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

from core.markets import TRADABLE_SUFFIXES, resolve_pair, split_balance_key
from core.portfolio import PortfolioView, build_view
from engine.types import ZERO, UnpricedAsset


class PortfolioUnavailable(Exception):
    """Kraken did not answer one of the reads. The message names which."""


class ConfiguredAsset(Protocol):
    asset: str
    pair: str
    target_pct: Decimal


def read_portfolio(public, private, fiat: str, assets: Iterable[ConfiguredAsset]) -> PortfolioView:
    configured = list(assets)
    names = public.assets()
    if names is None:
        raise PortfolioUnavailable("asset names")
    balances = private.balance()
    if balances is None:
        raise PortfolioUnavailable("balance")

    targets = {row.asset: row.target_pct for row in configured}
    pair_of = {row.asset: row.pair for row in configured}

    held = set()
    for key, amount in balances.items():
        name, suffix = split_balance_key(key, names)
        if amount != ZERO and suffix in TRADABLE_SUFFIXES:
            held.add(name)
    unmanaged = sorted(held - set(targets) - {fiat})
    if unmanaged:
        pairs = public.asset_pairs()
        if pairs is None:
            raise PortfolioUnavailable("asset pairs")
        for asset in unmanaged:
            meta = resolve_pair(asset, fiat, names, pairs)
            if meta is not None:
                pair_of[asset] = meta.pair

    quotes = public.ticker(sorted(set(pair_of.values()))) if pair_of else {}
    if quotes is None:
        raise PortfolioUnavailable("prices")
    prices = {asset: quotes[pair] for asset, pair in pair_of.items() if pair in quotes}

    try:
        return build_view(balances, names, fiat, targets, prices)
    except UnpricedAsset as exc:
        raise PortfolioUnavailable(f"a price for {exc.asset}") from None
