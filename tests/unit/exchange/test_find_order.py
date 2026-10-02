from decimal import Decimal

import pytest

from exchange.orders import find_order_by_cl_ord_id, find_order_by_txid, is_definitive_refusal
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
        "cost": "100.0",
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


@pytest.mark.parametrize(
    "errors",
    [
        ["EOrder:Insufficient funds"],
        ["EOrder:Order minimum not met"],
        ["EGeneral:Invalid arguments:volume"],
        ["EGeneral:Permission denied"],
        ["EAPI:Invalid nonce"],
        ["EService:Market in cancel_only mode"],
        ["EService:Market in post_only mode"],
        ["EService:Market in limit_only mode"],
    ],
)
def test_a_listed_code_is_a_definitive_refusal(errors):
    assert is_definitive_refusal(errors) is True


@pytest.mark.parametrize(
    "errors",
    [
        [],
        ["EService:Unavailable"],
        ["EService:Busy"],
        ["EGeneral:Internal error"],
        ["EBrandNew:A code nobody has seen"],
        # One ambiguous code is enough to make the whole answer unknown.
        ["EOrder:Insufficient funds", "EService:Busy"],
    ],
)
def test_anything_else_is_not(errors):
    """The list is closed. Reading a new code as a refusal is how a duplicate happens."""
    assert is_definitive_refusal(errors) is False


class FakeQuery:
    def __init__(self, answer):
        self._answer = answer
        self.asked = []

    def query_orders(self, txid):
        self.asked.append(txid)
        return self._answer


def test_an_order_is_read_by_its_txid_with_what_it_cost():
    client = FakeQuery({"OTX-1": _order("closed")})

    found = find_order_by_txid(client, "OTX-1")

    assert client.asked == ["OTX-1"]
    assert found.txid == "OTX-1"
    assert found.status == ExchangeOrderStatus.CLOSED
    assert found.cost == D("100.0")
    assert found.volume_executed == D("0.00212765")


def test_a_txid_that_could_not_be_read_is_unknown():
    assert find_order_by_txid(FakeQuery(None), "OTX-1") is None


def test_an_answer_without_the_txid_is_unknown_not_absent():
    """Kraken named this order. An answer that leaves it out proves nothing."""
    assert find_order_by_txid(FakeQuery({}), "OTX-1") is None


def test_a_lookup_by_client_id_carries_the_cost_too():
    found = find_order_by_cl_ord_id(FakeClient({}, {"OTX-2": _order("closed")}), CL_ORD_ID)

    assert found.cost == D("100.0")
