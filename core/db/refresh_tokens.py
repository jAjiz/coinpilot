"""Refresh tokens, stored as hashes. The rules for using them live in `core/refresh.py`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from core.db.models import RefreshToken


def add_refresh_token(
    session: Session,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    token_hash: bytes,
    issued_at: datetime,
    expires_at: datetime,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    session.add(token)
    session.flush()
    return token


def get_refresh_token_for_update(session: Session, token_hash: bytes) -> RefreshToken | None:
    """The row, locked until the transaction ends.

    Two requests with the same token are serialised here: the second sees the first one's
    `used_at` and is treated as a reuse, never as a second valid rotation.
    """
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def mark_refresh_token_used(session: Session, token: RefreshToken, used_at: datetime) -> None:
    token.used_at = used_at
    session.flush()


def revoke_family(session: Session, family_id: uuid.UUID, revoked_at: datetime) -> int:
    """Revokes every live token of one sign-in. Returns how many were still live."""
    result = session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )
    session.flush()
    return result.rowcount


def delete_expired_refresh_tokens(session: Session, before: datetime) -> int:
    """Retention, across every user at once, like the `sessions` sweep. Returns how many went."""
    result = session.execute(delete(RefreshToken).where(RefreshToken.expires_at < before))
    session.flush()
    return result.rowcount
