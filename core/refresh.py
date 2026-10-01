"""The life of a refresh token: issued at sign-in, rotated on every use, revoked at logout.

The tokens of one sign-in form a family, and each token is good for one use. Every token
of a family expires when the first one does: a sign-in lasts a fixed time from the Google
login, and refreshing never extends it. A used token that comes back means two parties
hold the family. The server cannot tell the owner from the thief, so it revokes the whole
family, and both must sign in again.

Nothing here raises for a refused token. The caller's transaction must commit a
revocation even when the answer is no.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

import core.database as db
from core.tokens import hash_refresh_token, new_refresh_token

logger = logging.getLogger("coinpilot.auth")


class RefreshFailure(StrEnum):
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REUSED = "reused"


@dataclass(frozen=True)
class IssuedRefresh:
    value: str = field(repr=False)
    expires_at: datetime
    user_id: uuid.UUID
    family_id: uuid.UUID


def start_family(session: Session, user_id: uuid.UUID, now: datetime, ttl: timedelta) -> IssuedRefresh:
    return _issue(session, user_id, uuid.uuid4(), now, expires_at=now + ttl)


def rotate(session: Session, presented: str, now: datetime) -> IssuedRefresh | RefreshFailure:
    """Uses up the token and issues the next one of its family, with the family's expiry."""
    token = db.get_refresh_token_for_update(session, hash_refresh_token(presented))
    if token is None:
        return RefreshFailure.UNKNOWN
    if token.revoked_at is not None:
        return RefreshFailure.REVOKED
    if token.used_at is not None:
        db.revoke_family(session, token.family_id, now)
        # The user id only; never the token or its hash.
        logger.warning("a used refresh token came back for user %s; its sign-in is revoked", token.user_id)
        return RefreshFailure.REUSED
    if token.expires_at <= now:
        return RefreshFailure.EXPIRED
    db.mark_refresh_token_used(session, token, now)
    # The expiry is inherited, never recomputed: a sign-in has an absolute lifetime.
    return _issue(session, token.user_id, token.family_id, now, expires_at=token.expires_at)


def revoke(session: Session, presented: str, now: datetime) -> bool:
    """Ends the sign-in the token belongs to. False when the token is unknown."""
    token = db.get_refresh_token_for_update(session, hash_refresh_token(presented))
    if token is None:
        return False
    db.revoke_family(session, token.family_id, now)
    return True


def _issue(
    session: Session,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
) -> IssuedRefresh:
    value = new_refresh_token()
    db.add_refresh_token(
        session,
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_refresh_token(value),
        issued_at=now,
        expires_at=expires_at,
    )
    return IssuedRefresh(value=value, expires_at=expires_at, user_id=user_id, family_id=family_id)
