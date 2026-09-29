import logging
from decimal import Decimal

import httpx
import pytest

from exchange.client import KrakenClient, MissingCredentials, build_http_client
from exchange.limits import KeyLimiter
from exchange.types import Credentials

D = Decimal

CREDENTIALS = Credentials(
    api_key="THE-PUBLIC-KEY",
    # Base64 of "this-is-a-test-secret". Fake, and allowed past the scanner on this line.
    api_secret="dGhpcy1pcy1hLXRlc3Qtc2VjcmV0",  # gitleaks:allow
)

ASSET_PAIRS = {
    "XXBTZEUR": {
        "altname": "XBTEUR",
        "base": "XXBT",
        "quote": "ZEUR",
        "pair_decimals": 1,
        "lot_decimals": 8,
        "ordermin": "0.00005",
        "costmin": "5",
        "status": "online",
    }
}


def _client(handler, *, credentials=CREDENTIALS, min_interval=0.0):
    """A client whose every request is answered by `handler`, never by the network."""
    http = httpx.Client(base_url="https://api.kraken.com", transport=httpx.MockTransport(handler))
    return KrakenClient(http, KeyLimiter(min_interval), credentials=credentials)


def _ok(result):
    return httpx.Response(200, json={"error": [], "result": result})


def test_a_public_call_is_unwrapped_into_value_objects():
    client = _client(lambda request: _ok(ASSET_PAIRS))

    pairs = client.asset_pairs()

    assert pairs["XXBTZEUR"].altname == "XBTEUR"
    assert pairs["XXBTZEUR"].volume_decimals == 8
    assert pairs["XXBTZEUR"].order_min == D("0.00005")
    assert pairs["XXBTZEUR"].tradable is True


def test_a_ticker_price_comes_back_as_a_decimal_not_a_float():
    client = _client(lambda request: _ok({"XXBTZEUR": {"c": ["47123.4", "0.01"]}}))

    prices = client.ticker(["XXBTZEUR"])

    assert prices == {"XXBTZEUR": D("47123.4")}
    assert isinstance(prices["XXBTZEUR"], Decimal)


def test_a_balance_comes_back_as_decimals():
    client = _client(lambda request: _ok({"ZEUR": "1234.5678", "XXBT": "0.05"}))

    assert client.balance() == {"ZEUR": D("1234.5678"), "XXBT": D("0.05")}


def test_a_private_call_carries_the_key_and_a_signature():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = request.content.decode()
        return _ok({})

    _client(handler).balance()

    assert seen["headers"]["API-Key"] == "THE-PUBLIC-KEY"
    assert seen["headers"]["API-Sign"]
    assert seen["body"].startswith("nonce=")


def test_a_private_call_without_credentials_is_a_programming_error():
    """Not a `None`. Asking for a balance with no key is a bug in the caller, not an
    outage, and returning `None` would hide it among the real ones."""
    client = _client(lambda request: _ok({}), credentials=None)

    with pytest.raises(MissingCredentials):
        client.balance()


def test_a_public_call_without_credentials_still_works():
    """This is what the scheduler uses for its one shared price fetch per tick."""
    client = _client(lambda request: _ok({"XXBTZEUR": {"c": ["100", "1"]}}), credentials=None)

    assert client.ticker(["XXBTZEUR"]) == {"XXBTZEUR": D("100")}


def test_a_kraken_error_becomes_none():
    client = _client(lambda request: httpx.Response(200, json={"error": ["EGeneral:Invalid arguments"]}))

    assert client.balance() is None


def test_a_kraken_warning_is_not_an_error():
    """Kraken prefixes an error with E and a warning with W. Treating a warning as a
    failure would throw away a perfectly good answer."""
    client = _client(
        lambda request: httpx.Response(200, json={"error": ["WGeneral:Deprecated"], "result": {"ZEUR": "10"}})
    )

    assert client.balance() == {"ZEUR": D("10")}


