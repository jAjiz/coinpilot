"""The rebalance operation and its proposal (spec §3.4, §8).

A rebalance sells, and a sell cannot be undone. So a request to rebalance never sends
anything: `propose` computes the plan and keeps it as the user's one live proposal, and
`approve` executes it once the user has read it. The one exception is the user who turned
automatic rebalancing on, which is the authorisation: for them the scheduler calls
`rebalance_now`. The executor sends; this module decides whether there is anything to send.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

import core.database as db
from core.db.models import Proposal
from core.db.types import Operation, OrderReason, ProposalStatus, ProposalTrigger, Trigger
from core.execution import EvaluationResult, EvaluationStatus, ExecutionContext, Planned, evaluate
from core.proposal_plan import has_orders, is_material, plan_document


@dataclass(frozen=True)
class ProposalState:
    version: int
    status: str
    trigger: str
    plan: dict[str, object]
    updated_at: datetime


@dataclass(frozen=True)
class RebalanceResult:
    evaluation: EvaluationResult
    # The live proposal as the evaluation left it. `None` when there is none.
    proposal: ProposalState | None


class NoProposal(Exception):
    """There is no live proposal to approve. Nothing was read."""


class StaleVersion(Exception):
    """The approval named a version that is not the live one. Nothing was read."""

    def __init__(self, current: ProposalState) -> None:
        super().__init__(f"the live proposal is version {current.version}")
        self.current = current


def current(context: ExecutionContext, user_id: uuid.UUID) -> ProposalState | None:
    with context.sessions() as session:
        return _state(db.get_live_proposal(session, user_id))


def withdraw(context: ExecutionContext, user_id: uuid.UUID) -> bool:
    """False when there was no live proposal. An executed one is not withdrawn."""
    with context.sessions() as session:
        if db.get_live_proposal(session, user_id) is None:
            return False
        return db.withdraw(session, user_id)


def propose(
    context: ExecutionContext, user_id: uuid.UUID, *, trigger: Trigger = Trigger.API
) -> RebalanceResult:
    """Compute a rebalance and keep it as the live proposal. Never sends an order.

    The scheduler calls it too, with `Trigger.SCHEDULER`, for a user whose automatic
    rebalancing is off. Raises what `evaluate` raises.
    """
    proposal_trigger = ProposalTrigger.SCHEDULED if trigger is Trigger.SCHEDULER else ProposalTrigger.MANUAL

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus:
        document = plan_document(planned.view.fiat, planned.legs)
        with context.sessions() as session:
            _keep(session, user_id, document, proposal_trigger, log)
        return EvaluationStatus.PROPOSED if has_orders(document) else EvaluationStatus.NOTHING_TO_DO

    result = evaluate(
        context,
        user_id,
        allow_sells=True,
        reason=OrderReason.REBALANCE,
        decide=decide,
        operation=Operation.PROPOSE,
        trigger=trigger,
    )
    return RebalanceResult(result, current(context, user_id))


def approve(context: ExecutionContext, user_id: uuid.UUID, version: int) -> RebalanceResult:
    """Execute the live proposal, if `version` is still it and its plan has not moved.

    The version is checked first, before anything is read from Kraken. Under the lock the
    plan is computed again: a material change is stored as the next version, and the
    evaluation ends `SUPERSEDED` with nothing sent. Otherwise the fresh plan executes,
    with today's amounts (spec §8).
    """
    with context.sessions() as session:
        slot = db.get_live_proposal(session, user_id)
        if slot is None:
            raise NoProposal(str(user_id))
        if slot.version != version:
            raise StaleVersion(_state(slot))

    executing = False

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus | None:
        nonlocal executing
        document = plan_document(planned.view.fiat, planned.legs)
        with context.sessions() as session:
            slot = db.get_live_proposal(session, user_id)
            if slot is None or slot.version != version:
                log.append("the proposal changed before it could execute; nothing was sent")
                return EvaluationStatus.SUPERSEDED
            if not has_orders(document):
                # `_keep` withdraws it, and says why.
                _keep(session, user_id, document, ProposalTrigger(slot.trigger), log)
                return EvaluationStatus.SUPERSEDED
            if is_material(slot.plan, document):
                _keep(session, user_id, document, ProposalTrigger(slot.trigger), log)
                log.append("the plan changed since it was proposed; nothing was sent")
                return EvaluationStatus.SUPERSEDED
            # What executes is today's plan, recorded under the version approved.
            db.save_proposal(
                session, user_id, plan=document, trigger=ProposalTrigger(slot.trigger), version=version
            )
            db.set_status(session, user_id, ProposalStatus.EXECUTING)
        executing = True
        log.append(f"proposal version {version} approved; executing")
        return None

    try:
        result = evaluate(
            context,
            user_id,
            allow_sells=True,
            reason=OrderReason.REBALANCE,
            decide=decide,
            operation=Operation.APPROVE,
            trigger=Trigger.API,
        )
    finally:
        # Even when the evaluation raised: orders may have gone out, and a proposal left
        # EXECUTING would be neither live nor done.
        if executing:
            with context.sessions() as session:
                db.set_status(session, user_id, ProposalStatus.EXECUTED)
    return RebalanceResult(result, current(context, user_id))


def rebalance_now(context: ExecutionContext, user_id: uuid.UUID) -> EvaluationResult:
    """Execute a rebalance without an approval. Only the scheduler calls this, and only for
    a user with automatic rebalancing on: enabling it was the authorisation (spec §3.4).

    The settings are read again under the lock, just before anything is sent: a user who
    switched it off, or paused, since the scheduler chose them is not sold from. A live
    proposal is withdrawn first. It was computed earlier, and what executes is today's
    plan; left live, it would offer an approval of something already done.
    """

    def decide(planned: Planned, log: list[str]) -> EvaluationStatus | None:
        with context.sessions() as session:
            settings = db.get_settings(session, user_id)
            if settings is None or not settings.auto_rebalance_enabled:
                log.append("automatic rebalancing was switched off; nothing was sent")
                return EvaluationStatus.NOTHING_TO_DO
            if settings.paused:
                log.append("scheduled operations are paused; nothing was sent")
                return EvaluationStatus.NOTHING_TO_DO
            slot = db.get_live_proposal(session, user_id)
            if slot is not None:
                db.withdraw(session, user_id)
                log.append(f"automatic rebalancing is on; proposal version {slot.version} was withdrawn")
        return None

    return evaluate(
        context,
        user_id,
        allow_sells=True,
        reason=OrderReason.REBALANCE,
        decide=decide,
        operation=Operation.REBALANCE,
        trigger=Trigger.SCHEDULER,
    )


def _why_nothing(document: Mapping, log: list[str]) -> str:
    """Why a plan has nothing to send. No leg at all: nothing drifts past the threshold. Legs
    that are all skipped: the drift is there, and each is logged with the note that stopped it."""
    skipped = [leg for leg in document["legs"] if leg["note"] is not None]
    if not skipped:
        return "the drift is below the threshold"
    for leg in skipped:
        log.append(f"{leg['asset']}: {leg['side']} skipped, {leg['note']}")
    return "no order can be sent"


def _keep(
    session: Session, user_id: uuid.UUID, document: Mapping, trigger: ProposalTrigger, log: list[str]
) -> None:
    """Keep `document` as the live proposal, or withdraw the proposal when it is empty.

    The version moves only on a material change (spec §8), and an unchanged plan is not
    rewritten: the stored plan stays the one the user read. The version never goes back:
    a proposal after a withdrawn or executed one takes the next number, so an approval
    meant for the old one cannot reach it.
    """
    slot = db.get_proposal(session, user_id)
    live = slot is not None and slot.status == ProposalStatus.LIVE
    if not has_orders(document):
        reason = _why_nothing(document, log)
        if live:
            db.withdraw(session, user_id)
            log.append(f"{reason}; the proposal was withdrawn")
        else:
            log.append(f"{reason}; nothing to propose")
        return
    if live and not is_material(slot.plan, document):
        log.append(f"proposal version {slot.version} still stands")
        return
    version = 1 if slot is None else slot.version + 1
    db.save_proposal(session, user_id, plan=dict(document), trigger=trigger, version=version)
    log.append(f"proposal version {version}")


def _state(row: Proposal | None) -> ProposalState | None:
    if row is None:
        return None
    return ProposalState(
        version=row.version,
        status=row.status,
        trigger=row.trigger,
        plan=row.plan,
        updated_at=row.updated_at,
    )
