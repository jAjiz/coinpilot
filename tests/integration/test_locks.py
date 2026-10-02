import uuid

import pytest

from core.db.locks import advisory_user_lock, lock_key


def test_a_second_evaluation_of_the_same_user_is_refused(engine):
    """Two at once could spend the same cash twice (spec §9.6)."""
    user_id = uuid.uuid4()

    with advisory_user_lock(engine, user_id) as first, advisory_user_lock(engine, user_id) as second:
        assert first is True
        assert second is False


def test_the_lock_is_released_when_the_evaluation_ends(engine):
    user_id = uuid.uuid4()
    with advisory_user_lock(engine, user_id):
        pass

    with advisory_user_lock(engine, user_id) as again:
        assert again is True


def test_the_lock_is_released_when_the_evaluation_raises(engine):
    user_id = uuid.uuid4()
    with pytest.raises(RuntimeError), advisory_user_lock(engine, user_id):
        raise RuntimeError("the executor failed")

    with advisory_user_lock(engine, user_id) as again:
        assert again is True


def test_two_users_do_not_wait_on_each_other(engine):
    with advisory_user_lock(engine, uuid.uuid4()) as alice, advisory_user_lock(engine, uuid.uuid4()) as bob:
        assert alice is True
        assert bob is True


def test_the_key_is_stable_and_fits_a_bigint():
    user_id = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")

    assert lock_key(user_id) == lock_key(user_id)
    assert -(2**63) <= lock_key(user_id) < 2**63
