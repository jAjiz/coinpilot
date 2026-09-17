from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.orders import (
    get_by_cl_ord_id,
    has_unresolved,
    list_orders,
    mark_failed,
    mark_filled,
    pending_orders,
    record_attempt,
)
from core.db.types import OrderReason, OrderStatus
from engine.types import Side

D = Decimal


def _attempt(session: Session, user_id, cl_ord_id: str, **overrides):
    fields = {
        "pair": "XBTEUR",
        "asset": "BTC",
        "side": Side.BUY,
        "reason": OrderReason.INVEST,
        "requested_fiat": D("100"),
    }
    fields.update(overrides)
    return record_attempt(session, user_id, cl_ord_id, **fields)


def test_an_attempt_is_recorded_pending_with_nothing_from_kraken_yet(db_session: Session, make_user):
    """The row describes the attempt before the attempt happens."""
    order = _attempt(db_session, make_user().id, "cl-1")

    assert order.status == OrderStatus.PENDING
    assert order.txid is None
    assert order.executed_volume is None
    assert order.requested_fiat == D("100")


def test_the_same_client_id_cannot_be_used_twice(db_session: Session, make_user):
    """One id per attempt. Reusing one would make a lost response unresolvable."""
    _attempt(db_session, make_user().id, "cl-2")

    with pytest.raises(IntegrityError):
        _attempt(db_session, make_user().id, "cl-2")


def test_a_fill_records_the_txid_the_volume_and_the_fee(db_session: Session, make_user):
    _attempt(db_session, make_user().id, "cl-3")

    order = mark_filled(
        db_session,
        "cl-3",
        txid="OABCDE-12345-XYZ",
        executed_volume=D("0.0021"),
        executed_price=D("47000.5"),
        fee=D("0.4"),
    )

    assert order.status == OrderStatus.FILLED
    assert order.txid == "OABCDE-12345-XYZ"
    assert order.executed_volume == D("0.0021")
    assert order.fee == D("0.4")


def test_a_genuine_absence_marks_the_attempt_failed(db_session: Session, make_user):
    """Only when both endpoints answered and neither had the id. The next plan retries."""
    _attempt(db_session, make_user().id, "cl-4")

    assert mark_failed(db_session, "cl-4").status == OrderStatus.FAILED


def test_an_unknown_client_id_resolves_to_nothing(db_session: Session):
    assert get_by_cl_ord_id(db_session, "never-minted") is None
    assert mark_filled(db_session, "never-minted", "t", D("1"), D("1"), D("0")) is None
    assert mark_failed(db_session, "never-minted") is None


def test_only_unresolved_attempts_are_listed(db_session: Session, make_user):
    user = make_user()
    _attempt(db_session, user.id, "cl-5")
    _attempt(db_session, user.id, "cl-6")
    mark_filled(db_session, "cl-6", "t", D("1"), D("1"), D("0"))

    assert [o.cl_ord_id for o in pending_orders(db_session, user.id)] == ["cl-5"]


def test_one_user_is_not_blocked_by_another_users_unresolved_attempt(db_session: Session, make_user):
    blocked = make_user()
    clear = make_user()
    _attempt(db_session, blocked.id, "cl-7")

    assert has_unresolved(db_session, blocked.id) is True
    assert has_unresolved(db_session, clear.id) is False


def test_resolving_the_last_attempt_clears_the_gate(db_session: Session, make_user):
    user = make_user()
    _attempt(db_session, user.id, "cl-8")

    mark_failed(db_session, "cl-8")

    assert has_unresolved(db_session, user.id) is False


def test_history_is_ordered_and_bounded_even_within_one_transaction(db_session: Session, make_user):
    """Every leg of one rebalance shares a `created_at`, because PostgreSQL's `now()` is
    the transaction timestamp. The page order must still be stable."""
    user = make_user()
    for n in range(3):
        _attempt(db_session, user.id, f"cl-9-{n}")

    listed = list_orders(db_session, user.id, limit=2)

    assert [o.cl_ord_id for o in listed] == ["cl-9-2", "cl-9-1"]


def test_unresolved_attempts_are_ordered_oldest_first(db_session: Session, make_user):
    user = make_user()
    for n in range(3):
        _attempt(db_session, user.id, f"cl-10-{n}")

    assert [o.cl_ord_id for o in pending_orders(db_session, user.id)] == [
        "cl-10-0",
        "cl-10-1",
        "cl-10-2",
    ]


@pytest.mark.parametrize("status", [member.value for member in OrderStatus])
def test_every_order_status_the_code_knows_is_accepted(db_session: Session, make_user, status):
    order = _attempt(db_session, make_user().id, f"cl-status-{status}")

    order.status = status
    db_session.flush()


@pytest.mark.parametrize("reason", [member.value for member in OrderReason])
def test_every_reason_the_code_knows_is_accepted(db_session: Session, make_user, reason):
    _attempt(db_session, make_user().id, f"cl-reason-{reason}", reason=reason)


@pytest.mark.parametrize("side", [member.value for member in Side])
def test_every_side_the_code_knows_is_accepted(db_session: Session, make_user, side):
    _attempt(db_session, make_user().id, f"cl-side-{side}", side=side)
