"""The FastAPI application, assembled from an `AppContext`."""

from __future__ import annotations

from fastapi import FastAPI

from api.context import AppContext
from api.routes import auth, health


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="CoinPilot", version="0.1.0")
    app.state.context = context
    for router in (health.router, auth.router):
        app.include_router(router)
    return app
