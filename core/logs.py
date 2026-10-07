"""Logging for the web process: one format, and two leaks closed.

uvicorn's access log records the request line with its query, and the Google callback
carries a single-use `code` there. PostgreSQL's error text carries a `DETAIL:` line that
repeats the values of the row it refused; `hide_parameters` keeps bound values out of
SQLAlchemy's message, but not out of the driver's own.
"""

from __future__ import annotations

import logging

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# uvicorn's access record: (client, method, path with query, HTTP version, status).
_ACCESS_ARGS = 5
_PATH = 2


class Formatter(logging.Formatter):
    """Drops every `DETAIL:` line from a traceback, in the exception and its causes."""

    def formatException(self, ei) -> str:
        text = super().formatException(ei)
        return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("DETAIL:"))


class WithoutQuery(logging.Filter):
    """Keeps the path of an access line and drops its query string."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == _ACCESS_ARGS and isinstance(args[_PATH], str):
            record.args = args[:_PATH] + (args[_PATH].split("?", 1)[0],) + args[_PATH + 1 :]
        return True


def configure() -> None:
    """`coinpilot.*` at INFO to stderr, so the scheduler's alerts and recoveries are seen,
    and uvicorn's own handlers in the same format. Called once, by the entry point, after
    uvicorn configured its loggers."""
    handler = logging.StreamHandler()
    handler.setFormatter(Formatter(FORMAT))
    root = logging.getLogger("coinpilot")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for existing in logging.getLogger("uvicorn").handlers:
        existing.setFormatter(Formatter(FORMAT))
    logging.getLogger("uvicorn.access").addFilter(WithoutQuery())
