"""The rebalance and its proposal (spec §8, §11).

`POST /rebalance` only proposes. What is sold is sold on `POST /proposal/approve`, with
the version the user read.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from api.deps import Ctx, CurrentUser
from api.evaluation import evaluation_errors, leg_out, refusal, unfinished
from api.schemas import ApproveIn, ProposalLegOut, ProposalOut, RebalanceOut
from core.execution import EvaluationStatus
from core.rebalance import (
    NoProposal,
    ProposalState,
    RebalanceResult,
    StaleVersion,
    approve,
    current,
    propose,
    withdraw,
)

router = APIRouter(tags=["proposal"])

NO_PROPOSAL = "there is no live proposal"


def _proposal(state: ProposalState | None) -> ProposalOut | None:
    if state is None:
        return None
    return ProposalOut(
        version=state.version,
        status=state.status,
        trigger=state.trigger,
        fiat=state.plan["fiat"],
        legs=[ProposalLegOut(**leg) for leg in state.plan["legs"]],
        updated_at=state.updated_at,
    )


def _proposal_json(state: ProposalState | None) -> dict | None:
    out = _proposal(state)
    return None if out is None else out.model_dump(mode="json")


def _out(result: RebalanceResult) -> RebalanceOut:
    return RebalanceOut(
        status=result.evaluation.status.value,
        legs=[leg_out(leg) for leg in result.evaluation.legs],
        proposal=_proposal(result.proposal),
        messages=list(result.evaluation.messages),
    )


@router.post("/rebalance", response_model=RebalanceOut)
def rebalance(user: CurrentUser, context: Ctx) -> RebalanceOut | JSONResponse:
    with evaluation_errors(user.id):
        result = propose(context, user.id)
    refused = unfinished(result.evaluation)
    if refused is not None:
        return refused
    return _out(result)


@router.get("/proposal", response_model=ProposalOut)
def read_proposal(user: CurrentUser, context: Ctx) -> ProposalOut:
    state = current(context, user.id)
    if state is None:
        raise HTTPException(404, NO_PROPOSAL)
    return _proposal(state)


@router.post("/proposal/approve", response_model=RebalanceOut)
def approve_proposal(body: ApproveIn, user: CurrentUser, context: Ctx) -> RebalanceOut | JSONResponse:
    try:
        with evaluation_errors(user.id):
            result = approve(context, user.id, body.version)
    except NoProposal:
        raise HTTPException(404, NO_PROPOSAL) from None
    except StaleVersion as exc:
        return refusal(
            409, "that is not the live version; read the proposal again", proposal=_proposal_json(exc.current)
        )

    refused = unfinished(result.evaluation)
    if refused is not None:
        return refused
    if result.evaluation.status is EvaluationStatus.SUPERSEDED:
        # `messages` says why: a new version, or the drift gone and the proposal withdrawn.
        return refusal(
            409,
            "the plan changed since it was proposed; nothing was sent",
            proposal=_proposal_json(result.proposal),
            messages=list(result.evaluation.messages),
        )
    return _out(result)


@router.delete("/proposal", status_code=204)
def withdraw_proposal(user: CurrentUser, context: Ctx) -> Response:
    if not withdraw(context, user.id):
        raise HTTPException(404, NO_PROPOSAL)
    return Response(status_code=204)
