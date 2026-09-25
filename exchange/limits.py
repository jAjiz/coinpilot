"""The two facts Kraken tracks per key: how recently it called, and its last nonce.

They live in one object because they share a scope and a lifetime. Both are counted per
key, both must outlive any single client object, and neither may sit in a module global:
user state there is what the design forbids, and an injected object is also what lets a
test run on a fake clock instead of really sleeping.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Kraken counts public endpoints against the calling address, not a key, so every
# unauthenticated call shares this one bucket.
PUBLIC_BUCKET = "__public__"


class KeyLimiter:
    """Paces calls and hands out nonces, separately for each key."""

    def __init__(
        self,
        min_interval: float,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._min_interval = min_interval
        self._now = now
        self._sleep = sleep
        self._clock = clock
        self._guard = threading.Lock()
        self._last_call: dict[str, float] = {}
        self._last_nonce: dict[str, int] = {}

    def wait_turn(self, bucket: str) -> None:
        """Block until this bucket may call again.

        The slot is reserved inside the guard and the wait happens outside it. Holding
        the guard across a sleep would make one key's pacing block every other key, which
        is the exact contention this design exists to avoid.
        """
        with self._guard:
            previous = self._last_call.get(bucket)
            now = self._now()
            wait = 0.0 if previous is None else previous + self._min_interval - now
            self._last_call[bucket] = now + max(wait, 0.0)

        if wait > 0:
            self._sleep(wait)

    def next_nonce(self, bucket: str) -> str:
        """A nonce strictly greater than the last one this bucket used.

        The clock alone is not enough. A correction can move it backwards, and Kraken
        then refuses every later request from that key until it catches up.
        """
        with self._guard:
            candidate = int(self._clock() * 1_000_000)
            previous = self._last_nonce.get(bucket, 0)
            if candidate <= previous:
                candidate = previous + 1
            self._last_nonce[bucket] = candidate
            return str(candidate)
