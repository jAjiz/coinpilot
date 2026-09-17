import pytest

from core.config import database_url


def test_a_missing_database_url_raises_rather_than_defaulting(monkeypatch):
    """A silent default would point production at a local database, and the failure would
    look like an empty account."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_the_url_that_is_set_is_the_one_returned(monkeypatch):
    """This test sets the environment because the reader is what is under test. Every
    other test states its inputs instead."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db")

    assert database_url() == "postgresql+psycopg://u:p@host:5432/db"
