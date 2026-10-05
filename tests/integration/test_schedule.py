from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from core.config import SchedulerConfig
from core.db.settings import create_settings, get_settings, update_settings
from core.schedule import INVEST, REBALANCE, backfill, next_run

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
CONFIG = SchedulerConfig()


def test_an_investment_switched_off_has_no_next_run(db_session: Session, make_user):
    user = make_user()
    settings = create_settings(db_session, user.id, fiat="EUR")

    assert next_run(settings, INVEST, NOW, CONFIG) is None
    assert NOW < next_run(settings, REBALANCE, NOW, CONFIG) <= NOW + CONFIG.min_cadence


def test_settings_written_before_the_scheduler_get_their_next_runs(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, invest_cash_enabled=True)

    backfill(db_session, NOW, CONFIG)

    settings = get_settings(db_session, user.id)
    assert NOW < settings.next_invest_at <= NOW + CONFIG.min_cadence
    assert NOW < settings.next_rebalance_at <= NOW + CONFIG.min_cadence


def test_backfill_leaves_a_scheduled_user_and_an_idle_investment_alone(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    planned = NOW + timedelta(days=3)
    update_settings(db_session, user.id, next_rebalance_at=planned)

    backfill(db_session, NOW, CONFIG)

    settings = get_settings(db_session, user.id)
    assert settings.next_rebalance_at == planned
    assert settings.next_invest_at is None
