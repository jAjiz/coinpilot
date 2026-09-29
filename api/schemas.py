"""Every request and response body.

A response model is a whitelist: a field that is not declared here cannot reach a client,
whatever the ORM row carries. No model in this file has a field for a Kraken key or
secret on the way out.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr


class TokenPairOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class RefreshIn(BaseModel):
    """The body of a refresh or a logout. A browser sends no body and relies on the cookie."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr | None = None


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    provider: str
    status: str
    created_at: datetime
