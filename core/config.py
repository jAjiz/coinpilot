"""The one module that reads the process environment.

Every other module receives what it needs as an argument. That is what lets a test state
its inputs instead of inheriting them from the machine it runs on.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

MASTER_KEY_BYTES = 32
MIN_JWT_SECRET_CHARS = 32
DEFAULT_JWT_TTL_MINUTES = 15
DEFAULT_REFRESH_TTL_DAYS = 30


class ConfigError(RuntimeError):
    """A setting is missing or malformed. The message names the variable, never its value."""


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str


@dataclass(frozen=True)
class AppConfig:
    # The URL carries the database password.
    database_url: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    # The access token cannot be revoked, so its lifetime is the bound on a stolen one.
    jwt_ttl: timedelta
    refresh_ttl: timedelta
    cookie_secure: bool
    google: GoogleConfig
    credential_keys: Mapping[int, bytes] = field(repr=False)
    credential_key_version: int


def database_url() -> str:
    """The database the platform connects to.

    Raises rather than defaulting. A silent default would point a production process at a
    local database, and the failure would look like an empty account.
    """
    return _required(os.environ, "DATABASE_URL")


def load_config(environ: Mapping[str, str]) -> AppConfig:
    """Everything the web process needs, read and checked once at start-up.

    `environ` is an argument so a test can hand over a plain dict. Only the entry point
    passes `os.environ`.
    """
    jwt_secret = _required(environ, "JWT_SECRET")
    if len(jwt_secret) < MIN_JWT_SECRET_CHARS:
        raise ConfigError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_CHARS} characters")

    keys = _master_keys(_required(environ, "CREDENTIAL_KEYS"))
    version = _positive(environ, "CREDENTIAL_KEY_VERSION")
    if version not in keys:
        raise ConfigError("CREDENTIAL_KEY_VERSION names a key that CREDENTIAL_KEYS does not hold")

    return AppConfig(
        database_url=_required(environ, "DATABASE_URL"),
        jwt_secret=jwt_secret,
        jwt_ttl=timedelta(minutes=_positive(environ, "JWT_TTL_MINUTES", default=DEFAULT_JWT_TTL_MINUTES)),
        refresh_ttl=timedelta(days=_positive(environ, "REFRESH_TTL_DAYS", default=DEFAULT_REFRESH_TTL_DAYS)),
        cookie_secure=_flag(environ, "COOKIE_SECURE", default=True),
        google=GoogleConfig(
            client_id=_required(environ, "GOOGLE_CLIENT_ID"),
            client_secret=_required(environ, "GOOGLE_CLIENT_SECRET"),
            redirect_uri=_required(environ, "GOOGLE_REDIRECT_URI"),
        ),
        credential_keys=keys,
        credential_key_version=version,
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _positive(environ: Mapping[str, str], name: str, default: int | None = None) -> int:
    raw = environ.get(name, "")
    if not raw:
        if default is None:
            raise ConfigError(f"{name} is not set")
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} is not an integer") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def _flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise ConfigError(f"{name} must be true or false")


def _master_keys(raw: str) -> dict[int, bytes]:
    """`1:<base64>,2:<base64>`.

    Every version that still seals a stored record must stay listed. Removing one makes
    those records unreadable.
    """
    keys: dict[int, bytes] = {}
    for entry in raw.split(","):
        version_text, separator, encoded = entry.strip().partition(":")
        if not separator:
            raise ConfigError("CREDENTIAL_KEYS entries must look like <version>:<base64>")
        try:
            version = int(version_text)
            key = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ConfigError("CREDENTIAL_KEYS holds an entry that does not parse") from None
        if len(key) != MASTER_KEY_BYTES:
            raise ConfigError(f"CREDENTIAL_KEYS version {version} is not {MASTER_KEY_BYTES} bytes")
        if version in keys:
            raise ConfigError(f"CREDENTIAL_KEYS lists version {version} twice")
        keys[version] = key
    return keys
