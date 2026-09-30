"""Target weights. An asset is refused here if Kraken cannot trade it against the fiat (§3.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import AssetIn, AssetOut, AssetsOut
from core.db.models import AssetConfig
from core.markets import resolve_pair, short_name
from engine.types import HUNDRED, ZERO

router = APIRouter(prefix="/assets", tags=["assets"])

KRAKEN_DOWN = "kraken could not be reached; nothing was changed"


@router.get("", response_model=AssetsOut)
def list_assets(user: CurrentUser, session: Db) -> AssetsOut:
    rows = db.list_assets(session, user.id)
    return AssetsOut(
        assets=[AssetOut.model_validate(row) for row in rows],
        cash_target_pct=HUNDRED - sum((row.target_pct for row in rows), ZERO),
    )


@router.put("/{asset}", response_model=AssetOut)
def put_asset(asset: str, body: AssetIn, user: CurrentUser, session: Db, context: Ctx) -> AssetConfig:
    # The fiat never changes once chosen, so reading it needs no lock.
    settings = db.get_settings(session, user.id)
    if settings is None:
        raise HTTPException(409, "choose a fiat with PATCH /config first")

    names = context.catalog.asset_names()
    if names is None:
        raise HTTPException(503, KRAKEN_DOWN)
    code = short_name(asset, names)
    if code is None:
        raise HTTPException(422, f"kraken lists no asset called {asset!r}")
    if code == settings.fiat:
        raise HTTPException(422, "the fiat is the cash target; it cannot also be an asset")
    pairs = context.catalog.pairs()
    if pairs is None:
        raise HTTPException(503, KRAKEN_DOWN)
    meta = resolve_pair(code, settings.fiat, names, pairs)
    if meta is None:
        raise HTTPException(422, f"kraken has no tradable {code}/{settings.fiat} pair")

    # Locked only now, after every call to Kraken: the lock serialises the sum check and
    # the write, and nothing slower than the database happens while it is held.
    db.lock_settings(session, user.id)
    others = sum((row.target_pct for row in db.list_assets(session, user.id) if row.asset != code), ZERO)
    if others + body.target_pct > HUNDRED:
        raise HTTPException(422, f"the weights would sum to {others + body.target_pct}; the limit is 100")

    return db.upsert_asset(session, user.id, asset=code, pair=meta.pair, target_pct=body.target_pct)


@router.delete("/{asset}", status_code=204)
def delete_asset(asset: str, user: CurrentUser, session: Db, context: Ctx) -> Response:
    # The same names `PUT` accepts. With Kraken unreachable, the stored short name still works.
    names = context.catalog.asset_names()
    code = (short_name(asset, names) if names is not None else None) or asset.strip().upper()
    if not db.delete_asset(session, user.id, code):
        raise HTTPException(404, "that asset has no weight")
    return Response(status_code=204)
