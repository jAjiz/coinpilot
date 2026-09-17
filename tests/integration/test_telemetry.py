import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.telemetry import (
    delete_evaluations_before,
    finish_evaluation,
    latest_snapshot,
    list_evaluations,
    record_snapshot,
    snapshots_since,
    start_evaluation,
)

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
HOLDINGS = {
    "BTC": {"amount": "0.5", "value": "24000.00", "managed": True},
    "DOGE": {"amount": "1000", "value": "80.00", "managed": False},
}


def _snapshot(session: Session, user_id, as_of: datetime, total: str = "30000"):
    return record_snapshot(
        session,
        user_id,
        as_of=as_of,
        fiat="EUR",
        total_value=D(total),
        cash=D("6000"),
        holdings=HOLDINGS,
    )


def test_a_snapshot_keeps_its_amounts_as_decimals(db_session: Session, make_user):
    snapshot = _snapshot(db_session, make_user().id, NOW)

    assert snapshot.total_value == D("30000")
    assert snapshot.cash == D("6000")
    assert isinstance(snapshot.total_value, Decimal)


def test_a_snapshot_records_the_unmanaged_holdings_too(db_session: Session, make_user):
    """The user sees their real Kraken account, not a partial view of it."""
    snapshot = _snapshot(db_session, make_user().id, NOW)

    assert snapshot.holdings["DOGE"]["managed"] is False


def test_the_latest_snapshot_is_the_newest_by_as_of(db_session: Session, make_user):
    user = make_user()
    _snapshot(db_session, user.id, NOW - timedelta(days=1), total="10")
    _snapshot(db_session, user.id, NOW, total="20")
    _snapshot(db_session, user.id, NOW - timedelta(hours=1), total="30")

    assert latest_snapshot(db_session, user.id).total_value == D("20")


def test_a_user_with_no_snapshot_has_none(db_session: Session, make_user):
    assert latest_snapshot(db_session, make_user().id) is None


def test_the_series_is_returned_oldest_first_from_a_start_point(db_session: Session, make_user):
    user = make_user()
    _snapshot(db_session, user.id, NOW - timedelta(days=3), total="10")
    _snapshot(db_session, user.id, NOW - timedelta(days=1), total="20")
    _snapshot(db_session, user.id, NOW, total="30")

    series = snapshots_since(db_session, user.id, since=NOW - timedelta(days=2), limit=100)

    assert [s.total_value for s in series] == [D("20"), D("30")]


def test_an_evaluation_starts_open(db_session: Session, make_user):
    record = start_evaluation(db_session, make_user().id, started_at=NOW)

    assert record.started_at == NOW
    assert record.finished_at is None
    assert record.duration_ms is None
    assert record.status == "RUNNING"


def test_finishing_an_evaluation_records_how_long_it_took(db_session: Session, make_user):
    """The host ceiling shows up on a chart rather than during an incident."""
    record = start_evaluation(db_session, make_user().id, started_at=NOW)

    finished = finish_evaluation(
        db_session,
        record.id,
        status="COMPLETED",
        finished_at=NOW + timedelta(milliseconds=1500),
        log_messages='["evaluated"]',
    )

    assert finished.status == "COMPLETED"
    assert finished.duration_ms == 1500
    assert finished.log_messages == '["evaluated"]'


def test_finishing_an_evaluation_that_does_not_exist_returns_none(db_session: Session):
    assert finish_evaluation(db_session, uuid.uuid4(), status="FAILED", finished_at=NOW) is None


def test_evaluations_come_back_newest_first_and_bounded(db_session: Session, make_user):
    user = make_user()
    for n in range(3):
        start_evaluation(db_session, user.id, started_at=NOW - timedelta(hours=n))

    listed = list_evaluations(db_session, user.id, limit=2)

    assert len(listed) == 2
    assert listed[0].started_at == NOW


def test_retention_removes_the_old_and_keeps_the_recent(db_session: Session, make_user):
    user = make_user()
    start_evaluation(db_session, user.id, started_at=NOW - timedelta(days=400))
    start_evaluation(db_session, user.id, started_at=NOW - timedelta(days=10))

    removed = delete_evaluations_before(db_session, cutoff=NOW - timedelta(days=365))

    assert removed == 1
    assert len(list_evaluations(db_session, user.id, limit=10)) == 1


def test_retention_sweeps_every_user_at_once(db_session: Session, make_user):
    """It is a system-wide sweep, not something a user asks for."""
    for _ in range(2):
        start_evaluation(db_session, make_user().id, started_at=NOW - timedelta(days=400))

    assert delete_evaluations_before(db_session, cutoff=NOW - timedelta(days=365)) == 2
