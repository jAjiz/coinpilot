from datetime import UTC, datetime, timedelta
from decimal import Decimal

from core.db.orders import get_by_cl_ord_id, mark_sent, record_attempt
from core.db.types import OrderReason, OrderStatus
from core.settlement import ABSENCE_GRACE, resolve_pending, settle
from engine.types import Side
from exchange.orders import ABSENT
from exchange.types import ExchangeOrderStatus, OrderLookup

D = Decimal
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LONG_AGO = NOW - ABSENCE_GRACE - timedelta(seconds=1)


def _attempt(db_session, user, cl_ord_id, attempted_at=LONG_AGO, txid=None):
    record_attempt(
        db_session,
        user.id,
        cl_ord_id,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=D("100"),
        attempted_at=attempted_at,
    )
    if txid is not None:
        mark_sent(db_session, cl_ord_id, txid)


def _seen(status, executed="0.002", txid="OTX-1"):
    return OrderLookup(
        txid=txid,
        status=status,
        volume=D("0.002"),
        volume_executed=D(executed),
        price=D("50000"),
        fee=D("0.000008"),
        cost=D("100"),
    )


class FakePrivate:
    """Answers the three lookups and records which were asked."""

    def __init__(self, by_txid=None, open_=None, closed=None):
        self.by_txid = {} if by_txid is None else by_txid
        self.open = {} if open_ is None else open_
        self.closed = {} if closed is None else closed
        self.asked = []

    def query_orders(self, txid):
        self.asked.append(("query", txid))
        return self.by_txid

    def open_orders(self, cl_ord_id=None):
        self.asked.append(("open", cl_ord_id))
        return self.open

    def closed_orders(self, cl_ord_id=None):
        self.asked.append(("closed", cl_ord_id))
        return self.closed


def test_a_closed_order_is_filled_with_what_it_cost(db_session, make_user):
    _attempt(db_session, make_user(), "cl-1")

    assert settle(db_session, "cl-1", _seen(ExchangeOrderStatus.CLOSED)) is OrderStatus.FILLED
    order = get_by_cl_ord_id(db_session, "cl-1")
    assert (order.txid, order.cost, order.executed_volume) == ("OTX-1", D("100"), D("0.002"))


def test_a_canceled_order_that_executed_partly_is_filled_with_what_executed(db_session, make_user):
    """Kraken's market price protection can cancel the rest of a market order."""
    _attempt(db_session, make_user(), "cl-2")

    status = settle(db_session, "cl-2", _seen(ExchangeOrderStatus.CANCELED, executed="0.001"))

    assert status is OrderStatus.FILLED
    assert get_by_cl_ord_id(db_session, "cl-2").executed_volume == D("0.001")


def test_a_canceled_order_with_nothing_executed_failed(db_session, make_user):
    _attempt(db_session, make_user(), "cl-3")

    assert settle(db_session, "cl-3", _seen(ExchangeOrderStatus.CANCELED, executed="0")) is OrderStatus.FAILED
    assert get_by_cl_ord_id(db_session, "cl-3").error == "canceled with nothing executed"


def test_an_order_still_open_stays_pending_and_keeps_its_txid(db_session, make_user):
    _attempt(db_session, make_user(), "cl-4")

    assert settle(db_session, "cl-4", _seen(ExchangeOrderStatus.OPEN, executed="0")) is OrderStatus.PENDING
    assert get_by_cl_ord_id(db_session, "cl-4").txid == "OTX-1"


def test_a_status_word_nobody_modelled_stays_pending(db_session, make_user):
    _attempt(db_session, make_user(), "cl-5")

    assert settle(db_session, "cl-5", _seen(ExchangeOrderStatus.UNKNOWN)) is OrderStatus.PENDING


def test_a_lookup_that_failed_decides_nothing(db_session, make_user):
    _attempt(db_session, make_user(), "cl-6")

    assert settle(db_session, "cl-6", None) is OrderStatus.PENDING


def test_a_genuine_absence_failed(db_session, make_user):
    _attempt(db_session, make_user(), "cl-7")

    assert settle(db_session, "cl-7", ABSENT) is OrderStatus.FAILED


def test_nothing_pending_is_clear_and_asks_kraken_nothing(app_context, make_user):
    private = FakePrivate()

    assert resolve_pending(app_context.sessions, private, make_user().id, NOW).clear is True
    assert private.asked == []


def test_a_sent_order_is_resolved_by_its_txid(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-8", txid="OTX-8")
    private = FakePrivate(by_txid={"OTX-8": {"status": "closed", "vol_exec": "0.002", "cost": "100"}})

    resolution = resolve_pending(app_context.sessions, private, user.id, NOW)

    assert resolution.clear is True
    assert private.asked == [("query", "OTX-8")]
    assert get_by_cl_ord_id(db_session, "cl-8").status == OrderStatus.FILLED


def test_an_order_whose_answer_was_lost_is_found_by_its_client_id(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-9")
    closed = {"OTX-9": {"status": "closed", "cl_ord_id": "cl-9", "vol_exec": "0.002", "cost": "100"}}

    resolution = resolve_pending(app_context.sessions, FakePrivate(closed=closed), user.id, NOW)

    assert resolution.clear is True
    assert get_by_cl_ord_id(db_session, "cl-9").txid == "OTX-9"


def test_an_old_absence_fails_the_attempt_so_the_next_plan_retries(app_context, db_session, make_user):
    user = make_user()
    _attempt(db_session, user, "cl-10")

    resolution = resolve_pending(app_context.sessions, FakePrivate(), user.id, NOW)

    assert resolution.clear is True
    assert get_by_cl_ord_id(db_session, "cl-10").status == OrderStatus.FAILED


def test_an_absence_read_too_soon_is_not_believed(app_context, db_session, make_user):
    """Kraken may not list an order it accepted a moment ago. Failing it now is how a
    lost answer turns into a duplicate order."""
    user = make_user()
    _attempt(db_session, user, "cl-11", attempted_at=NOW - timedelta(seconds=30))

    resolution = resolve_pending(app_context.sessions, FakePrivate(), user.id, NOW)

    assert resolution.clear is False
    assert get_by_cl_ord_id(db_session, "cl-11").status == OrderStatus.PENDING


def test_one_unknown_order_keeps_the_user_unresolved_and_the_rest_still_resolve(
    app_context, db_session, make_user
):
    user = make_user()
    _attempt(db_session, user, "cl-12", txid="OTX-12")
    _attempt(db_session, user, "cl-13")

    class HalfDown(FakePrivate):
        def open_orders(self, cl_ord_id=None):
            return None

    private = HalfDown(by_txid={"OTX-12": {"status": "closed", "vol_exec": "0.002", "cost": "100"}})
    resolution = resolve_pending(app_context.sessions, private, user.id, NOW)

    assert resolution.clear is False
    assert get_by_cl_ord_id(db_session, "cl-12").status == OrderStatus.FILLED
    assert get_by_cl_ord_id(db_session, "cl-13").status == OrderStatus.PENDING
    assert any("cl-13" in message for message in resolution.messages)
