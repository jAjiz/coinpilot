"""Investing free cash: the one place in this system that places an order (spec §9).

An evaluation runs in short transactions of its own, never in a request's. The row of an
attempt is committed before its order is sent (§9.2), and no transaction is open while
Kraken is waited on (§9.6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

import core.database as db
from core.catalog import MarketCatalog
from core.crypto import CredentialCipher, Sealed
from core.db.models import Order
from core.db.types import OrderReason
from core.portfolio import PortfolioView, plain_amount
from core.reading import PortfolioUnavailable, read_portfolio
from core.settlement import resolve_pending, settle
from engine.reconcile import reconcile
from engine.types import ZERO, CashPolicy, Policy, Side
from exchange.orders import find_order_by_txid, new_cl_ord_id
from exchange.precision import minimum_fiat, round_cost
from exchange.types import Credentials, PlacementOutcome

logger = logging.getLogger("coinpilot.execution")


class ExecutionContext(Protocol):
    """What the executor needs. `api.context.AppContext` is one; a scheduler will be another."""

    sessions: Callable[[], AbstractContextManager[Session]]
    cipher: CredentialCipher
    catalog: MarketCatalog
    now: Callable[[], datetime]
    user_lock: Callable[[uuid.UUID], AbstractContextManager[bool]]

    def public_kraken(self): ...

    def kraken_for(self, credentials: Credentials): ...


class EvaluationBusy(Exception):
    """Another evaluation of this user is running. Nothing was done."""


class NotReady(Exception):
    """The user has not configured what an investment needs. The message says what."""


class EvaluationStatus(StrEnum):
    DONE = "DONE"
    NOTHING_TO_DO = "NOTHING_TO_DO"
    STOPPED = "STOPPED"
    UNRESOLVED = "UNRESOLVED"
    KRAKEN_UNAVAILABLE = "KRAKEN_UNAVAILABLE"
    PREVIEW = "PREVIEW"
    ERROR = "ERROR"


class LegStatus(StrEnum):
    FILLED = "FILLED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    UNCHECKED = "UNCHECKED"


@dataclass(frozen=True)
class LegResult:
    asset: str
    pair: str
    amount_fiat: Decimal
    minimum_fiat: Decimal | None
    status: LegStatus
    cl_ord_id: str | None = None
    txid: str | None = None
    cost: Decimal | None = None
    executed_volume: Decimal | None = None
    executed_price: Decimal | None = None
    fee: Decimal | None = None
    error: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class InvestResult:
    status: EvaluationStatus
    preview: bool
    legs: tuple[LegResult, ...] = ()
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Target:
    asset: str
    pair: str
    target_pct: Decimal


@dataclass(frozen=True)
class _Account:
    fiat: str
    policy: Policy
    # The user's own floor, applied with Kraken's minimum in one place (spec §7.3).
    floor: Decimal
    targets: tuple[_Target, ...]
    sealed: Sealed


@dataclass(frozen=True)
class _Leg:
    asset: str
    pair: str
    # Rounded down to the pair's cost precision.
    amount: Decimal
    minimum: Decimal | None
    # Why it is not sent. `None` for a leg that is.
    note: str | None


@dataclass(frozen=True)
class _Planned:
    view: PortfolioView
    legs: tuple[_Leg, ...]


UNRESOLVED_MESSAGE = "an earlier order is still unresolved; nothing was computed"


def invest(context: ExecutionContext, user_id: uuid.UUID, *, preview: bool = False) -> InvestResult:
    """Invest the user's free cash now or, with `preview`, say what that would do.

    Raises `NotReady` before anything is read, `EvaluationBusy` when another evaluation
    of the user holds the lock, and `CredentialsUnreadable` when the stored key does not
    open. Every other outcome is a status in the result.
    """
    account = _load(context, user_id)
    private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
    if preview:
        return _preview(context, user_id, account, private)
    with context.user_lock(user_id) as taken:
        if not taken:
            raise EvaluationBusy(str(user_id))
        return _run(context, user_id, account, private)


def _load(context: ExecutionContext, user_id: uuid.UUID) -> _Account:
    with context.sessions() as session:
        settings = db.get_settings(session, user_id)
        if settings is None:
            raise NotReady("choose a fiat with PATCH /config first")
        record = db.get_credentials(session, user_id)
        if record is None:
            raise NotReady("register a Kraken key with POST /credentials first")
        policy = Policy(
            allow_sells=False,
            cash_policy=CashPolicy.REDUCE_DRIFT if settings.cash_rebalance_enabled else CashPolicy.PRORATA,
            min_drift_pct=settings.min_drift_pct,
            # Zero for the engine: the executor applies the user's floor beside Kraken's
            # minimum, so a leg dropped for either reason is logged with it.
            min_order_fiat=ZERO,
        )
        targets = tuple(
            _Target(row.asset, row.pair, row.target_pct) for row in db.list_assets(session, user_id)
        )
        sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
        return _Account(
            fiat=settings.fiat,
            policy=policy,
            floor=settings.min_order_fiat,
            targets=targets,
            sealed=sealed,
        )


def _plan(context: ExecutionContext, account: _Account, private) -> _Planned:
    """Read the account, run the engine, and size each leg against Kraken's minimum.

    Raises `PortfolioUnavailable` when any read fails.
    """
    view = read_portfolio(context.public_kraken(), private, account.fiat, account.targets)
    metas = context.catalog.pairs()
    if metas is None:
        raise PortfolioUnavailable("asset pairs")
    managed = {holding.asset: holding for holding in view.holdings if holding.managed}
    pair_of = {target.asset: target.pair for target in account.targets}
    plan = reconcile(
        {asset: holding.amount for asset, holding in managed.items()},
        {asset: holding.price for asset, holding in managed.items()},
        {target.asset: target.target_pct for target in account.targets},
        view.cash,
        account.policy,
    )

    legs: list[_Leg] = []
    for leg in plan.legs:
        if leg.side is not Side.BUY:
            raise RuntimeError("an invest plan never sells; phase 6 owns sells")
        pair = pair_of[leg.asset]
        meta = metas.get(pair)
        if meta is None or not meta.tradable:
            legs.append(_Leg(leg.asset, pair, leg.amount_fiat, None, f"kraken does not trade {pair} now"))
            continue
        amount = round_cost(meta, leg.amount_fiat)
        minimum = max(minimum_fiat(meta, managed[leg.asset].price), account.floor)
        note = None
        if amount < minimum:
            note = (
                f"{plain_amount(amount)} {account.fiat} is below the minimum "
                f"of {plain_amount(minimum)} {account.fiat}"
            )
        legs.append(_Leg(leg.asset, pair, amount, minimum, note))
    return _Planned(view=view, legs=tuple(legs))


def _run(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> InvestResult:
    with context.sessions() as session:
        evaluation_id = db.start_evaluation(session, user_id, context.now()).id
    log: list[str] = []
    legs: list[LegResult] = []
    status = EvaluationStatus.ERROR
    try:
        status = _evaluate(context, user_id, account, private, log, legs)
    except PortfolioUnavailable as exc:
        status = EvaluationStatus.KRAKEN_UNAVAILABLE
        log.append(f"kraken did not return {exc}; nothing was sent")
    finally:
        with context.sessions() as session:
            db.finish_evaluation(session, evaluation_id, status, context.now(), "\n".join(log) or None)
    return InvestResult(status=status, preview=False, legs=tuple(legs), messages=tuple(log))


def _evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    log: list[str],
    legs: list[LegResult],
) -> EvaluationStatus:
    resolution = resolve_pending(context.sessions, private, user_id, context.now())
    log.extend(resolution.messages)
    if not resolution.clear:
        log.append(UNRESOLVED_MESSAGE)
        return EvaluationStatus.UNRESOLVED

    planned = _plan(context, account, private)
    with context.sessions() as session:
        db.record_snapshot(
            session,
            user_id,
            as_of=context.now(),
            fiat=account.fiat,
            total_value=planned.view.managed_value,
            cash=planned.view.cash,
            holdings=planned.view.snapshot_json(),
        )

    stopped = False
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
        elif stopped:
            legs.append(_skipped(leg, "not sent: an earlier order's answer is unknown"))
        else:
            result = _send(context, user_id, private, leg)
            legs.append(result)
            # An unknown answer leaves no txid. The balance is ambiguous until resolved.
            stopped = result.status is LegStatus.PENDING and result.txid is None
        log.append(_describe(legs[-1], account.fiat))

    if stopped:
        return EvaluationStatus.STOPPED
    if any(leg.status is not LegStatus.SKIPPED for leg in legs):
        return EvaluationStatus.DONE
    return EvaluationStatus.NOTHING_TO_DO


def _send(context: ExecutionContext, user_id: uuid.UUID, private, leg: _Leg) -> LegResult:
    cl_ord_id = new_cl_ord_id()
    with context.sessions() as session:
        db.record_attempt(
            session,
            user_id,
            cl_ord_id,
            pair=leg.pair,
            asset=leg.asset,
            side=Side.BUY,
            reason=OrderReason.INVEST,
            requested_fiat=leg.amount,
            attempted_at=context.now(),
        )
    # Committed. From here a lost answer leaves a row to resolve, not a gap (spec §9.2).
    placement = private.add_order(leg.pair, "buy", leg.amount, cl_ord_id, in_quote=True)

    if placement.outcome is PlacementOutcome.REFUSED:
        with context.sessions() as session:
            db.mark_failed(session, cl_ord_id, error=placement.error)
    elif placement.outcome is PlacementOutcome.SENT:
        with context.sessions() as session:
            db.mark_sent(session, cl_ord_id, placement.txid)
        lookup = find_order_by_txid(private, placement.txid)
        with context.sessions() as session:
            settle(session, cl_ord_id, lookup)

    with context.sessions() as session:
        return _from_row(leg, db.get_by_cl_ord_id(session, cl_ord_id))


def _from_row(leg: _Leg, order: Order) -> LegResult:
    return LegResult(
        asset=leg.asset,
        pair=leg.pair,
        amount_fiat=leg.amount,
        minimum_fiat=leg.minimum,
        status=LegStatus(order.status),
        cl_ord_id=order.cl_ord_id,
        txid=order.txid,
        cost=order.cost,
        executed_volume=order.executed_volume,
        executed_price=order.executed_price,
        fee=order.fee,
        error=order.error,
    )


def _skipped(leg: _Leg, note: str) -> LegResult:
    return LegResult(leg.asset, leg.pair, leg.amount, leg.minimum, LegStatus.SKIPPED, note=note)


def _describe(leg: LegResult, fiat: str) -> str:
    text = f"{leg.asset}: buy of {plain_amount(leg.amount_fiat)} {fiat} {leg.status.value}"
    if leg.error:
        text += f" ({leg.error})"
    if leg.note:
        text += f": {leg.note}"
    return text


def _preview(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> InvestResult:
    """Read, plan and have Kraken validate. Writes nothing, takes no lock, resolves nothing."""
    with context.sessions() as session:
        unresolved = db.has_unresolved(session, user_id)
    if unresolved:
        return InvestResult(EvaluationStatus.UNRESOLVED, preview=True, messages=(UNRESOLVED_MESSAGE,))
    try:
        planned = _plan(context, account, private)
    except PortfolioUnavailable as exc:
        return InvestResult(
            EvaluationStatus.KRAKEN_UNAVAILABLE, preview=True, messages=(f"kraken did not return {exc}",)
        )

    verdicts = {PlacementOutcome.VALIDATED: LegStatus.VALIDATED, PlacementOutcome.REFUSED: LegStatus.REJECTED}
    legs: list[LegResult] = []
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
            continue
        placement = private.add_order(
            leg.pair, "buy", leg.amount, new_cl_ord_id(), in_quote=True, validate=True
        )
        status = verdicts.get(placement.outcome, LegStatus.UNCHECKED)
        legs.append(LegResult(leg.asset, leg.pair, leg.amount, leg.minimum, status, error=placement.error))
    return InvestResult(EvaluationStatus.PREVIEW, preview=True, legs=tuple(legs))
