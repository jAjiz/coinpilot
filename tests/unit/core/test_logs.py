import logging
import sys

import pytest

from core.logs import FORMAT, Formatter, WithoutQuery, configure

ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


def _record_raising(exc: Exception) -> logging.LogRecord:
    try:
        raise exc
    except Exception:
        return logging.LogRecord(
            "coinpilot.scheduler", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )


def _access(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        ACCESS_FORMAT,
        ("10.0.0.1:5000", "GET", path, "1.1", 302),
        None,
    )


@pytest.fixture
def clean_loggers():
    """`configure` changes process-wide loggers. Put them back."""
    loggers = [logging.getLogger(name) for name in ("coinpilot", "uvicorn", "uvicorn.access")]
    saved = [(list(logger.handlers), list(logger.filters), logger.level) for logger in loggers]
    yield
    for logger, (handlers, filters, level) in zip(loggers, saved, strict=True):
        logger.handlers[:] = handlers
        logger.filters[:] = filters
        logger.setLevel(level)


def test_a_traceback_keeps_the_error_and_loses_postgres_detail():
    record = _record_raising(
        RuntimeError(
            'duplicate key value violates unique constraint "orders_txid"\n'
            "DETAIL:  Key (txid)=(OABC-1) exists."
        )
    )

    text = Formatter(FORMAT).format(record)

    assert "duplicate key value violates unique constraint" in text
    assert "OABC-1" not in text
    assert "DETAIL" not in text


def test_a_message_with_no_traceback_is_formatted_as_usual():
    record = logging.LogRecord("coinpilot.api", logging.INFO, __file__, 1, "user %s: done", ("u-1",), None)

    assert Formatter("%(message)s").format(record) == "user u-1: done"


def test_the_access_log_loses_the_query_string():
    record = _access("/auth/callback/google?code=THE-CODE&state=s")

    assert WithoutQuery().filter(record) is True
    assert "THE-CODE" not in record.getMessage()
    assert "/auth/callback/google" in record.getMessage()


def test_a_path_with_no_query_is_left_alone():
    record = _access("/portfolio")

    WithoutQuery().filter(record)

    assert record.getMessage() == '10.0.0.1:5000 - "GET /portfolio HTTP/1.1" 302'


def test_a_record_that_is_not_an_access_line_is_left_alone():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s?%s", ("a", "b"), None)

    WithoutQuery().filter(record)

    assert record.getMessage() == "a?b"


def test_configure_filters_the_access_log_and_formats_uvicorns_handlers(clean_loggers):
    uvicorn_handler = logging.StreamHandler()
    logging.getLogger("uvicorn").addHandler(uvicorn_handler)

    configure()

    assert any(isinstance(f, WithoutQuery) for f in logging.getLogger("uvicorn.access").filters)
    assert isinstance(uvicorn_handler.formatter, Formatter)
    assert any(isinstance(h.formatter, Formatter) for h in logging.getLogger("coinpilot").handlers)
    assert logging.getLogger("coinpilot").level == logging.INFO
