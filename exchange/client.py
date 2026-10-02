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
from exchange.orders import is_definitive_refusal
from exchange.precision import format_decimal
from exchange.signing import encode_body, sign
from exchange.types import Credentials, PairMeta, Placement, PlacementOutcome

logger = logging.getLogger("coinpilot.exchange")

KRAKEN_BASE_URL = "https://api.kraken.com"


class MissingCredentials(Exception):
    """A private endpoint was asked for on a client that has no key."""


class KrakenError(RuntimeError):
    """Kraken answered, and the answer was an error."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"kraken returned {errors}")
        self.errors = tuple(errors)


class KeyRefused(Exception):
    """Kraken says this key, or its secret, is not valid.

    Raised only where the caller asked to tell this apart from an outage. Everywhere else
    it is one more `None`.
    """


class KeyLockedOut(Exception):
    """Kraken has locked the account out after repeated invalid keys, typically for a few
    minutes. Every attempt restarts the lockout, so the caller must wait, not retry.

    Raised, like `KeyRefused`, only where the caller asked to tell it apart.
    """


class SecretUnreadable(Exception):
    """The secret is not base64, so no request could be signed, and none was sent."""


_LOCKOUT_ERROR = "EGeneral:Temporary lockout"

# A nonce error is left out on purpose: it means this system's clock or counter is wrong,
# not that the person typed the wrong key.
_REFUSED_KEY_ERRORS = ("EAPI:Invalid key", "EAPI:Invalid signature")


def _is_refusal(errors: tuple[str, ...]) -> bool:
    return any(str(error).startswith(_REFUSED_KEY_ERRORS) for error in errors)


def _is_lockout(errors: tuple[str, ...]) -> bool:
    return any(str(error).startswith(_LOCKOUT_ERROR) for error in errors)


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

    def _call_private(self, endpoint: str, payload: Mapping[str, str] | None = None) -> dict:
        """One signed call. Raises on every failure; the callers decide what each means."""
        credentials = self._credentials
        if credentials is None:
            raise MissingCredentials(endpoint)
        path = f"/0/private/{endpoint}"
        self._limiter.wait_turn(credentials.api_key)
        nonce = self._limiter.next_nonce(credentials.api_key)
        body = encode_body({"nonce": nonce, **dict(payload or {})})
        try:
            signature = sign(path, nonce, body, credentials.api_secret)
        except ValueError:
            # Kraken issues base64 secrets, so one that does not decode was mistyped.
            raise SecretUnreadable(endpoint) from None
        headers = {
            "API-Key": credentials.api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._http.post(path, content=body, headers=headers)
        response.raise_for_status()
        return self._unwrap(response.json())

    def _private(
        self,
        endpoint: str,
        payload: Mapping[str, str] | None = None,
        *,
        refusals: bool = False,
    ) -> dict | None:
        if self._credentials is None:
            raise MissingCredentials(endpoint)
        return self._safely(lambda: self._call_private(endpoint, payload), endpoint, refusals=refusals)

    @staticmethod
    def _unwrap(payload: dict) -> dict:
        errors = [entry for entry in payload.get("error", []) if _is_error(entry)]
        if errors:
            raise KrakenError(errors)
        return payload.get("result", {})

    def _safely(self, call: Callable[[], dict], endpoint: str, *, refusals: bool = False) -> dict | None:
        try:
            return call()
        except SecretUnreadable:
            if refusals:
                logger.warning("kraken %s refused the key", endpoint)
                raise KeyRefused(endpoint) from None
            logger.warning("kraken %s failed: the secret does not decode", endpoint)
            return None
        except KrakenError as exc:
            if refusals and _is_refusal(exc.errors):
                logger.warning("kraken %s refused the key", endpoint)
                raise KeyRefused(endpoint) from None
            if refusals and _is_lockout(exc.errors):
                logger.warning("kraken %s is locked out after repeated invalid keys", endpoint)
                raise KeyLockedOut(endpoint) from None
            logger.warning("kraken %s failed: %s", endpoint, self._redact(str(exc)))
            return None
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
                    cost_decimals=int(entry["cost_decimals"]),
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

    def assets(self) -> dict[str, str] | None:
        """Kraken's internal name for every asset, mapped to its short name: `XXBT` to `XBT`."""
        raw = self._public("Assets")
        if raw is None:
            return None
        return {
            name: str(entry["altname"])
            for name, entry in raw.items()
            if isinstance(entry, dict) and entry.get("altname")
        }

    # ----- private data ----------------------------------------------------

    def api_key_info(self) -> dict | None:
        """Requires no permission to call, which is why key validation starts here.

        Raises `KeyRefused` when Kraken says the key or its secret is wrong, and
        `KeyLockedOut` when it has stopped listening after too many wrong ones. `None`
        still means Kraken could not be asked.
        """
        return self._private("GetApiKeyInfo", refusals=True)

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
        *,
        in_quote: bool = False,
        validate: bool = False,
    ) -> Placement:
        """A market order, always, and what became of the request.

        `in_quote=True` makes `volume` an amount of the quote currency and takes the fee
        in the asset bought (`viqc`, `fcib`), so the order spends exactly that amount
        (spec §9.1). Kraken accepts it on buys only. `validate=True` has Kraken check the
        order and never trade it.

        Never `None`. This is the one call where *Kraken refused* and *nobody knows* must be
        told apart: the first leaves nothing at Kraken, the second may have bought (§9.4).
        """
        if in_quote and side != "buy":
            raise ValueError("kraken takes an amount in the quote currency for buys only")
        payload = {
            "pair": pair,
            "type": side,
            "ordertype": "market",
            "volume": format_decimal(volume),
            "cl_ord_id": cl_ord_id,
        }
        if in_quote:
            payload["oflags"] = "viqc,fcib"
        if validate:
            payload["validate"] = "true"

        try:
            result = self._call_private("AddOrder", payload)
        except MissingCredentials:
            raise
        except SecretUnreadable:
            logger.warning("kraken AddOrder not sent: the secret does not decode")
            return Placement(PlacementOutcome.REFUSED, error="the secret does not decode")
        except KrakenError as exc:
            if is_definitive_refusal(exc.errors):
                logger.warning("kraken AddOrder refused: %s", self._redact(", ".join(exc.errors)))
                return Placement(PlacementOutcome.REFUSED, error=str(exc.errors[0]))
            logger.warning("kraken AddOrder answer unknown: %s", self._redact(str(exc)))
            return Placement(PlacementOutcome.UNKNOWN)
        except Exception as exc:
            logger.warning("kraken AddOrder answer unknown: %s", self._redact(str(exc)))
            return Placement(PlacementOutcome.UNKNOWN)

        if validate:
            return Placement(PlacementOutcome.VALIDATED)
        txids = result.get("txid") if isinstance(result, dict) else None
        if isinstance(txids, list) and txids:
            return Placement(PlacementOutcome.SENT, txid=str(txids[0]))
        logger.warning("kraken AddOrder answered with no txid")
        return Placement(PlacementOutcome.UNKNOWN)

    def open_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("OpenOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("open", {})

    def closed_orders(self, cl_ord_id: str | None = None) -> dict[str, dict] | None:
        raw = self._private("ClosedOrders", {"cl_ord_id": cl_ord_id} if cl_ord_id else None)
        return None if raw is None else raw.get("closed", {})

    def query_orders(self, txid: str) -> dict[str, dict] | None:
        """Orders by Kraken's own id, open or closed."""
        raw = self._private("QueryOrders", {"txid": txid})
        if raw is None:
            return None
        return {name: entry for name, entry in raw.items() if isinstance(entry, dict)}
