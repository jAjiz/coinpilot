from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.db.models import RefreshToken
from core.db.refresh_tokens import delete_expired_refresh_tokens
from core.refresh import IssuedRefresh, RefreshFailure, revoke, rotate, start_family
from core.tokens import hash_refresh_token

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TTL = timedelta(days=30)
LATER = NOW + timedelta(minutes=20)


def _family(session, family_id):
    stmt = select(RefreshToken).where(RefreshToken.family_id == family_id).order_by(RefreshToken.issued_at)
    return list(session.execute(stmt).scalars())


def test_a_new_family_stores_the_hash_and_never_the_value(db_session, make_user):
    user = make_user()

    issued = start_family(db_session, user.id, NOW, TTL)

    [row] = _family(db_session, issued.family_id)
    assert row.token_hash == hash_refresh_token(issued.value)
    assert issued.value.encode() not in row.token_hash
    assert row.expires_at == NOW + TTL
    assert issued.user_id == user.id


def test_a_rotation_uses_up_the_token_and_issues_the_next_in_the_family(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    second = rotate(db_session, first.value, LATER)

    assert isinstance(second, IssuedRefresh)
    assert second.value != first.value
    assert second.family_id == first.family_id
    old, new = _family(db_session, first.family_id)
    assert old.used_at == LATER
    assert new.used_at is None
    assert new.expires_at == NOW + TTL


def test_refreshing_never_extends_the_sign_in(db_session, make_user):
    """The family's expiry is fixed at the Google login. Activity does not move it."""
    first = start_family(db_session, make_user().id, NOW, TTL)
    almost = NOW + TTL - timedelta(minutes=1)

    second = rotate(db_session, first.value, almost)

    assert second.expires_at == NOW + TTL
    assert rotate(db_session, second.value, NOW + TTL) is RefreshFailure.EXPIRED


def test_the_next_token_rotates_in_turn(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)
    second = rotate(db_session, first.value, LATER)

    assert isinstance(rotate(db_session, second.value, LATER), IssuedRefresh)


def test_a_used_token_presented_again_revokes_the_whole_family(db_session, make_user):
    """Two parties hold the family. The server cannot tell the owner from the thief."""
    first = start_family(db_session, make_user().id, NOW, TTL)
    second = rotate(db_session, first.value, LATER)

    assert rotate(db_session, first.value, LATER) is RefreshFailure.REUSED
    assert rotate(db_session, second.value, LATER) is RefreshFailure.REVOKED
    assert all(row.revoked_at == LATER for row in _family(db_session, first.family_id))


def test_a_token_nobody_issued_is_unknown(db_session):
    assert rotate(db_session, "never-issued", NOW) is RefreshFailure.UNKNOWN


def test_an_expired_token_is_refused_and_not_used_up(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    assert rotate(db_session, first.value, NOW + TTL) is RefreshFailure.EXPIRED
    assert _family(db_session, first.family_id)[0].used_at is None


def test_revoking_ends_the_family_and_says_whether_there_was_one(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    assert revoke(db_session, first.value, LATER) is True
    assert rotate(db_session, first.value, LATER) is RefreshFailure.REVOKED
    assert revoke(db_session, "never-issued", LATER) is False


def test_revoking_one_family_leaves_the_users_other_sign_ins(db_session, make_user):
    """Logging out on one device does not log out the others."""
    user = make_user()
    phone = start_family(db_session, user.id, NOW, TTL)
    laptop = start_family(db_session, user.id, NOW, TTL)

    revoke(db_session, phone.value, LATER)

    assert isinstance(rotate(db_session, laptop.value, LATER), IssuedRefresh)


def test_retention_deletes_only_what_has_expired(db_session, make_user):
    user = make_user()
    old = start_family(db_session, user.id, NOW - TTL - timedelta(days=1), TTL)
    fresh = start_family(db_session, user.id, NOW, TTL)

    assert delete_expired_refresh_tokens(db_session, before=NOW) == 1
    assert _family(db_session, old.family_id) == []
    assert len(_family(db_session, fresh.family_id)) == 1
