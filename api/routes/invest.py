"""Invest free cash now (spec §11). A preview has Kraken validate and records nothing."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import Ctx, CurrentUser
from api.evaluation import evaluation_errors, leg_out, unfinished
from api.schemas import InvestOut
from core.execution import invest

router = APIRouter(prefix="/invest", tags=["invest"])


@router.post("", response_model=InvestOut)
def invest_now(user: CurrentUser, context: Ctx, preview: bool = False) -> InvestOut | JSONResponse:
    with evaluation_errors(user.id):
        result = invest(context, user.id, preview=preview)
    refused = unfinished(result)
    if refused is not None:
        return refused
    return InvestOut(
        status=result.status.value,
        preview=result.preview,
        legs=[leg_out(leg) for leg in result.legs],
        messages=list(result.messages),
    )
