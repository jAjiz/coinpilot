import core.db.session as session_module
from core.db.session import CONNECT_TIMEOUT_SECONDS, create_engine_from_url


def test_opening_a_connection_gives_up_after_five_seconds(monkeypatch):
    """psycopg's own default is 130 s: every request would hang that long on a database
    that is down. This bounds opening a connection only; a query may run longer."""
    seen = {}
    monkeypatch.setattr(session_module, "create_engine", lambda url, **kwargs: seen.update(kwargs))

    create_engine_from_url("postgresql+psycopg://u:p@localhost/db")

    assert CONNECT_TIMEOUT_SECONDS == 5
    assert seen["connect_args"] == {"connect_timeout": 5}


def test_errors_do_not_carry_the_bound_parameters(monkeypatch):
    """A statement's parameters are balances and order amounts read with the user's key,
    and an error's text ends up in a log line."""
    seen = {}
    monkeypatch.setattr(session_module, "create_engine", lambda url, **kwargs: seen.update(kwargs))

    create_engine_from_url("postgresql+psycopg://u:p@localhost/db")

    assert seen["hide_parameters"] is True
