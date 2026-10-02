"""Invest free cash now (spec §11). A preview has Kraken validate and records nothing."""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.deps import Ctx, CurrentUser
from api.schemas import InvestOut, LegOut
from core.crypto import CredentialsUnreadable
from core.execution import EvaluationBusy, EvaluationResult, EvaluationStatus, LegResult, NotReady, invest
from core.portfolio import plain_amount

logger = logging.getLogger("coinpilot.api")

router = APIRouter(prefix="/invest", tags=["invest"])


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else plain_amount(value)


def _leg(leg: LegResult) -> LegOut:
    return LegOut(
        asset=leg.asset,
        pair=leg.pair,
        amount_fiat=plain_amount(leg.amount_fiat),
        minimum_fiat=_plain(leg.minimum_fiat),
        status=leg.status.value,
        cl_ord_id=leg.cl_ord_id,
        txid=leg.txid,
        cost=_plain(leg.cost),
        executed_volume=_plain(leg.executed_volume),
        executed_price=_plain(leg.executed_price),
        fee=_plain(leg.fee),
        error=leg.error,
        note=leg.note,
    )


def _out(result: EvaluationResult) -> InvestOut:
    return InvestOut(
        status=result.status.value,
        preview=result.preview,
        legs=[_leg(leg) for leg in result.legs],
        messages=list(result.messages),
    )


def _refusal(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@router.post("", response_model=InvestOut)
def invest_now(user: CurrentUser, context: Ctx, preview: bool = False) -> InvestOut | JSONResponse:
    try:
        result = invest(context, user.id, preview=preview)
    except EvaluationBusy:
        raise HTTPException(
            409, "an evaluation of this account is already running; try again shortly"
        ) from None
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from None
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user.id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None

    # Returned, not raised: these are evaluations that ran and were recorded. Raising would
    # roll back the request's transaction, which must never be what decides whether an
    # evaluation's record survives.
    if result.status is EvaluationStatus.UNRESOLVED:
        return _refusal(409, "an earlier order is still unresolved; try again in a few minutes")
    if result.status is EvaluationStatus.KRAKEN_UNAVAILABLE:
        return _refusal(503, "kraken could not be read; nothing was sent")
    return _out(result)
