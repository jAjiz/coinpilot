"""The FastAPI application, assembled from an `AppContext`."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.context import AppContext
from api.routes import auth, credentials, health


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


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="CoinPilot", version="0.1.0")
    app.state.context = context
    app.add_exception_handler(RequestValidationError, _validation_error)
    for router in (health.router, auth.router, credentials.router):
        app.include_router(router)
    return app
