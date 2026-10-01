"""The last snapshot, shown at once, and a refresh that reads Kraken now (spec §10.4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import PortfolioOut
from core.crypto import CredentialsUnreadable, Sealed
from core.db.models import PortfolioSnapshot
from core.portfolio import plain_amount
from core.reading import PortfolioUnavailable, read_portfolio

logger = logging.getLogger("coinpilot.api")

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _out(snapshot: PortfolioSnapshot) -> PortfolioOut:
    return PortfolioOut(
        as_of=snapshot.as_of,
        fiat=snapshot.fiat,
        total_value=plain_amount(snapshot.total_value),
        cash=plain_amount(snapshot.cash),
        holdings=snapshot.holdings,
    )


@router.get("", response_model=PortfolioOut)
def read(user: CurrentUser, session: Db) -> PortfolioOut:
    snapshot = db.latest_snapshot(session, user.id)
    if snapshot is None:
        raise HTTPException(404, "no snapshot yet; POST /portfolio/refresh to take one")
    return _out(snapshot)


@router.post("/refresh", response_model=PortfolioOut)
def refresh(user: CurrentUser, session: Db, context: Ctx) -> PortfolioOut:
    settings = db.get_settings(session, user.id)
    if settings is None:
        raise HTTPException(409, "choose a fiat with PATCH /config first")
    record = db.get_credentials(session, user.id)
    if record is None:
        raise HTTPException(409, "register a Kraken key with POST /credentials first")

    try:
        credentials = context.cipher.unseal(
            user.id, Sealed(record.ciphertext, record.nonce, record.key_version)
        )
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user.id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None

    try:
        view = read_portfolio(
            context.public_kraken(),
            context.kraken_for(credentials),
            settings.fiat,
            db.list_assets(session, user.id),
        )
    except PortfolioUnavailable as exc:
        raise HTTPException(503, f"kraken did not return {exc}; nothing was recorded") from None

    snapshot = db.record_snapshot(
        session,
        user.id,
        as_of=context.now(),
        fiat=settings.fiat,
        total_value=view.managed_value,
        cash=view.cash,
        holdings=view.snapshot_json(),
    )
    return _out(snapshot)