def test_an_http_error_becomes_none():
    client = _client(lambda request: httpx.Response(502, text="bad gateway"))

    assert client.balance() is None


def test_a_timeout_becomes_none():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    assert _client(handler).balance() is None


def test_a_response_that_is_not_json_becomes_none():
    client = _client(lambda request: httpx.Response(200, text="<html>maintenance</html>"))

    assert client.balance() is None


def test_a_failure_never_writes_a_credential_to_the_log(caplog):
    """The one credential test this phase can run. Nothing here may leak a key."""

    def handler(request):
        raise httpx.ConnectError(
            f"connection failed for {CREDENTIALS.api_key} with {CREDENTIALS.api_secret}",
            request=request,
        )

    with caplog.at_level(logging.WARNING):
        assert _client(handler).balance() is None

    written = caplog.text
    assert "connection failed" in written
    assert CREDENTIALS.api_key not in written
    assert CREDENTIALS.api_secret not in written


def test_an_order_is_a_market_order_and_carries_its_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"txid": ["OABCDE-12345-XYZ"]})

    result = _client(handler).add_order(
        pair="XXBTZEUR", side="buy", volume=D("0.00212765"), cl_ord_id="abc123"
    )

    assert "ordertype=market" in seen["body"]
    assert "type=buy" in seen["body"]
    assert "volume=0.00212765" in seen["body"]
    assert "cl_ord_id=abc123" in seen["body"]
    assert "price=" not in seen["body"]
    assert result["txid"] == ["OABCDE-12345-XYZ"]


def test_a_tiny_volume_is_sent_in_full_not_in_scientific_notation():
    """`str(Decimal("0.00000001"))` is "1E-8", which Kraken refuses."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"txid": ["X"]})

    _client(handler).add_order(pair="XXBTZEUR", side="sell", volume=D("0.00000001"), cl_ord_id="abc123")

    assert "volume=0.00000001" in seen["body"]


def test_a_validate_only_order_says_so():
    """No integration test places a real order. This is how that rule is kept."""
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({})

    _client(handler).add_order(pair="XXBTZEUR", side="buy", volume=D("1"), cl_ord_id="abc123", validate=True)

    assert "validate=true" in seen["body"]


def test_open_orders_can_be_filtered_by_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"open": {"OABC": {"cl_ord_id": "abc123", "status": "open"}}})

    orders = _client(handler).open_orders(cl_ord_id="abc123")

    assert "cl_ord_id=abc123" in seen["body"]
    assert orders["OABC"]["status"] == "open"


def test_closed_orders_can_be_filtered_by_client_id():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return _ok({"closed": {"OABC": {"cl_ord_id": "abc123", "status": "closed"}}})

    orders = _client(handler).closed_orders(cl_ord_id="abc123")

    assert "cl_ord_id=abc123" in seen["body"]
    assert orders["OABC"]["status"] == "closed"


def test_the_http_client_is_always_built_with_a_timeout():
    """One stalled call on a single-worker scheduler blocks every later tick."""
    http = build_http_client(timeout_seconds=7.5)

    assert http.timeout.read == 7.5
    assert http.timeout.connect == 7.5
    http.close()


def test_a_pair_that_is_not_online_comes_back_untradable():
    frozen = {"XXBTZEUR": {**ASSET_PAIRS["XXBTZEUR"], "status": "cancel_only"}}
    client = _client(lambda request: _ok(frozen))

    assert client.asset_pairs()["XXBTZEUR"].tradable is False


def test_an_asset_pair_missing_a_field_is_skipped_rather_than_crashing_the_read():
    """One malformed pair must not cost the caller every other pair in the response."""
    payload = {"GOOD": ASSET_PAIRS["XXBTZEUR"], "BROKEN": {"altname": "X"}}
    client = _client(lambda request: _ok(payload))

    pairs = client.asset_pairs()

    assert set(pairs) == {"GOOD"}
