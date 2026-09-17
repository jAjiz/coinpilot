import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from core.db.settings import (
    create_settings,
    delete_asset,
    due_users,
    get_settings,
    list_assets,
    targets_for,
    update_settings,
    upsert_asset,
)
from core.db.types import CadenceMode

D = Decimal
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(minutes=30)
LATER = NOW + timedelta(minutes=30)


def test_a_new_settings_row_starts_with_the_stated_defaults(db_session: Session, make_user):
    settings = create_settings(db_session, make_user().id, fiat="EUR")

    assert settings.fiat == "EUR"
    assert settings.invest_cash_enabled is True
    assert settings.cash_rebalance_enabled is False
    assert settings.auto_rebalance_enabled is False
    assert settings.min_drift_pct == D("0")
    assert settings.min_order_fiat == D("0")
    assert settings.invest_cadence_mode == CadenceMode.MIN
    assert settings.rebalance_cadence_mode == CadenceMode.MIN
    assert settings.paused is False


def test_settings_for_an_unknown_user_are_none(db_session: Session):
    assert get_settings(db_session, uuid.uuid4()) is None


def test_a_setting_can_be_changed(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    update_settings(db_session, user.id, min_drift_pct=D("2.5"), auto_rebalance_enabled=True)

    settings = get_settings(db_session, user.id)
    assert settings.min_drift_pct == D("2.5")
    assert settings.auto_rebalance_enabled is True


def test_a_misspelled_field_is_refused_instead_of_silently_ignored(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(ValueError, match="min_drift"):
        update_settings(db_session, user.id, min_drift=D("2.5"))


def test_the_fiat_currency_cannot_be_changed(db_session: Session, make_user):
    """Immutable for now. Changing it would invalidate every stored pair and snapshot."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    with pytest.raises(ValueError, match="fiat"):
        update_settings(db_session, user.id, fiat="USD")


def test_a_user_whose_invest_time_has_passed_is_due(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, next_rebalance_at=LATER)

    due = due_users(db_session, NOW, limit=10)

    assert [d.user_id for d in due] == [user.id]
    assert due[0].invest_due is True
    assert due[0].rebalance_due is False


def test_a_user_due_for_both_reports_both(db_session: Session, make_user):
    """One balance read, two operations. The caller needs to know it is both."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, next_rebalance_at=EARLIER)

    due = due_users(db_session, NOW, limit=10)

    assert due[0].invest_due is True
    assert due[0].rebalance_due is True


def test_a_user_with_nothing_due_is_not_returned(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=LATER, next_rebalance_at=LATER)

    assert due_users(db_session, NOW, limit=10) == []


def test_a_paused_user_is_never_due(db_session: Session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")
    update_settings(db_session, user.id, next_invest_at=EARLIER, paused=True)

    assert due_users(db_session, NOW, limit=10) == []


def test_a_user_who_has_never_been_scheduled_is_not_due(db_session: Session, make_user):
    """Both times are null until something schedules them. Null is not overdue."""
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    assert due_users(db_session, NOW, limit=10) == []


def test_the_batch_is_bounded(db_session: Session, make_user):
    """After an outage every user is overdue at once. Without a cap that is a stampede."""
    for _ in range(3):
        user = make_user()
        create_settings(db_session, user.id, fiat="EUR")
        update_settings(db_session, user.id, next_invest_at=EARLIER)

    assert len(due_users(db_session, NOW, limit=2)) == 2


def test_the_most_overdue_user_goes_first(db_session: Session, make_user):
    late = make_user()
    create_settings(db_session, late.id, fiat="EUR")
    update_settings(db_session, late.id, next_invest_at=NOW - timedelta(hours=5))

    recent = make_user()
    create_settings(db_session, recent.id, fiat="EUR")
    update_settings(db_session, recent.id, next_invest_at=NOW - timedelta(minutes=1))

    assert [d.user_id for d in due_users(db_session, NOW, limit=10)] == [late.id, recent.id]


def test_an_asset_is_inserted_then_updated_in_place(db_session: Session, make_user):
    user = make_user()

    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("40"))

    assets = list_assets(db_session, user.id)
    assert len(assets) == 1
    assert assets[0].target_pct == D("40")


def test_assets_come_back_in_a_stable_order(db_session: Session, make_user):
    user = make_user()
    upsert_asset(db_session, user.id, asset="ETH", pair="ETHEUR", target_pct=D("30"))
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert [a.asset for a in list_assets(db_session, user.id)] == ["BTC", "ETH"]


def test_deleting_an_asset_says_whether_there_was_one(db_session: Session, make_user):
    user = make_user()
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))

    assert delete_asset(db_session, user.id, "BTC") is True
    assert delete_asset(db_session, user.id, "BTC") is False


def test_targets_come_back_in_the_shape_the_engine_takes(db_session: Session, make_user):
    """`reconcile` takes `targets` as a mapping of asset code to percent. This is it."""
    user = make_user()
    upsert_asset(db_session, user.id, asset="BTC", pair="XBTEUR", target_pct=D("60"))
    upsert_asset(db_session, user.id, asset="ETH", pair="ETHEUR", target_pct=D("30"))

    assert targets_for(db_session, user.id) == {"BTC": D("60.00"), "ETH": D("30.00")}


def test_a_target_of_zero_is_kept_because_it_means_exit(db_session: Session, make_user):
    """No row means unmanaged. A zero row means sell it. The engine needs to see the row."""
    user = make_user()
    upsert_asset(db_session, user.id, asset="DOGE", pair="DOGEEUR", target_pct=D("0"))

    assert targets_for(db_session, user.id) == {"DOGE": D("0.00")}
