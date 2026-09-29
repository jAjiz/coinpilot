"""Every request and response body.

A response model is a whitelist: a field that is not declared here cannot reach a client,
whatever the ORM row carries. No model in this file has a field for a Kraken key or
secret on the way out.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


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


class CredentialsIn(BaseModel):
    # `SecretStr` keeps the values out of a repr. It does not keep them out of a
    # validation error; the handler in `api/app.py` does that.
    api_key: SecretStr = Field(min_length=1, max_length=256)
    api_secret: SecretStr = Field(min_length=1, max_length=512)


class KeyAcceptedOut(BaseModel):
    validated_at: datetime
    permissions: list[str]
    ip_allowlist: list[str]


class CredentialStatusOut(BaseModel):
    registered: bool
    validated_at: datetime | None = None
    key_version: int | None = None
