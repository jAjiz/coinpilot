from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.crypto import CredentialCipher, Sealed
from core.db.users import credential_owners_not_at, get_credentials, save_credentials
from core.rotation import Outcome, reseal, rotate
from exchange.types import Credentials

KEY_1 = bytes(range(32))
KEY_2 = bytes(range(32, 64))
KEY_3 = bytes(range(64, 96))
OLD = CredentialCipher({1: KEY_1}, 1)
NEW = CredentialCipher({1: KEY_1, 2: KEY_2}, 2)
ONLY_NEW = CredentialCipher({2: KEY_2}, 2)
CREDENTIALS = Credentials(api_key="THE-PUBLIC-KEY", api_secret="THE-SECRET-VALUE")
VALIDATED = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _store(session: Session, user_id, cipher: CredentialCipher) -> None:
    sealed = cipher.seal(user_id, CREDENTIALS)
    save_credentials(session, user_id, sealed.ciphertext, sealed.nonce, sealed.key_version, VALIDATED)


def _opened(session: Session, user_id, cipher: CredentialCipher) -> Credentials:
    record = get_credentials(session, user_id)
    return cipher.unseal(user_id, Sealed(record.ciphertext, record.nonce, record.key_version))


def _sessions(session: Session) -> Callable:
    """What `rotate` is given in production is `session_scope`. Here each unit of work is a
    savepoint inside the test's transaction, which is rolled back."""

    @contextmanager
    def sessions():
        nested = session.begin_nested()
        try:
            yield session
        except Exception:
            nested.rollback()
            raise
        else:
            nested.commit()

    return sessions


def test_a_record_under_an_old_key_is_sealed_again_under_the_active_one(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, OLD)

    outcome = reseal(db_session, NEW, alice.id)

    assert outcome is Outcome.RESEALED
    assert get_credentials(db_session, alice.id).key_version == 2
    # The old key is no longer needed to open it.
    assert _opened(db_session, alice.id, ONLY_NEW) == CREDENTIALS


def test_resealing_does_not_pretend_the_key_was_validated_again(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, OLD)

    reseal(db_session, NEW, alice.id)

    assert get_credentials(db_session, alice.id).validated_at == VALIDATED


def test_a_record_already_under_the_active_key_is_not_touched(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, NEW)
    before = get_credentials(db_session, alice.id).ciphertext

    assert reseal(db_session, NEW, alice.id) is Outcome.CURRENT
    assert get_credentials(db_session, alice.id).ciphertext == before


def test_a_user_with_no_record_is_gone(db_session: Session, make_user):
    assert reseal(db_session, NEW, make_user().id) is Outcome.GONE


def test_a_record_that_does_not_open_is_left_as_it_was(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, CredentialCipher({3: KEY_3}, 3))
    before = get_credentials(db_session, alice.id).ciphertext

    assert reseal(db_session, NEW, alice.id) is Outcome.UNREADABLE
    record = get_credentials(db_session, alice.id)
    assert (record.key_version, record.ciphertext) == (3, before)


def test_rotate_reseals_every_old_record_and_reports_the_unreadable(db_session: Session, make_user):
    alice, bob, carol, dave = make_user(), make_user(), make_user(), make_user()
    _store(db_session, alice.id, OLD)
    _store(db_session, bob.id, OLD)
    _store(db_session, carol.id, NEW)
    _store(db_session, dave.id, CredentialCipher({3: KEY_3}, 3))

    report = rotate(_sessions(db_session), NEW)

    # Membership only: the development database's real record is listed too, and it does
    # not open under this test's keys.
    assert {alice.id, bob.id} <= set(report.resealed)
    assert carol.id not in report.resealed
    assert dave.id in report.unreadable
    assert not report.ok
    left = credential_owners_not_at(db_session, 2)
    assert alice.id not in left and bob.id not in left
    assert dave.id in left
