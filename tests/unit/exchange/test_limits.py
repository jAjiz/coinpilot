from exchange.limits import PUBLIC_BUCKET, KeyLimiter


class FakeClock:
    """A clock the test moves by hand. Sleeping advances it, exactly as it would in life."""

    def __init__(self) -> None:
        self.monotonic = 1000.0
        self.wall = 1_700_000_000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.monotonic

    def time(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.monotonic += seconds
        self.wall += seconds


def _limiter(clock: FakeClock, min_interval: float = 1.0) -> KeyLimiter:
    return KeyLimiter(min_interval, now=clock.now, sleep=clock.sleep, clock=clock.time)


def test_the_first_call_for_a_key_never_waits():
    clock = FakeClock()
    limiter = _limiter(clock)

    limiter.wait_turn("key-a")

    assert clock.slept == []


def test_a_second_call_too_soon_waits_the_remainder():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")
    clock.monotonic += 0.25

    limiter.wait_turn("key-a")

    assert clock.slept == [0.75]


def test_a_second_call_after_the_interval_does_not_wait():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")
    clock.monotonic += 5.0

    limiter.wait_turn("key-a")

    assert clock.slept == []


def test_one_users_pace_does_not_slow_another():
    """The whole multi-tenant argument in one test. Kraken counts per key."""
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn("key-a")

    limiter.wait_turn("key-b")

    assert clock.slept == []


def test_every_public_call_shares_one_bucket():
    """Public endpoints are counted by address, so they contend with each other."""
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.wait_turn(PUBLIC_BUCKET)

    limiter.wait_turn(PUBLIC_BUCKET)

    assert clock.slept == [1.0]


def test_a_nonce_is_the_clock_in_microseconds():
    clock = FakeClock()
    limiter = _limiter(clock)

    assert limiter.next_nonce("key-a") == str(int(clock.wall * 1_000_000))


def test_two_nonces_for_one_key_always_increase():
    """Kraken refuses a nonce that is not greater than the last one this key used."""
    clock = FakeClock()
    limiter = _limiter(clock)

    first = int(limiter.next_nonce("key-a"))
    second = int(limiter.next_nonce("key-a"))

    assert second > first


def test_a_clock_that_jumps_backwards_still_yields_an_increasing_nonce():
    """An NTP correction would otherwise lock the key out until the clock caught up."""
    clock = FakeClock()
    limiter = _limiter(clock)
    first = int(limiter.next_nonce("key-a"))
    clock.wall -= 60.0

    second = int(limiter.next_nonce("key-a"))

    assert second > first


def test_each_key_keeps_its_own_nonce_sequence():
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.next_nonce("key-a")
    limiter.next_nonce("key-a")
    clock.wall -= 60.0

    fresh = int(limiter.next_nonce("key-b"))

    assert fresh == int(clock.wall * 1_000_000)
