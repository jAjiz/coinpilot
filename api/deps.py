"""What a route can ask for: the context, a database session, the signed-in user."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

import core.database as db
from api.context import AppContext
from core.db.models import User
from core.db.types import UserStatus
from core.tokens import TokenInvalid

ACCESS_COOKIE = "coinpilot_token"


def _context(request: Request) -> AppContext:
    return request.app.state.context


Ctx = Annotated[AppContext, Depends(_context)]


def _session(context: Ctx) -> Iterator[Session]:
    with context.sessions() as session:
        yield session


# Function scope: the transaction commits before the response is sent. With FastAPI's
# default scope it commits afterwards, and a failed commit reaches the client as a 200.
Db = Annotated[Session, Depends(_session, scope="function")]


def _token(request: Request) -> str | None:
    """The bearer header first, for an application; the cookie second, for a browser."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(ACCESS_COOKIE)


def _current_user(request: Request, session: Db, context: Ctx) -> User:
    unauthenticated = HTTPException(401, "not signed in", headers={"WWW-Authenticate": "Bearer"})
    token = _token(request)
    if token is None:
        raise unauthenticated
    try:
        user_id = context.signer.verify(token)
    except TokenInvalid:
        raise unauthenticated from None
    user = db.get_user(session, user_id)
    if user is None:
        raise unauthenticated
    # An access token cannot be revoked. Reading the status on every request is what
    # makes disabling an account take effect now rather than when the token expires.
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "this account is disabled")
    return user


CurrentUser = Annotated[User, Depends(_current_user)]
