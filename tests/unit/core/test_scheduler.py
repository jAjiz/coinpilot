"""The scheduler's pool. The integration tests run one worker, as the test session is not
thread-safe; production runs several, and this is that branch."""

import threading
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from core.config import SchedulerConfig
from core.db.settings import DueUser
from core.schedule import INVEST, REBALANCE
from core.scheduler import Scheduler

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _scheduler(workers: int) -> Scheduler:
    config = SimpleNamespace(scheduler=SchedulerConfig(workers=workers))
    return Scheduler(SimpleNamespace(config=config))


def test_the_pool_handles_every_due_user_and_one_failure_stops_none(monkeypatch):
    due = [DueUser(uuid.uuid4(), invest_due=True, rebalance_due=True) for _ in range(8)]
    broken = due[2].user_id
    handled: list[tuple[uuid.UUID, str, str]] = []
    guard = threading.Lock()

    def operate(self, context, user_id, prefix, now):
        with guard:
            handled.append((user_id, prefix, threading.current_thread().name))
        if user_id == broken and prefix == INVEST:
            raise RuntimeError("boom")

    monkeypatch.setattr(Scheduler, "_operate", operate)

    _scheduler(workers=4)._each(object(), due, NOW)

    done = {(user_id, prefix) for user_id, prefix, _ in handled}
    expected = {(user.user_id, prefix) for user in due for prefix in (INVEST, REBALANCE)}
    # The broken user's investment raised, so its rebalance was not reached; every other user's ran.
    assert done == expected - {(broken, REBALANCE)}
    assert all(name.startswith("coinpilot-evaluation") for _, _, name in handled)
