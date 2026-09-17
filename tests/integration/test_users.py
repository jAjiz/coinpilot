import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.types import UserStatus
from core.db.users import (
    create_user,
    delete_credentials,
    get_credentials,
    get_user,
    get_user_by_identity,
    save_credentials,
    set_user_status,
)

VALIDATED = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_a_new_user_gets_a_uuid_and_is_active(db_session: Session):
    user = create_user(db_session, provider="google", subject="s-1", email="a@b.test")

    assert isinstance(user.id, uuid.UUID)
    assert user.status == UserStatus.ACTIVE


def test_a_user_is_found_by_provider_and_subject(db_session: Session):
    created = create_user(db_session, provider="google", subject="s-2", email="a@b.test")

    assert get_user_by_identity(db_session, "google", "s-2").id == created.id


def test_the_same_subject_at_another_provider_is_another_person(db_session: Session):
    create_user(db_session, provider="google", subject="s-3", email="a@b.test")

    assert get_user_by_identity(db_session, "github", "s-3") is None


def test_two_identities_may_share_an_email(db_session: Session):
    """One human with two providers is two rows until something links them."""
    create_user(db_session, provider="google", subject="s-4", email="same@b.test")
    create_user(db_session, provider="github", subject="s-4", email="same@b.test")

    assert get_user_by_identity(db_session, "github", "s-4") is not None


def test_the_same_identity_twice_is_refused(db_session: Session):
    create_user(db_session, provider="google", subject="s-5", email="a@b.test")

    with pytest.raises(IntegrityError):
        create_user(db_session, provider="google", subject="s-5", email="other@b.test")


def test_an_unknown_user_id_returns_none(db_session: Session):
    assert get_user(db_session, uuid.uuid4()) is None


def test_a_user_can_be_disabled(db_session: Session, make_user):
    user = make_user()

    updated = set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert updated.status == UserStatus.DISABLED


def test_credentials_are_stored_and_read_back_unchanged(db_session: Session, make_user):
    user = make_user()

    save_credentials(
        db_session,
        user.id,
        ciphertext=b"\x01\x02opaque",
        nonce=b"\x03nonce",
        key_version=1,
        validated_at=VALIDATED,
    )

    stored = get_credentials(db_session, user.id)
    assert stored.ciphertext == b"\x01\x02opaque"
    assert stored.nonce == b"\x03nonce"
    assert stored.key_version == 1
    assert stored.validated_at == VALIDATED


def test_saving_again_replaces_rather_than_adding_a_second_record(db_session: Session, make_user):
    user = make_user()
    save_credentials(db_session, user.id, b"first", b"n1", 1, VALIDATED)

    save_credentials(db_session, user.id, b"second", b"n2", 2, VALIDATED)

    stored = get_credentials(db_session, user.id)
    assert stored.ciphertext == b"second"
    assert stored.key_version == 2


def test_deleting_credentials_says_whether_there_was_anything_to_delete(db_session: Session, make_user):
    user = make_user()
    save_credentials(db_session, user.id, b"x", b"n", 1, VALIDATED)

    assert delete_credentials(db_session, user.id) is True
    assert delete_credentials(db_session, user.id) is False


def test_removing_a_user_removes_their_credentials(db_session: Session, make_user):
    """The cascade is what makes account deletion one statement instead of a checklist."""
    user = make_user()
    save_credentials(db_session, user.id, b"x", b"n", 1, VALIDATED)

    db_session.delete(get_user(db_session, user.id))
    db_session.flush()

    assert get_credentials(db_session, user.id) is None
