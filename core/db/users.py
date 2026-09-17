"""Identity, and the record that holds the encrypted Kraken credentials.

Nothing here encrypts or decrypts anything. This layer stores opaque bytes and the phase
that owns the cipher decides what they mean. Keeping the two apart is what lets the
storage be tested with no master key anywhere near it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import User, UserCredentials
from core.db.types import UserStatus


def create_user(session: Session, provider: str, subject: str, email: str) -> User:
    user = User(provider=provider, subject=subject, email=email, status=UserStatus.ACTIVE)
    session.add(user)
    session.flush()
    return user


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def get_user_by_identity(session: Session, provider: str, subject: str) -> User | None:
    """The lookup the OAuth callback makes.

    On the provider and its subject, never on the email: an email can change hands and a
    subject cannot.
    """
    stmt = select(User).where(User.provider == provider, User.subject == subject)
    return session.execute(stmt).scalar_one_or_none()


def set_user_status(session: Session, user_id: uuid.UUID, status: UserStatus) -> User | None:
    user = session.get(User, user_id)
    if user is None:
        return None
    user.status = status
    session.flush()
    return user


def save_credentials(
    session: Session,
    user_id: uuid.UUID,
    ciphertext: bytes,
    nonce: bytes,
    key_version: int,
    validated_at: datetime,
) -> UserCredentials:
    """Insert or replace. There is one credential record per user, so this is an upsert."""
    record = session.get(UserCredentials, user_id)
    if record is None:
        record = UserCredentials(user_id=user_id)
        session.add(record)
    record.ciphertext = ciphertext
    record.nonce = nonce
    record.key_version = key_version
    record.validated_at = validated_at
    session.flush()
    return record


def get_credentials(session: Session, user_id: uuid.UUID) -> UserCredentials | None:
    return session.get(UserCredentials, user_id)


def delete_credentials(session: Session, user_id: uuid.UUID) -> bool:
    """True when a record was removed, false when there was none to remove."""
    record = session.get(UserCredentials, user_id)
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True
