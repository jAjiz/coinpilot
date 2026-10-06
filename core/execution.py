"""Placing orders: the one place in this system that does (spec §9).

Two operations run through here. An investment buys with free cash and needs no
approval. A rebalance sells first and buys with what the sells raised, and is sent only
when the caller's decision says so; `core/rebalance.py` holds that decision.

An evaluation runs in short transactions of its own, never in a request's. The row of an
attempt is committed before its order is sent (§9.2), and no transaction is open while
Kraken is waited on (§9.6).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from sqlalchemy.orm import Session

import core.database as db
from core.catalog import MarketCatalog
from core.crypto import CredentialCipher, Sealed
from core.db.models import Order
from core.db.types import Operation, OrderReason, Trigger
from core.portfolio import PortfolioView, plain_amount
from core.reading import PortfolioUnavailable, read_portfolio
from core.settlement import resolve_pending, settle
from engine.reconcile import reconcile
from engine.types import HUNDRED, ZERO, CashPolicy, Policy, Side
from exchange.orders import find_order_by_txid, new_cl_ord_id
from exchange.precision import credited, minimum_fiat, round_cost, round_volume, volume_from_fiat
from exchange.types import Credentials, PairMeta, Placement, PlacementOutcome

logger = logging.getLogger("coinpilot.execution")


class ExecutionContext(Protocol):
    """What the executor needs. `api.context.AppContext` is one; the scheduler's tick is another."""

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
    """The user has not configured what an operation needs. The message says what."""


class EvaluationStatus(StrEnum):
    DONE = "DONE"
    NOTHING_TO_DO = "NOTHING_TO_DO"
    STOPPED = "STOPPED"
    UNRESOLVED = "UNRESOLVED"
    KRAKEN_UNAVAILABLE = "KRAKEN_UNAVAILABLE"
    PREVIEW = "PREVIEW"
    ERROR = "ERROR"
    # Every order was answered, and Kraken refused at least one. What filled stays filled.
    PARTIAL = "PARTIAL"
    # A rebalance was computed and waits for approval. Nothing was sent.
    PROPOSED = "PROPOSED"
    # An approval met a plan that had changed. Nothing was sent.
    SUPERSEDED = "SUPERSEDED"


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
    side: Side
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
    # A sell's volume of the asset. A buy is placed in fiat and has none.
    volume: Decimal | None = None


@dataclass(frozen=True)
class EvaluationResult:
    status: EvaluationStatus
    preview: bool
    legs: tuple[LegResult, ...] = ()
    messages: tuple[str, ...] = ()
    # With `UNRESOLVED`: what blocked it was a lookup Kraken did not answer (spec §9.2),
    # not an order merely not listed yet.
    lookup_failed: bool = False


@dataclass(frozen=True)
class PlannedLeg:
    asset: str
    pair: str
    side: Side
    # In fiat, rounded down to the pair's cost precision.
    amount: Decimal
    minimum: Decimal | None
    # Why it is not sent. `None` for a leg that is.
    note: str | None
    # A sell's volume of the asset, rounded down. A buy is placed in fiat and has none.
    volume: Decimal | None = None
    # The pair's metadata, to resize a buy against what the sells raised.
    meta: PairMeta | None = None


@dataclass(frozen=True)
class Planned:
    view: PortfolioView
    legs: tuple[PlannedLeg, ...]
    # Fiat above the cash target when the account was read: what buys may spend before
    # any sell has raised anything.
    free_cash: Decimal
    # The places Kraken's ledger keeps for the fiat: what a sell credits is rounded to them.
    fiat_places: int


# Once the plan is known, under the lock: `None` sends it, and a status ends the
# evaluation with nothing sent. It may write in transactions of its own, and log.
Decision = Callable[[Planned, list[str]], EvaluationStatus | None]


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


UNRESOLVED_MESSAGE = "an earlier order is still unresolved; nothing was computed"


