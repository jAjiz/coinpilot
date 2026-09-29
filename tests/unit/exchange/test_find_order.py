from decimal import Decimal

from exchange.orders import find_order_by_cl_ord_id
from exchange.types import ExchangeOrderStatus

D = Decimal
CL_ORD_ID = "abc123"


def _order(status: str = "closed", cl_ord_id: str = CL_ORD_ID) -> dict:
    return {
        "cl_ord_id": cl_ord_id,
        "status": status,
        "vol": "0.00212765",
        "vol_exec": "0.00212765",
        "price": "47000.5",
        "fee": "0.40",
    }


class FakeClient:
    """Answers the two lookups with whatever the test hands it, and counts the calls.

    `None` stands for an endpoint that could not be read at all.
    """

    def __init__(self, open_result, closed_result):
        self._open = open_result
        self._closed = closed_result
        self.calls: list[str] = []

    def open_orders(self, cl_ord_id=None):
        self.calls.append("open")
        return self._open

    def closed_orders(self, cl_ord_id=None):
        self.calls.append("closed")
        return self._closed


def test_an_order_still_on_the_book_resolves_to_its_txid():
    client = FakeClient({"OABC-1": _order("open")}, {})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-1"
    assert found.status == ExchangeOrderStatus.OPEN


def test_a_finished_order_resolves_from_the_closed_endpoint():
    client = FakeClient({}, {"OABC-2": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-2"
    assert found.status == ExchangeOrderStatus.CLOSED


def test_the_fill_comes_back_as_decimals():
    client = FakeClient({}, {"OABC-2": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.volume == D("0.00212765")
    assert found.volume_executed == D("0.00212765")
    assert found.price == D("47000.5")
    assert found.fee == D("0.40")


def test_an_expired_order_reads_as_canceled():
    client = FakeClient({}, {"OABC-3": _order("expired")})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID).status == ExchangeOrderStatus.CANCELED


def test_a_live_order_wins_over_a_dead_one_carrying_the_same_id():
    """Adopting the dead txid would finalise the trade and orphan a live order."""
    client = FakeClient({"LIVE": _order("open")}, {"DEAD": _order("canceled")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "LIVE"


def test_the_closed_endpoint_is_not_asked_once_the_open_one_answers():
    client = FakeClient({"LIVE": _order("open")}, {})

    find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert client.calls == ["open"]


def test_both_endpoints_answering_empty_is_a_genuine_absence():
    """Evidence that nothing landed. The caller marks the attempt failed and retries."""
    client = FakeClient({}, {})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found is not None
    assert found.txid is None
    assert found.status is None


def test_an_endpoint_that_could_not_be_read_makes_the_whole_lookup_unknown():
    """The two readings differ by a duplicate order, so absence is never assumed."""
    client = FakeClient(None, {})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_both_endpoints_failing_is_unknown():
    client = FakeClient(None, None)

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_one_failing_endpoint_does_not_hide_a_clean_hit_on_the_other():
    client = FakeClient(None, {"OABC-4": _order("closed")})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.txid == "OABC-4"


def test_rows_that_do_not_echo_the_id_are_unknown_not_absent():
    """Kraken is asked to filter. If it ever stopped, this is the difference between
    failing loudly and adopting a stranger's txid."""
    client = FakeClient({"SOMEONE-ELSE": _order(cl_ord_id="different")}, {})

    assert find_order_by_cl_ord_id(client, CL_ORD_ID) is None


def test_a_field_kraken_omits_reads_as_zero_rather_than_crashing():
    client = FakeClient({}, {"OABC-5": {"cl_ord_id": CL_ORD_ID, "status": "closed"}})

    found = find_order_by_cl_ord_id(client, CL_ORD_ID)

    assert found.volume == D("0")
    assert found.fee == D("0")
