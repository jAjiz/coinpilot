"""Sign-in with Google, the refresh of a sign-in, and who the caller is.

The login state and the PKCE verifier cross Google's redirect in a signed cookie scoped
to the callback path, so no table holds half-finished logins.

A refused refresh or logout is returned, never raised. Every route runs in one
transaction, and an exception would roll back a revocation made on the way to the
refusal.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

import core.database as db
from api.context import AppContext
from api.deps import ACCESS_COOKIE, Ctx, CurrentUser, Db
from api.schemas import MeOut, RefreshIn, TokenPairOut
from core import google
from core.db.types import UserStatus
from core.refresh import IssuedRefresh, RefreshFailure, revoke, rotate, start_family
from core.tokens import LOGIN_STATE_TTL, TokenInvalid

router = APIRouter(prefix="/auth", tags=["auth"])

PROVIDER = "google"
LOGIN_COOKIE = "coinpilot_login"
LOGIN_COOKIE_PATH = "/auth/callback"
REFRESH_COOKIE = "coinpilot_refresh"
# Sent to the auth routes only. `Strict`: a request another site starts never carries it.
REFRESH_COOKIE_PATH = "/auth"
START_AGAIN = "the login expired or was not started here; start again"


def _only_google(provider: str) -> None:
    if provider != PROVIDER:
        raise HTTPException(404, "unknown provider")


def _presented_refresh(request: Request, body: RefreshIn | None) -> str | None:
    """The body first, for an application; the cookie second, for a browser."""
    if body is not None and body.refresh_token is not None:
        return body.refresh_token.get_secret_value()
    return request.cookies.get(REFRESH_COOKIE)


def _signed_in(context: AppContext, user_id: uuid.UUID, refresh: IssuedRefresh) -> JSONResponse:
    access = context.signer.issue(user_id)
    body = TokenPairOut(
        access_token=access.value,
        expires_at=access.expires_at,
        refresh_token=refresh.value,
        refresh_expires_at=refresh.expires_at,
    )
    response = JSONResponse(body.model_dump(mode="json"))
    response.set_cookie(
        ACCESS_COOKIE,
        access.value,
        max_age=int(context.config.jwt_ttl.total_seconds()),
        path="/",
        httponly=True,
        secure=context.config.cookie_secure,
        # `Lax`, not `Strict`: it must arrive on the navigation back from Google.
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh.value,
        # What is left of the sign-in, not a fresh lifetime: the expiry is absolute.
        max_age=int((refresh.expires_at - context.now()).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=context.config.cookie_secure,
        samesite="strict",
    )
    return response


def _signed_out(status_code: int, detail: str | None = None) -> Response:
    if detail is None:
        response = Response(status_code=status_code)
    else:
        response = JSONResponse({"detail": detail}, status_code=status_code)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return response


@router.get("/login/{provider}")
def login(provider: str, context: Ctx) -> RedirectResponse:
    _only_google(provider)
    started = google.new_login()
    response = RedirectResponse(google.authorization_url(context.config.google, started), status_code=302)
    response.set_cookie(
        LOGIN_COOKIE,
        context.signer.issue_login_state(started),
        max_age=int(LOGIN_STATE_TTL.total_seconds()),
        path=LOGIN_COOKIE_PATH,
        httponly=True,
        secure=context.config.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/callback/{provider}", response_model=TokenPairOut)
def callback(
    provider: str,
    request: Request,
    session: Db,
    context: Ctx,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> JSONResponse:
    _only_google(provider)
    if error:
        raise HTTPException(400, "google did not grant the login")
    cookie = request.cookies.get(LOGIN_COOKIE)
    if not cookie or not code or not state:
        raise HTTPException(400, START_AGAIN)
    try:
        expected = context.signer.verify_login_state(cookie)
    except TokenInvalid:
        raise HTTPException(400, START_AGAIN) from None
    if not secrets.compare_digest(expected.state, state):
        raise HTTPException(400, "the login state does not match; start again")

    try:
        identity = google.exchange_code(context.google_http, context.config.google, code, expected.verifier)
    except google.GoogleLoginFailed as exc:
        raise HTTPException(400, str(exc)) from None

    user = db.get_user_by_identity(session, PROVIDER, identity.subject)
    if user is None:
        user = db.create_user(session, PROVIDER, identity.subject, identity.email)
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "this account is disabled")

    refresh = start_family(session, user.id, context.now(), context.config.refresh_ttl)
    response = _signed_in(context, user.id, refresh)
    response.delete_cookie(LOGIN_COOKIE, path=LOGIN_COOKIE_PATH)
    return response


@router.post("/refresh", response_model=TokenPairOut)
def refresh(request: Request, session: Db, context: Ctx, body: RefreshIn | None = None) -> Response:
    """Trades a refresh token for a new pair. The token presented is used up."""
    presented = _presented_refresh(request, body)
    if presented is None:
        return _signed_out(401, "no refresh token")

    now = context.now()
    outcome = rotate(session, presented, now)
    if isinstance(outcome, RefreshFailure):
        return _signed_out(401, f"the refresh token is {outcome.value}; sign in again")

    user = db.get_user(session, outcome.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        db.revoke_family(session, outcome.family_id, now)
        return _signed_out(403, "this account is disabled")
    return _signed_in(context, user.id, outcome)


@router.post("/logout", status_code=204)
def logout(request: Request, session: Db, context: Ctx, body: RefreshIn | None = None) -> Response:
    """Ends this sign-in: its refresh tokens are revoked and both cookies removed.

    An access token already issued keeps working until it expires, at most
    `JWT_TTL_MINUTES` later. That is the trade of every stateless access token (spec §15).
    """
    presented = _presented_refresh(request, body)
    if presented is not None:
        revoke(session, presented, context.now())
    return _signed_out(204)


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return MeOut.model_validate(user)
