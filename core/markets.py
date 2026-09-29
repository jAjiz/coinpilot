"""Kraken's asset names, and the pair that trades one asset against the user's fiat.

Kraken names an asset three ways. `Balance` and `AssetPairs` use the internal name
(`XXBT`, `ZEUR`); people and newer endpoints use the short name (`XBT`, `EUR`); a balance
held in an earn product carries a suffix (`XBT.F`). This system stores the short name, in
upper case, and translates here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping

from exchange.types import PairMeta

# `.F` is Kraken Rewards: read-only as an asset and traded through its base asset, so it
# counts as holdings. Every other suffix is staked or bonded and cannot be sold now.
TRADABLE_SUFFIXES = frozenset({"", "F"})

# A dark-pool pair has the same base and quote as the lit one. It does not accept market
# orders, so an asset must never resolve to it.
DARK_POOL_SUFFIX = ".d"

# A constant, not a Kraken call: the fiat is chosen once and never changes.
SUPPORTED_FIATS = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD")


def short_name(code: str, asset_names: Mapping[str, str]) -> str | None:
    """The short name for a short or internal name, or `None` if Kraken does not list it."""
    wanted = code.strip().upper()
    if not wanted:
        return None
    for internal, short in asset_names.items():
        if wanted in (internal.upper(), short.upper()):
            return short.upper()
    return None


def kraken_key(short: str, asset_names: Mapping[str, str]) -> str | None:
    wanted = short.strip().upper()
    for internal, name in asset_names.items():
        if name.upper() == wanted:
            return internal
    return None


def split_balance_key(key: str, asset_names: Mapping[str, str]) -> tuple[str, str]:
    """`XBT.F` is (`XBT`, `F`). `XXBT` is (`XBT`, ``). An unlisted base keeps its own name."""
    base, _, suffix = key.partition(".")
    return short_name(base, asset_names) or base.upper(), suffix


def resolve_pair(
    asset: str,
    fiat: str,
    asset_names: Mapping[str, str],
    pairs: Mapping[str, PairMeta],
) -> PairMeta | None:
    """The one pair that trades `asset` against `fiat` with a market order, or `None`."""
    base = kraken_key(asset, asset_names)
    quote = kraken_key(fiat, asset_names)
    if base is None or quote is None or base == quote:
        return None
    for name in sorted(pairs):
        meta = pairs[name]
        if name.endswith(DARK_POOL_SUFFIX):
            continue
        if meta.base == base and meta.quote == quote and meta.tradable:
            return meta
    return None
