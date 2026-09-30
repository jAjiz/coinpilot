"""Access tokens, refresh token values, and the state that carries a login across Google's redirect.

The access token and the login state are JWTs signed with one secret. A `typ` claim tells
them apart, so neither can be presented where the other is expected. An access token
cannot be revoked, so it is short-lived; the status check on every request, in the API
layer, is what makes disabling an account immediate.

A refresh token is not a JWT. It is a random value the server looks up, which is what
makes it revocable.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
ISSUER = "coinpilot"
AUDIENCE = "coinpilot-api"
ACCESS = "access"
LOGIN_STATE = "login-state"
LOGIN_STATE_TTL = timedelta(minutes=10)
REFRESH_TOKEN_BYTES = 32


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(value: str) -> bytes:
    """What the database stores. Plain SHA-256 is enough for 256 random bits: there is no
    dictionary to guess from, so a slow password hash would only cost time."""
    return hashlib.sha256(value.encode("utf-8")).digest()


class TokenInvalid(Exception):
    """Expired, changed, signed elsewhere, or meant for something else."""


@dataclass(frozen=True)
class IssuedToken:
    value: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class LoginState:
    """What the callback needs to finish a login it did not start."""

    state: str
    verifier: str = field(repr=False)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TokenSigner:
    def __init__(self, secret: str, ttl: timedelta, now: Callable[[], datetime] = _utcnow) -> None:
        self._secret = secret
        self._ttl = ttl
        self._now = now

    def issue(self, user_id: uuid.UUID) -> IssuedToken:
        issued = self._now()
        expires = issued + self._ttl
        value = self._encode({"sub": str(user_id), "typ": ACCESS}, issued, expires)
        return IssuedToken(value=value, expires_at=expires)

    def verify(self, token: str) -> uuid.UUID:
        claims = self._decode(token, ACCESS)
        try:
            return uuid.UUID(str(claims["sub"]))
        except (KeyError, ValueError):
            raise TokenInvalid("the subject is not a user id") from None

    def issue_login_state(self, login: LoginState) -> str:
        issued = self._now()
        claims = {"state": login.state, "verifier": login.verifier, "typ": LOGIN_STATE}
        return self._encode(claims, issued, issued + LOGIN_STATE_TTL)

    def verify_login_state(self, token: str) -> LoginState:
        claims = self._decode(token, LOGIN_STATE)
        try:
            return LoginState(state=str(claims["state"]), verifier=str(claims["verifier"]))
        except KeyError:
            raise TokenInvalid("the login state is incomplete") from None

    def _encode(self, claims: dict[str, str], issued: datetime, expires: datetime) -> str:
        payload = {**claims, "iss": ISSUER, "aud": AUDIENCE, "iat": issued, "exp": expires}
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def _decode(self, token: str, expected_type: str) -> dict[str, object]:
        try:
            # The algorithm list is pinned: reading it from the token header is how an
            # `alg: none` token gets accepted.
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                # PyJWT reads the machine's clock and cannot be handed another, so the
                # expiry is checked below on the clock that issued the token.
                options={
                    "require": ["exp", "iat", "iss", "aud", "typ"],
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
        except jwt.PyJWTError:
            raise TokenInvalid("the token does not verify") from None
        expires = claims["exp"]
        if not isinstance(expires, int | float) or expires <= self._now().timestamp():
            raise TokenInvalid("the token has expired")
        if claims.get("typ") != expected_type:
            raise TokenInvalid("the token is meant for something else")
        return claims
