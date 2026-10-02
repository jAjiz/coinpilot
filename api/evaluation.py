"""What `POST /invest`, `POST /rebalance` and `POST /proposal/approve` share: the shape
of a leg, and the answers when an evaluation cannot run."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from api.schemas import LegOut
from core.crypto import CredentialsUnreadable
from core.execution import EvaluationBusy, EvaluationResult, EvaluationStatus, LegResult, NotReady
from core.portfolio import plain_amount

logger = logging.getLogger("coinpilot.api")


def plain(value: Decimal | None) -> str | None:
    return None if value is None else plain_amount(value)


def leg_out(leg: LegResult) -> LegOut:
    return LegOut(
        asset=leg.asset,
        pair=leg.pair,
        side=leg.side.value,
        amount_fiat=plain_amount(leg.amount_fiat),
        minimum_fiat=plain(leg.minimum_fiat),
        status=leg.status.value,
        cl_ord_id=leg.cl_ord_id,
        txid=leg.txid,
        cost=plain(leg.cost),
        executed_volume=plain(leg.executed_volume),
        executed_price=plain(leg.executed_price),
        fee=plain(leg.fee),
        error=leg.error,
        note=leg.note,
        volume=plain(leg.volume),
    )


@contextmanager
def evaluation_errors(user_id: uuid.UUID) -> Iterator[None]:
    """The evaluations that never started: busy, not configured, or a key that does not open."""
    try:
        yield
    except EvaluationBusy:
        raise HTTPException(
            409, "an evaluation of this account is already running; try again shortly"
        ) from None
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from None
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user_id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None


def refusal(status_code: int, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, **extra})


def unfinished(result: EvaluationResult) -> JSONResponse | None:
    """The answer for an evaluation that ran, was recorded, and could not compute.

    Returned, not raised: raising would roll back the request's transaction, which must
    never be what decides whether an evaluation's record survives.
    """
    if result.status is EvaluationStatus.UNRESOLVED:
        return refusal(409, "an earlier order is still unresolved; try again in a few minutes")
    if result.status is EvaluationStatus.KRAKEN_UNAVAILABLE:
        return refusal(503, "kraken could not be read; nothing was sent")
    return None