class _Pin:
    """Pins the evaluation's snapshot once, just before its first order is sent.

    Before, not after: a process that dies mid-operation still leaves the account as it was
    before the orders, and the day's next read cannot overwrite it.
    """

    def __init__(self, context: ExecutionContext, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
        self._context = context
        self._user_id = user_id
        self._snapshot_id = snapshot_id
        self._done = False

    def __call__(self) -> None:
        if self._done:
            return
        with self._context.sessions() as session:
            db.pin_snapshot(session, self._user_id, self._snapshot_id)
        self._done = True


def invest(
    context: ExecutionContext,
    user_id: uuid.UUID,
    *,
    preview: bool = False,
    trigger: Trigger = Trigger.API,
) -> EvaluationResult:
    """Invest the user's free cash now or, with `preview`, say what that would do.

    Raises `NotReady` before anything is read, `EvaluationBusy` when another evaluation
    of the user holds the lock, and `CredentialsUnreadable` when the stored key does not
    open. Every other outcome is a status in the result.

    By hand, the call is the user asking, and `invest_cash_enabled` does not apply (spec
    §3.4). From the scheduler, the settings are read again under the lock, just before
    anything is sent: an investment switched off, or a user paused, since the scheduler
    chose them is not spent from.
    """
    if preview:
        account = _load(context, user_id, allow_sells=False)
        private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
        return _preview(context, user_id, account, private)
    return evaluate(
        context,
        user_id,
        allow_sells=False,
        reason=OrderReason.INVEST,
        decide=_still_scheduled(context, user_id) if trigger is Trigger.SCHEDULER else _send_it,
        operation=Operation.INVEST,
        trigger=trigger,
    )


def _send_it(planned: Planned, log: list[str]) -> None:
    """An investment needs no approval (spec §3.4)."""
    return None


def _still_scheduled(context: ExecutionContext, user_id: uuid.UUID) -> Decision:
    def decide(planned: Planned, log: list[str]) -> EvaluationStatus | None:
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
        if settings is None or not settings.invest_cash_enabled:
            log.append("investing was switched off; nothing was sent")
            return EvaluationStatus.NOTHING_TO_DO
        if settings.paused:
            log.append("scheduled operations are paused; nothing was sent")
            return EvaluationStatus.NOTHING_TO_DO
        return None

    return decide


def evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    *,
    allow_sells: bool,
    reason: OrderReason,
    decide: Decision,
    operation: Operation,
    trigger: Trigger,
) -> EvaluationResult:
    """Lock, resolve, read and plan; then let `decide` judge, and send what it lets through.

    Raises as `invest` does. Every other outcome is a status in the result, and recorded
    with `operation` and `trigger`.
    """
    account = _load(context, user_id, allow_sells=allow_sells)
    private = context.kraken_for(context.cipher.unseal(user_id, account.sealed))
    with context.user_lock(user_id) as taken:
        if not taken:
            raise EvaluationBusy(str(user_id))
        return _run(context, user_id, account, private, reason, decide, operation, trigger)


