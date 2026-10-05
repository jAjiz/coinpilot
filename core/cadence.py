"""When an operation is next due (spec §3.5, §10.2). Pure: no database, no clock.

Each user's slots are shifted by an offset taken from their id, so a thousand users on the
same cadence do not fall due in the same minute. The offset is a hash, not the clock: it
is uniform, and the same on every run, so an incident can be reproduced.
"""

from __future__ import annotations

import calendar
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.db.types import CadenceMode

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# The mean length of a calendar month, for a first guess only. The walk corrects it.
_MEAN_MONTH_DAYS = 30.436875


@dataclass(frozen=True)
class Cadence:
    mode: CadenceMode
    interval_days: int | None = None
    interval_months: int | None = None
    # An instant. Below a day it carries no meaning and is ignored.
    anchor: datetime | None = None


def offset_seconds(user_id: uuid.UUID, span_seconds: int) -> int:
    """Where in `span_seconds` this user's slots fall.

    CRC32 of the id, not `hash`: Python salts `hash` per process, and a user's slot must
    not move when the process restarts.
    """
    return zlib.crc32(user_id.bytes) % span_seconds


def next_slot(
    cadence: Cadence, user_id: uuid.UUID, now: datetime, *, min_interval: timedelta, window: timedelta
) -> datetime:
    """The first slot strictly after `now`.

    A slot missed while the system was down is not caught up: the next one is after `now`,
    so a user is evaluated once, never once per missed slot (spec §10.2).
    """
    if cadence.mode == CadenceMode.MIN:
        return _every(user_id, now, min_interval)
    return _anchored(cadence, user_id, now, window)


def _every(user_id: uuid.UUID, now: datetime, interval: timedelta) -> datetime:
    """`epoch + k × interval + offset`: below a day there is no anchor (spec §10.2)."""
    step = int(interval.total_seconds())
    offset = offset_seconds(user_id, step)
    elapsed = int((now - EPOCH).total_seconds()) - offset
    return EPOCH + timedelta(seconds=(elapsed // step + 1) * step + offset)


def _anchored(cadence: Cadence, user_id: uuid.UUID, now: datetime, window: timedelta) -> datetime:
    """`anchor + k × (months, days) + offset`, the offset inside `window`.

    The anchor fixes the date and the time; the offset spreads users over the hour after it.
    """
    days = cadence.interval_days or 0
    months = cadence.interval_months or 0
    if cadence.anchor is None or days + months == 0:
        raise ValueError("an INTERVAL cadence needs a length and an anchor")
    anchor = cadence.anchor.astimezone(UTC)
    shift = timedelta(seconds=offset_seconds(user_id, int(window.total_seconds())))

    # A guess from the mean length of a step, then a walk to the exact one.
    mean_step = timedelta(days=days + months * _MEAN_MONTH_DAYS)
    k = max(0, int((now - anchor) / mean_step))
    while k > 0 and _occurrence(anchor, k, months, days) + shift > now:
        k -= 1
    while _occurrence(anchor, k, months, days) + shift <= now:
        k += 1
    return _occurrence(anchor, k, months, days) + shift


def _occurrence(anchor: datetime, k: int, months: int, days: int) -> datetime:
    """The k-th step. Months are counted from the anchor each time, never chained: an anchor
    on the 31st falls on the 30th or the 28th, and returns to the 31st."""
    return _add_months(anchor, k * months) + timedelta(days=k * days)


def _add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
