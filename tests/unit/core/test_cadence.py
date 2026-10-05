import uuid
import zlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.cadence import EPOCH, Cadence, next_slot, offset_seconds
from core.db.types import CadenceMode

USER = uuid.UUID("12345678-1234-5678-1234-567812345678")
MIN = timedelta(minutes=15)
WINDOW = timedelta(hours=1)
SHIFT = timedelta(seconds=offset_seconds(USER, 3600))


def _at(*parts):
    return datetime(*parts, tzinfo=UTC)


def _slot(cadence, now):
    return next_slot(cadence, USER, now, min_interval=MIN, window=WINDOW)


MIN_CADENCE = Cadence(CadenceMode.MIN)
DAILY = Cadence(CadenceMode.INTERVAL, interval_days=1, anchor=_at(2026, 1, 1, 9, 0))
MONTHLY_31 = Cadence(CadenceMode.INTERVAL, interval_months=1, anchor=_at(2026, 1, 31, 9, 0))


def test_the_offset_is_the_ids_crc32_within_the_span():
    """CRC32, not `hash`: Python salts `hash` per process, and the slot must not move on a restart."""
    assert offset_seconds(USER, 900) == zlib.crc32(USER.bytes) % 900


def test_offsets_spread_users_across_the_span():
    offsets = [offset_seconds(uuid.uuid5(uuid.NAMESPACE_OID, str(n)), 3600) for n in range(500)]

    assert all(0 <= offset < 3600 for offset in offsets)
    assert len(set(offsets)) > 400


def test_the_shift_is_within_the_window():
    assert timedelta(0) <= SHIFT < WINDOW


def test_a_min_cadence_falls_on_the_users_offset_within_each_interval():
    now = _at(2026, 10, 5, 12, 7)

    slot = _slot(MIN_CADENCE, now)

    assert now < slot <= now + MIN
    assert (slot - EPOCH).total_seconds() % 900 == offset_seconds(USER, 900)


def test_a_min_cadence_never_returns_now_itself():
    now = _slot(MIN_CADENCE, _at(2026, 10, 5, 12, 0))

    assert _slot(MIN_CADENCE, now) == now + MIN


def test_a_daily_cadence_runs_at_the_anchors_time_plus_the_users_shift():
    assert _slot(DAILY, _at(2026, 10, 5, 12, 0)) == _at(2026, 10, 6, 9, 0) + SHIFT


def test_todays_slot_is_returned_while_it_is_still_ahead():
    today = _at(2026, 10, 5, 9, 0) + SHIFT

    assert _slot(DAILY, today - timedelta(seconds=1)) == today


def test_missed_slots_are_not_caught_up():
    """Down for a week: the next run is the next slot, once (spec §10.2)."""
    assert _slot(DAILY, _at(2026, 10, 12, 10, 30)) == _at(2026, 10, 13, 9, 0) + SHIFT


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_at(2026, 2, 10), _at(2026, 2, 28, 9, 0)),
        (_at(2026, 3, 1), _at(2026, 3, 31, 9, 0)),
        (_at(2026, 4, 1), _at(2026, 4, 30, 9, 0)),
        (_at(2026, 5, 1), _at(2026, 5, 31, 9, 0)),
    ],
)
def test_a_monthly_cadence_on_the_31st_returns_to_the_31st(now, expected):
    """Months are counted from the anchor, never chained: chained, it would stay on the 28th."""
    assert _slot(MONTHLY_31, now) == expected + SHIFT


def test_a_quarterly_cadence_counts_calendar_months_from_the_anchor():
    quarterly = Cadence(CadenceMode.INTERVAL, interval_months=3, anchor=_at(2026, 1, 15, 9, 0))

    assert _slot(quarterly, _at(2026, 5, 1)) == _at(2026, 7, 15, 9, 0) + SHIFT


def test_days_and_months_together_add_both_per_step():
    both = Cadence(CadenceMode.INTERVAL, interval_days=1, interval_months=1, anchor=_at(2026, 1, 1, 9, 0))

    assert _slot(both, _at(2026, 1, 10)) == _at(2026, 2, 2, 9, 0) + SHIFT


def test_an_anchor_in_the_future_is_the_first_slot():
    later = Cadence(CadenceMode.INTERVAL, interval_days=7, anchor=_at(2027, 1, 1, 9, 0))

    assert _slot(later, _at(2026, 10, 5)) == _at(2027, 1, 1, 9, 0) + SHIFT


def test_an_anchor_given_in_another_zone_is_read_as_its_instant_in_utc():
    summer_in_madrid = datetime(2026, 7, 1, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    cadence = Cadence(CadenceMode.INTERVAL, interval_days=1, anchor=summer_in_madrid)

    assert _slot(cadence, _at(2026, 10, 5, 12, 0)) == _at(2026, 10, 6, 9, 0) + SHIFT


def test_an_interval_cadence_without_an_anchor_is_refused():
    with pytest.raises(ValueError):
        _slot(Cadence(CadenceMode.INTERVAL, interval_days=1), _at(2026, 10, 5))


@pytest.mark.parametrize(
    ("days", "months"),
    [(-1, 0), (0, -1), (2, -1), (-30, 2), (-1, -1)],
)
def test_a_negative_length_is_refused_rather_than_walked_forever(days, months):
    """The API forbids it, the database does not: a hand-edited row must fail one user, not
    spin the tick thread."""
    cadence = Cadence(
        CadenceMode.INTERVAL, interval_days=days, interval_months=months, anchor=_at(2026, 1, 1)
    )

    with pytest.raises(ValueError):
        _slot(cadence, _at(2026, 10, 5))
