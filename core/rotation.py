"""Master-key rotation: every stored credential sealed again under the active key (spec §5.3).

The cipher opens any version it holds and seals with the active one. Rotating is: add the
new key and make it active, restart, run this, check that nothing is left under the old
version, remove the old key, restart (runbook: docs/operations.md).

Each record is re-sealed in its own transaction, under a row lock. A user who registers a
new key meanwhile is neither lost nor overwritten: whichever write comes second wins, and
both are sealed with the active key. A record that does not open is left exactly as it was.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

import core.database as db
from core.crypto import CredentialCipher, CredentialsUnreadable, Sealed


class Outcome(StrEnum):
    RESEALED = "RESEALED"
    # Already under the active key.
    CURRENT = "CURRENT"
    # Deleted since it was listed.
    GONE = "GONE"
    # Under a version the cipher does not hold, or altered. Left as it was.
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class RotationReport:
    resealed: tuple[uuid.UUID, ...]
    unreadable: tuple[uuid.UUID, ...]

    @property
    def ok(self) -> bool:
        return not self.unreadable


def reseal(session: Session, cipher: CredentialCipher, user_id: uuid.UUID) -> Outcome:
    """One record, inside the caller's transaction. `validated_at` is kept: nothing was
    validated again."""
    record = db.lock_credentials(session, user_id)
    if record is None:
        return Outcome.GONE
    if record.key_version == cipher.active_version:
        return Outcome.CURRENT
    try:
        credentials = cipher.unseal(user_id, Sealed(record.ciphertext, record.nonce, record.key_version))
    except CredentialsUnreadable:
        return Outcome.UNREADABLE
    sealed = cipher.seal(user_id, credentials)
    record.ciphertext = sealed.ciphertext
    record.nonce = sealed.nonce
    record.key_version = sealed.key_version
    session.flush()
    return Outcome.RESEALED


def rotate(
    sessions: Callable[[], AbstractContextManager[Session]], cipher: CredentialCipher
) -> RotationReport:
    """Every record not under the active key, one transaction each."""
    with sessions() as session:
        owners = db.credential_owners_not_at(session, cipher.active_version)
    resealed: list[uuid.UUID] = []
    unreadable: list[uuid.UUID] = []
    for user_id in owners:
        with sessions() as session:
            outcome = reseal(session, cipher, user_id)
        if outcome is Outcome.RESEALED:
            resealed.append(user_id)
        elif outcome is Outcome.UNREADABLE:
            unreadable.append(user_id)
    return RotationReport(tuple(resealed), tuple(unreadable))
