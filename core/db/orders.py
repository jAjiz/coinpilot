"""The order ledger.

The row exists before the order does. `record_attempt` runs before `AddOrder`, so the
persisted state describes the attempt before the attempt happens and a lost response
leaves evidence rather than a gap.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Order
from core.db.types import OrderReason, OrderStatus
from engine.types import Side


def record_attempt(
    session: Session,
    user_id: uuid.UUID,
    cl_ord_id: str,
    pair: str,
    asset: str,
    side: Side,
    reason: OrderReason,
    requested_fiat: Decimal,
) -> Order:
    """Write the attempt down first. Nothing here talks to Kraken."""
    order = Order(
        user_id=user_id,
        cl_ord_id=cl_ord_id,
        pair=pair,
        asset=asset,
        side=side,
        reason=reason,
        status=OrderStatus.PENDING,
        requested_fiat=requested_fiat,
    )
    session.add(order)
    session.flush()
    return order


def get_by_cl_ord_id(session: Session, cl_ord_id: str) -> Order | None:
    return session.execute(select(Order).where(Order.cl_ord_id == cl_ord_id)).scalar_one_or_none()


def mark_filled(
    session: Session,
    cl_ord_id: str,
    txid: str,
    executed_volume: Decimal,
    executed_price: Decimal,
    fee: Decimal,
) -> Order | None:
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.txid = txid
    order.executed_volume = executed_volume
    order.executed_price = executed_price
    order.fee = fee
    order.status = OrderStatus.FILLED
    session.flush()
    return order


def mark_failed(session: Session, cl_ord_id: str) -> Order | None:
    """Only for a genuine absence: both endpoints answered and neither had the id.

    A lookup that itself failed is still unknown, and its row must stay `PENDING`. The
    two readings differ by a duplicate order.
    """
    order = get_by_cl_ord_id(session, cl_ord_id)
    if order is None:
        return None
    order.status = OrderStatus.FAILED
    session.flush()
    return order


def pending_orders(session: Session, user_id: uuid.UUID) -> list[Order]:
    """The attempts to resolve before this user can be evaluated, oldest first."""
    stmt = (
        select(Order)
        .where(Order.user_id == user_id, Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at, Order.cl_ord_id)
    )
    return list(session.execute(stmt).scalars())


def has_unresolved(session: Session, user_id: uuid.UUID) -> bool:
    """While anything is unresolved, this user is not evaluated.

    A plan computed on an ambiguous balance is a wrong plan, and doing nothing for one
    round is safe here.
    """
    stmt = select(Order.id).where(Order.user_id == user_id, Order.status == OrderStatus.PENDING).limit(1)
    return session.execute(stmt).first() is not None


def list_orders(session: Session, user_id: uuid.UUID, limit: int = 50) -> list[Order]:
    # `created_at` alone is not enough. PostgreSQL's `now()` is the transaction
    # timestamp, so every leg of one rebalance carries the same value and the order of
    # the page would be arbitrary. The client id breaks the tie.
    stmt = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.cl_ord_id.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())
