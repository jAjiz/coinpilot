import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.types import UserStatus

EXPECTED_TABLES = frozenset(
    {
        "users",
        "user_credentials",
        "user_settings",
        "asset_config",
        "orders",
        "proposal",
        "portfolio_snapshots",
        "sessions",
    }
)


def test_the_migration_creates_every_table(db_session: Session):
    present = set(inspect(db_session.get_bind()).get_table_names())

    assert present >= EXPECTED_TABLES


def test_every_table_except_users_carries_a_user_id(db_session: Session):
    """The spec's first rule about the data model, asserted rather than trusted."""
    inspector = inspect(db_session.get_bind())

    for table in sorted(EXPECTED_TABLES - {"users"}):
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert "user_id" in columns, f"{table} has no user_id"


def test_the_scheduler_query_is_indexed(db_session: Session):
    """One indexed query per tick. Without these it is a sequential scan of every user."""
    names = {i["name"] for i in inspect(db_session.get_bind()).get_indexes("user_settings")}

    assert "ix_user_settings_next_invest_at" in names
    assert "ix_user_settings_next_rebalance_at" in names


def test_the_unresolved_attempt_lookup_is_indexed(db_session: Session):
    names = {i["name"] for i in inspect(db_session.get_bind()).get_indexes("orders")}

    assert "ix_orders_user_pending" in names


@pytest.mark.parametrize("status", [member.value for member in UserStatus])
def test_every_status_the_code_knows_is_accepted_by_the_database(db_session: Session, status: str):
    db_session.execute(
        text(
            "INSERT INTO users (id, provider, subject, email, status) "
            "VALUES (gen_random_uuid(), 'google', :subject, 'a@b.test', :status)"
        ),
        {"subject": f"subject-{status}", "status": status},
    )
    db_session.flush()


def test_a_status_the_code_does_not_know_is_refused(db_session: Session):
    """The enumeration and the check constraint must not drift apart."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO users (id, provider, subject, email, status) "
                "VALUES (gen_random_uuid(), 'google', 'drifted', 'a@b.test', 'NONSENSE')"
            )
        )
        db_session.flush()
