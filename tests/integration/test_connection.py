from sqlalchemy import text
from sqlalchemy.orm import Session


def test_the_session_reaches_a_real_database(db_session: Session):
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1


def test_the_database_is_postgresql(db_session: Session):
    """The schema uses JSONB and partial indexes, so the backend is not interchangeable."""
    version = db_session.execute(text("SELECT version()")).scalar_one()

    assert "PostgreSQL" in version