def _load(context: ExecutionContext, user_id: uuid.UUID, *, allow_sells: bool) -> _Account:
    with context.sessions() as session:
        settings = db.get_settings(session, user_id)
        if settings is None:
            raise NotReady("choose a fiat with PATCH /config first")
        record = db.get_credentials(session, user_id)
        if record is None:
            raise NotReady("register a Kraken key with POST /credentials first")
        policy = Policy(
            allow_sells=allow_sells,
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


def _plan(context: ExecutionContext, account: _Account, private) -> Planned:
    """Read the account, run the engine, and size each leg against Kraken's minimum.

    Raises `PortfolioUnavailable` when any read fails.
    """
    view = read_portfolio(context.public_kraken(), private, account.fiat, account.targets)
    metas = context.catalog.pairs()
    if metas is None:
        raise PortfolioUnavailable("asset pairs")
    places = (context.catalog.decimals() or {}).get(account.fiat)
    if places is None:
        raise PortfolioUnavailable("asset decimals")
    managed = {holding.asset: holding for holding in view.holdings if holding.managed}
    pair_of = {target.asset: target.pair for target in account.targets}
    target_of = {target.asset: target.target_pct for target in account.targets}
    plan = reconcile(
        {asset: holding.amount for asset, holding in managed.items()},
        {asset: holding.price for asset, holding in managed.items()},
        target_of,
        view.cash,
        account.policy,
    )

    legs: list[PlannedLeg] = []
    for leg in plan.legs:
        pair = pair_of[leg.asset]
        meta = metas.get(pair)
        if meta is None or not meta.tradable:
            legs.append(
                PlannedLeg(
                    leg.asset, pair, leg.side, leg.amount_fiat, None, f"kraken does not trade {pair} now"
                )
            )
            continue
        holding = managed[leg.asset]
        amount = round_cost(meta, leg.amount_fiat)
        volume = None
        if leg.side is Side.SELL:
            held = round_volume(meta, holding.amount)
            # An exit sells everything: sized from a price, it would leave dust Kraken
            # will not take. Any other sell never asks for more than is held.
            if target_of[leg.asset] == ZERO:
                volume = held
            else:
                volume = min(volume_from_fiat(meta, leg.amount_fiat, holding.price), held)
        minimum = max(minimum_fiat(meta, holding.price), account.floor)
        note = None
        if amount < minimum:
            note = (
                f"{plain_amount(amount)} {account.fiat} is below the minimum "
                f"of {plain_amount(minimum)} {account.fiat}"
            )
        legs.append(PlannedLeg(leg.asset, pair, leg.side, amount, minimum, note, volume, meta))
    return Planned(view=view, legs=tuple(legs), free_cash=_free_cash(view), fiat_places=places)


def _free_cash(view: PortfolioView) -> Decimal:
    """Cash above the cash target. The engine's `investable_cash`, from the same valuation."""
    wanted = view.managed_value * view.cash_target_pct / HUNDRED
    excess = view.cash - wanted
    return excess if excess > ZERO else ZERO


def _run(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    reason: OrderReason,
    decide: Decision,
    operation: Operation,
    trigger: Trigger,
) -> EvaluationResult:
    with context.sessions() as session:
        evaluation_id = db.start_evaluation(
            session, user_id, context.now(), operation=operation, trigger=trigger
        ).id
    log: list[str] = []
    legs: list[LegResult] = []
    blocked: list[bool] = []
    status = EvaluationStatus.ERROR
    try:
        status = _evaluate(context, user_id, account, private, reason, decide, log, legs, blocked)
    except PortfolioUnavailable as exc:
        status = EvaluationStatus.KRAKEN_UNAVAILABLE
        log.append(f"kraken did not return {exc}; nothing was sent")
    finally:
        with context.sessions() as session:
            db.finish_evaluation(session, evaluation_id, status, context.now(), "\n".join(log) or None)
    return EvaluationResult(
        status=status, preview=False, legs=tuple(legs), messages=tuple(log), lookup_failed=any(blocked)
    )


def _evaluate(
    context: ExecutionContext,
    user_id: uuid.UUID,
    account: _Account,
    private,
    reason: OrderReason,
    decide: Decision,
    log: list[str],
    legs: list[LegResult],
    blocked: list[bool],
) -> EvaluationStatus:
    resolution = resolve_pending(context.sessions, private, user_id, context.now())
    log.extend(resolution.messages)
    if not resolution.clear:
        log.append(UNRESOLVED_MESSAGE)
        blocked.append(resolution.lookup_failed)
        return EvaluationStatus.UNRESOLVED

    planned = _plan(context, account, private)
    with context.sessions() as session:
        snapshot_id = db.keep_snapshot(
            session,
            user_id,
            as_of=context.now(),
            fiat=account.fiat,
            total_value=planned.view.managed_value,
            cash=planned.view.cash,
            holdings=planned.view.snapshot_json(),
        ).id

    verdict = decide(planned, log)
    if verdict is not None:
        return verdict

    pin = _Pin(context, user_id, snapshot_id)
    stopped = _send_all(context, user_id, private, planned, reason, account.fiat, log, legs, pin)
    if stopped:
        return EvaluationStatus.STOPPED
    if any(leg.status is LegStatus.FAILED for leg in legs):
        return EvaluationStatus.PARTIAL
    if any(leg.status is not LegStatus.SKIPPED for leg in legs):
        return EvaluationStatus.DONE
    if not legs:
        # Skipped legs log their own notes; an empty plan would otherwise leave no trace.
        log.append("the plan has no orders; nothing was sent")
    return EvaluationStatus.NOTHING_TO_DO


def _send_all(
    context: ExecutionContext,
    user_id: uuid.UUID,
    private,
    planned: Planned,
    reason: OrderReason,
    fiat: str,
    log: list[str],
    legs: list[LegResult],
    pin: Callable[[], None],
) -> bool:
    """Sells first, then the buys inside what there is to spend (spec §7.2).

    True when an unknown answer stopped it. The budget is read from the ledger, not from
    the balance, which may not reflect the sells yet (§9.2).
    """
    budget = planned.free_cash
    stopped = False
    for leg in planned.legs:
        if leg.side is not Side.SELL:
            continue
        result, stopped = _attempt(context, user_id, private, leg, reason, stopped, pin)
        legs.append(result)
        log.append(_describe(result, fiat))
        if result.status is LegStatus.FILLED:
            # `fciq`: the fee is in fiat. Counted as the ledger rounds it, not as the order
            # reports it: a buy of the reported amount was refused for 0.00007 EUR.
            budget += credited(result.cost or ZERO, result.fee or ZERO, planned.fiat_places)

    buys = [leg for leg in planned.legs if leg.side is Side.BUY]
    for leg in _within(buys, budget, fiat):
        result, stopped = _attempt(context, user_id, private, leg, reason, stopped, pin)
        legs.append(result)
        log.append(_describe(result, fiat))
    return stopped


def _within(buys: list[PlannedLeg], budget: Decimal, fiat: str) -> list[PlannedLeg]:
    """The buys, shrunk in proportion when together they ask for more than `budget`.

    A rebalance's buys are sized from prices read before the sells, and a sell raises less
    than planned: Kraken keeps a fee, and the price moves. One factor for every buy keeps
    the plan's proportions. A buy that shrinks below its minimum is skipped.
    """
    asked = sum((leg.amount for leg in buys if leg.note is None), ZERO)
    if asked <= budget:
        return buys
    factor = budget / asked
    fitted: list[PlannedLeg] = []
    for leg in buys:
        if leg.note is not None:
            fitted.append(leg)
            continue
        amount = round_cost(leg.meta, leg.amount * factor)
        note = None
        if amount < leg.minimum:
            note = (
                f"after the sells, {plain_amount(amount)} {fiat} is below the minimum "
                f"of {plain_amount(leg.minimum)} {fiat}"
            )
        fitted.append(replace(leg, amount=amount, note=note))
    return fitted


def _attempt(
    context: ExecutionContext,
    user_id: uuid.UUID,
    private,
    leg: PlannedLeg,
    reason: OrderReason,
    stopped: bool,
    pin: Callable[[], None],
) -> tuple[LegResult, bool]:
    """Send one leg unless it is skipped or an earlier answer was lost. Returns `stopped`."""
    if leg.note is not None:
        return _skipped(leg, leg.note), stopped
    if stopped:
        return _skipped(leg, "not sent: an earlier order's answer is unknown"), True
    pin()
    result = _send(context, user_id, private, leg, reason)
    # An unknown answer leaves no txid. The balance is ambiguous until resolved.
    return result, result.status is LegStatus.PENDING and result.txid is None


def _place(private, leg: PlannedLeg, cl_ord_id: str, *, validate: bool = False) -> Placement:
    """A buy is an amount of fiat (`viqc`); a sell is a volume of the asset (spec §9.1)."""
    if leg.side is Side.BUY:
        return private.add_order(leg.pair, "buy", leg.amount, cl_ord_id, in_quote=True, validate=validate)
    return private.add_order(leg.pair, "sell", leg.volume, cl_ord_id, validate=validate)


def _send(
    context: ExecutionContext, user_id: uuid.UUID, private, leg: PlannedLeg, reason: OrderReason
) -> LegResult:
    cl_ord_id = new_cl_ord_id()
    with context.sessions() as session:
        db.record_attempt(
            session,
            user_id,
            cl_ord_id,
            pair=leg.pair,
            asset=leg.asset,
            side=leg.side,
            reason=reason,
            requested_fiat=leg.amount,
            attempted_at=context.now(),
        )
    # Committed. From here a lost answer leaves a row to resolve, not a gap (spec §9.2).
    placement = _place(private, leg, cl_ord_id)

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


def _from_row(leg: PlannedLeg, order: Order) -> LegResult:
    return LegResult(
        asset=leg.asset,
        pair=leg.pair,
        side=leg.side,
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
        volume=leg.volume,
    )


def _skipped(leg: PlannedLeg, note: str) -> LegResult:
    return LegResult(
        leg.asset,
        leg.pair,
        leg.side,
        leg.amount,
        leg.minimum,
        LegStatus.SKIPPED,
        note=note,
        volume=leg.volume,
    )


def _describe(leg: LegResult, fiat: str) -> str:
    text = f"{leg.asset}: {leg.side.value} of {plain_amount(leg.amount_fiat)} {fiat} {leg.status.value}"
    if leg.error:
        text += f" ({leg.error})"
    if leg.note:
        text += f": {leg.note}"
    return text


def _preview(context: ExecutionContext, user_id: uuid.UUID, account: _Account, private) -> EvaluationResult:
    """Read, plan and have Kraken validate. Writes nothing, takes no lock, resolves nothing."""
    with context.sessions() as session:
        unresolved = db.has_unresolved(session, user_id)
    if unresolved:
        return EvaluationResult(EvaluationStatus.UNRESOLVED, preview=True, messages=(UNRESOLVED_MESSAGE,))
    try:
        planned = _plan(context, account, private)
    except PortfolioUnavailable as exc:
        return EvaluationResult(
            EvaluationStatus.KRAKEN_UNAVAILABLE, preview=True, messages=(f"kraken did not return {exc}",)
        )

    verdicts = {PlacementOutcome.VALIDATED: LegStatus.VALIDATED, PlacementOutcome.REFUSED: LegStatus.REJECTED}
    legs: list[LegResult] = []
    for leg in planned.legs:
        if leg.note is not None:
            legs.append(_skipped(leg, leg.note))
            continue
        placement = _place(private, leg, new_cl_ord_id(), validate=True)
        status = verdicts.get(placement.outcome, LegStatus.UNCHECKED)
        legs.append(
            LegResult(leg.asset, leg.pair, leg.side, leg.amount, leg.minimum, status, error=placement.error)
        )
    return EvaluationResult(EvaluationStatus.PREVIEW, preview=True, legs=tuple(legs))
