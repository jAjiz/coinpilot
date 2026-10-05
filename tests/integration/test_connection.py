import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def test_the_session_reaches_a_real_database(db_session: Session):
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1


def test_the_database_is_postgresql(db_session: Session):
    """The schema uses JSONB and partial indexes, so the backend is not interchangeable."""
    version = db_session.execute(text("SELECT version()")).scalar_one()

    assert "PostgreSQL" in version


def test_a_database_error_does_not_show_the_bound_parameters(db_session: Session):
    """What an error says reaches a log line; what was bound was read with the user's key."""
    with pytest.raises(DBAPIError) as raised, db_session.begin_nested():
        db_session.execute(text("SELECT CAST(:held AS text), 1 / 0"), {"held": "XXBT-0.01400000"})

    assert "XXBT-0.01400000" not in str(raised.value)
