"""What happened: the orders attempted and the evaluations run. Both empty until phase 5."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

import core.database as db
from api.deps import CurrentUser, Db
from api.schemas import EvaluationOut, OrderOut

router = APIRouter(tags=["history"])

Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("/orders", response_model=list[OrderOut])
def orders(
    user: CurrentUser,
    session: Db,
    limit: Limit = 50,
    session_id: Annotated[uuid.UUID | None, Query(alias="session")] = None,
) -> list[OrderOut]:
    rows = db.list_orders(session, user.id, limit=limit, session_id=session_id)
    return [OrderOut.model_validate(row) for row in rows]


@router.get("/sessions", response_model=list[EvaluationOut])
def sessions(user: CurrentUser, session: Db, limit: Limit = 50) -> list[EvaluationOut]:
    return [EvaluationOut.model_validate(row) for row in db.list_evaluations(session, user.id, limit=limit)]
