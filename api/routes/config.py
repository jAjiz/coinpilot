"""A user's settings. The first PATCH creates them and chooses the fiat, which then never changes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import core.database as db
from api.deps import CurrentUser, Db
from api.schemas import ConfigOut, ConfigPatch
from core.db.models import UserSettings
from core.db.types import CadenceMode
from core.markets import SUPPORTED_FIATS

router = APIRouter(prefix="/config", tags=["config"])

_CADENCES = ("invest", "rebalance")


def _cadence_problem(prefix: str, merged: dict[str, object]) -> str | None:
    """An INTERVAL cadence needs a length and an anchor. MIN ignores both."""
    if merged[f"{prefix}_cadence_mode"] != CadenceMode.INTERVAL:
        return None
    days = merged[f"{prefix}_interval_days"] or 0
    months = merged[f"{prefix}_interval_months"] or 0
    if days + months == 0:
        return f"an INTERVAL {prefix} cadence needs interval_days or interval_months"
    if merged[f"{prefix}_cadence_anchor"] is None:
        return f"an INTERVAL {prefix} cadence needs a cadence_anchor"
    return None


def _merged(settings: UserSettings, changes: dict[str, object]) -> dict[str, object]:
    fields = [
        f"{prefix}_{name}"
        for prefix in _CADENCES
        for name in ("cadence_mode", "interval_days", "interval_months", "cadence_anchor")
    ]
    return {name: getattr(settings, name) for name in fields} | changes


@router.get("", response_model=ConfigOut)
def read_config(user: CurrentUser, session: Db) -> UserSettings:
    settings = db.get_settings(session, user.id)
    if settings is None:
        raise HTTPException(404, "no settings yet; PATCH /config with a fiat to create them")
    return settings


@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch, user: CurrentUser, session: Db) -> UserSettings:
    changes = body.model_dump(exclude_unset=True)
    fiat = changes.pop("fiat", None)
    fiat = fiat.strip().upper() if isinstance(fiat, str) else None

    settings = db.lock_settings(session, user.id)
    if settings is None:
        if fiat is None:
            raise HTTPException(409, "the first PATCH /config must choose a fiat")
        if fiat not in SUPPORTED_FIATS:
            raise HTTPException(422, f"supported fiats are {', '.join(SUPPORTED_FIATS)}")
        settings = db.create_settings(session, user.id, fiat=fiat)
    elif fiat is not None and fiat != settings.fiat:
        raise HTTPException(422, "the fiat cannot be changed")

    merged = _merged(settings, changes)
    for prefix in _CADENCES:
        problem = _cadence_problem(prefix, merged)
        if problem is not None:
            raise HTTPException(422, problem)

    if changes:
        settings = db.update_settings(session, user.id, **changes)
    return settings
