"""The only module in this system that speaks HTTP to Kraken.

Everything that can fail returns `None`. A missed evaluation is recoverable and a crashed
process is not, so no network problem is ever allowed to escape as an exception.

The one thing that does raise is asking for a private call with no credentials. That is a
bug in the caller, not an outage, and returning `None` would hide it among the real ones.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation

import httpx

from exchange.limits import PUBLIC_BUCKET, KeyLimiter
from exchange.precision import format_decimal
from exchange.signing import encode_body, sign
from exchange.types import Credentials, PairMeta

logger = logging.getLogger("coinpilot.exchange")

KRAKEN_BASE_URL = "https://api.kraken.com"


class MissingCredentials(Exception):
    """A private endpoint was asked for on a client that has no key."""


def build_http_client(timeout_seconds: float = 10.0) -> httpx.Client:
    """The transport, always with a timeout.

    Stating the bound here means nobody can build a transport without one by accident.
    One stalled call on a single-worker scheduler blocks every later tick.
    """
    return httpx.Client(base_url=KRAKEN_BASE_URL, timeout=timeout_seconds)


def _is_error(entry: object) -> bool:
    """Kraken prefixes an error with `E` and a warning with `W`."""
    return str(entry).startswith("E")


def _decimal(raw: object) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


class KrakenClient:
    """One authenticated identity against Kraken.

    The credentials are optional. A client without them still reads public data, which is
    what the scheduler uses for its one shared price fetch per tick.
    """

    def __init__(
        self,
        http: httpx.Client,
        limiter: KeyLimiter,
        credentials: Credentials | None = None,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._credentials = credentials

    # ----- the two ways in -------------------------------------------------

    def _public(self, endpoint: str, params: Mapping[str, str] | None = None) -> dict | None:
        def call() -> dict:
            self._limiter.wait_turn(PUBLIC_BUCKET)
            response = self._http.get(f"/0/public/{endpoint}", params=dict(params or {}))
            response.raise_for_status()
            return self._unwrap(response.json())

        return self._safely(call, endpoint)

    def _private(self, endpoint: str, payload: Mapping[str, str] | None = None) -> dict | None:
        credentials = self._credentials
        if credentials is None:
            raise MissingCredentials(endpoint)
        path = f"/0/private/{endpoint}"

        def call() -> dict:
            self._limiter.wait_turn(credentials.api_key)
            nonce = self._limiter.next_nonce(credentials.api_key)
            body = encode_body({"nonce": nonce, **dict(payload or {})})
            headers = {
                "API-Key": credentials.api_key,
                "API-Sign": sign(path, nonce, body, credentials.api_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            response = self._http.post(path, content=body, headers=headers)
            response.raise_for_status()
            return self._unwrap(response.json())

        return self._safely(call, endpoint)

    @staticmethod
    def _unwrap(payload: dict) -> dict:
        errors = [entry for entry in payload.get("error", []) if _is_error(entry)]
        if errors:
            raise RuntimeError(f"kraken returned {errors}")
        return payload.get("result", {})

    def _safely(self, call: Callable[[], dict], endpoint: str) -> dict | None:
        try:
            return call()
        except Exception as exc:
            logger.warning("kraken %s failed: %s", endpoint, self._redact(str(exc)))
            return None

    def _redact(self, text: str) -> str:
        """Nothing this module writes may carry a credential, whatever produced it.

        An exception raised deep in a transport can quote the request it was building.
        Redacting at the one place that logs is cheaper than auditing every path that
        could reach it.
        """
        if self._credentials is None:
            return text
        return text.replace(self._credentials.api_key, "***").replace(self._credentials.api_secret, "***")

    # ----- public data -----------------------------------------------------

    def asset_pairs(self, pairs: list[str] | None = None) -> dict[str, PairMeta] | None:
        """Every tradable pair, or the ones named, as value objects.

        A pair missing a field is skipped rather than raised on: one malformed entry must
        not cost the caller every other pair in the response.
        """
        params = {"pair": ",".join(pairs)} if pairs else None
        raw = self._public("AssetPairs", params)
        if raw is None:
            return None

        parsed: dict[str, PairMeta] = {}
        for name, entry in raw.items():
            try:
                parsed[name] = PairMeta(
                    pair=name,
                    altname=entry["altname"],
                    base=entry["base"],
                    quote=entry["quote"],
                    price_decimals=int(entry["pair_decimals"]),
                    volume_decimals=int(entry["lot_decimals"]),
                    order_min=Decimal(str(entry["ordermin"])),
                    cost_min=Decimal(str(entry["costmin"])),
                    status=str(entry["status"]),
                )
            except (KeyError, TypeError, ValueError, InvalidOperation):
                logger.warning("skipping unreadable asset pair %s", name)
        return parsed

    def ticker(self, pairs: list[str]) -> dict[str, Decimal] | None:
        """The last traded price of each pair. `c` is [price, lot volume]."""
        raw = self._public("Ticker", {"pair": ",".join(pairs)})
        if raw is None:
            return None
        prices: dict[str, Decimal] = {}
        for name, entry in raw.items():
            price = _decimal((entry.get("c") or [None])[0])
            if price is not None:
                prices[name] = price
        return prices

    # ----- private data ----------------------------------------------------

    def api_key_info(self) -> dict | None:
        """Requires no permission to call, which is why key validation starts here."""
        return self._private("GetApiKeyInfo")

    def balance(self) -> dict[str, Decimal] | None:
        raw = self._private("Balance")
        if raw is None:
            return None
        balances: dict[str, Decimal] = {}
        for asset, amount in raw.items():
            value = _decimal(amount)
            if value is not None:
                balances[asset] = value
        return balances

    def add_order(
        self,
        pair: str,
        side: str,
        volume: Decimal,
        cl_ord_id: str,
        validate: bool = False,
    ) -> dict | None:
        """A market order, always.

        There is no price and no order that rests between ticks, so there is nothing to
        reprice, nothing to cancel and no order state machine. `validate=True` has Kraken
        check the order and never send it to the matching engine.
        """
        payload = {
            "pair": pair,
            "type": side,
            "ordertype": "market",
            "volume": format_decimal(volume),
            "cl_ord_id": cl_ord_id,
        }
        if validate:
            payload["validate"] = "true"
        return self._private("AddOrder", payload)

    def open_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("OpenOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("open", {})

    def closed_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("ClosedOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("closed", {})
