"""The FastAPI application, assembled from an `AppContext`."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from api.context import AppContext
from api.routes import assets, auth, config, credentials, health, history, invest, portfolio

logger = logging.getLogger("coinpilot.api")

DATABASE_DOWN = "the database cannot be reached right now; try again in a moment"


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Validation errors without the offending input.

    FastAPI's default answer includes the value that failed. On `POST /credentials` that
    value is a Kraken key or secret, and a `SecretStr` field does not prevent it.
    """
    detail = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg", ""), "type": error.get("type", "")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def _database_unreachable(error: Exception) -> bool:
    """No connection could be had: the pool was full, or the server did not answer.

    An error the server sent back carries a SQLSTATE, a lock timeout for one. The database
    answered, so it is not an outage and stays a 500.
    """
    if isinstance(error, PoolTimeout):
        return True
    return isinstance(error, OperationalError) and getattr(error.orig, "sqlstate", None) is None


async def _database_error(request: Request, exc: Exception) -> JSONResponse:
    if not _database_unreachable(exc):
        raise exc
    # The type only: the driver's message names the host and port.
    logger.error("the database could not be reached: %s", type(getattr(exc, "orig", None) or exc).__name__)
    return JSONResponse(status_code=503, content={"detail": DATABASE_DOWN})


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="CoinPilot", version="0.1.0")
    app.state.context = context
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(OperationalError, _database_error)
    app.add_exception_handler(PoolTimeout, _database_error)
    for router in (
        health.router,
        auth.router,
        credentials.router,
        config.router,
        assets.router,
        portfolio.router,
        invest.router,
        history.router,
    ):
        app.include_router(router)
    return app
