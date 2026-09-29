# Phase 4 — Identity and the Read Path

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person signs in with Google, registers a Kraken key that is validated and then
stored encrypted, declares a fiat and target weights, and reads their real portfolio —
through a REST API that has no way to place an order.

**Architecture:** `core/` gains four pure modules — the cipher, the tokens, Kraken's asset
names, the portfolio view — two that do I/O through injected clients (Google sign-in and
the portfolio read), and one over the database: the rotation of refresh tokens. Sign-in
issues a short-lived JWT and a rotating refresh token that the server stores hashed and can
revoke. `api/` is a thin FastAPI layer over them. Every dependency
the application needs is built once into an `AppContext` and passed to `create_app`, so a
test builds the same application with fake Kraken and Google transports and a database
session that is rolled back.

**Tech Stack:** Python 3.13, FastAPI, PyJWT, cryptography (AES-GCM), httpx, SQLAlchemy, Alembic.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §3.1, §3.3, §5, §6, §10.4, §11, §12, §15

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 4 of 8

## Global Constraints

- **Python 3.13.** One version, not a range.
- **Money is `Decimal`, never `float`.** A JSON response carries every amount as a string.
- **Pin every dependency with `==`.**
- **No test reads configuration from the environment.** `load_config` takes a mapping, and
  every test hands it a plain dict.
- **No test touches the network.** Kraken and Google are answered by `httpx.MockTransport`.
- **No endpoint returns a Kraken credential**, not even in an error. No log line contains one.
- **Every endpoint is scoped to the authenticated user.** No route takes a user id.
- **This phase cannot place an order.** A test fails if `add_order` appears under `api/`
  or `core/`.
- **Coverage gate is 80 %**, enforced by the CI command. `api` joins the measured sources.
- **`ruff check` and `ruff format --check` must pass.**
- Commit messages follow Conventional Commits.

## Review Focus

The spec does not name these inputs, and each one breaks a person's trust if it is wrong.
Each has a test in the task that owns the code.

1. **A request body that fails validation.** FastAPI's default 422 echoes the rejected
   value in an `input` field; on `POST /credentials` that value is a Kraken key or secret.
   Checked while writing this plan: a `SecretStr` does not stop it. → Task 10.
2. **A dark-pool pair.** Kraken lists `XXBTZEUR.d` with the same base and quote as
   `XXBTZEUR`, and it does not accept market orders. An asset must never resolve to it. → Task 5.
3. **Balances under three names.** Kraken reports `XXBT`, `XBT.F` and `DOT.S` in one
   `Balance` answer. `.F` is tradable through its base asset and counts; `.S` is staked and
   cannot be sold now. A wrong fold shows the wrong weights. → Task 6.
4. **A refresh token presented a second time.** One of the two holders is a thief, and
   the server cannot tell which, so the whole family is revoked. The refusal must not
   raise: an exception rolls the request back, and the revocation with it. → Tasks 8 and 9.
5. **A managed asset Kraken returns no price for.** A valuation that silently leaves it
   out has every weight wrong. The refresh must fail and record nothing. → Task 12.

---

## What Kraken and Google actually say

Every fact below was read from the provider's documentation or live endpoint while
writing this plan.

| Fact | Source |
|---|---|
| `Balance` keys are Kraken's internal names: `ZUSD`, `XXBT`, `XETH` | [Balance](https://docs.kraken.com/api/docs/rest-api/get-account-balance) |
| A balance key can carry a suffix: `.S` staked, `.M` opt-in rewards, `.F` Kraken Rewards, `.B` yield-bearing, `.T` tokenized. They are read-only: "use the base asset (e.g. `USDT` to transact with your `USDT` and `USDT.F` balances)" | [Balance](https://docs.kraken.com/api/docs/rest-api/get-account-balance) |
| `Assets` maps each internal name (`XXBT`, `ZEUR`) to an `altname` | [Assets](https://docs.kraken.com/api/docs/rest-api/get-asset-info) |
| `EAPI:Invalid key`: the key is missing, malformed, deleted or revoked. `EAPI:Invalid signature`: the `API-Sign` does not match. `EAPI:Invalid nonce`: the nonce is not above the last one accepted | [Spot errors](https://docs.kraken.com/api/docs/guides/spot-errors) |
| `EGeneral:Temporary lockout` follows too many sequential `EAPI:Invalid key` errors | [Spot errors](https://docs.kraken.com/api/docs/guides/spot-errors) |
| Google: authorize `https://accounts.google.com/o/oauth2/v2/auth`, token `https://oauth2.googleapis.com/token`, userinfo `https://openidconnect.googleapis.com/v1/userinfo`, PKCE `S256` supported | [discovery document](https://accounts.google.com/.well-known/openid-configuration) |

Two library facts were also checked by running them, not recalled:

- **FastAPI runs the exit code of a `yield` dependency after the response is sent**, by
  default. A commit that fails there reaches the client as a 200. With
  `Depends(..., scope="function")` it runs before, and the same failure is a 500.
- **PyJWT's `require` option accepts custom claims** (`typ`), and a token signed with
  `alg: none` is refused when `algorithms=["HS256"]` is pinned.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/config.py` | `load_config(environ) -> AppConfig`; `database_url()` stays for Alembic |
| `core/crypto.py` | `CredentialCipher` — AES-GCM, one payload, bound to the user id |
| `core/tokens.py` | `TokenSigner` — the access token and the login state, both JWTs; refresh token values and their hash |
| `core/refresh.py` | `start_family`, `rotate`, `revoke` — the life of a refresh token |
| `core/db/models.py` | Gains `RefreshToken` |
| `core/db/refresh_tokens.py` | The refresh token DAL |
| `scripts/migrations/versions/<rev>_refresh_tokens.py` | The `refresh_tokens` table, autogenerated |
| `core/google.py` | The authorization URL, the code exchange, the verified identity |
| `core/markets.py` | Kraken's asset names and the pair that trades an asset against a fiat |
| `core/portfolio.py` | `build_view` — balances, prices and targets into one view, pure |
| `core/reading.py` | `read_portfolio` — the Kraken reads a view needs, through injected clients |
| `core/db/settings.py` | Gains `lock_settings` |
| `exchange/client.py` | Gains `assets()`, `KrakenError`, `KeyRefused` |
| `exchange/keys.py`, `exchange/types.py` | Gain `KeyRejection.INVALID_KEY` |
| `api/context.py` | `AppContext` — every dependency, built once |
| `api/app.py` | `create_app(context)` and the validation-error handler |
| `api/deps.py` | The database session, the context, the current user |
| `api/schemas.py` | Every request and response model |
| `api/main.py` | The process entry point, the only caller of `load_config(os.environ)` |
| `api/routes/{health,auth,credentials,config,assets,portfolio,history}.py` | One router each |
| `tests/unit/core/test_{config,crypto,tokens,google,markets,portfolio,reading}.py` | The pure and injected modules |
| `tests/integration/test_api_*.py` | Every route, against a real Postgres and fake providers |

Route tests are **integration** tests: every route reads or writes the database. The
providers are fake; the database is not.

---

## Decisions taken in this plan

- **Google only.** Chosen by the user.
- **A short-lived access token and a rotating refresh token.** Chosen by the user: the
  standard pattern.
  - The **access token** is a JWT that lives 15 minutes by default. It is verified without
    a database read of the token, and it cannot be revoked; its short life is the bound.
    The status check on every request still makes disabling an account immediate.
  - The **refresh token** is 32 random bytes. The server stores only its SHA-256, which is
    enough for a value with that much entropy. It is good for **one** use: every refresh
    marks it used and issues a new one in the same *family*.
  - **A sign-in has an absolute lifetime**, 30 days by default, counted from the Google
    login. Every token of a family expires at the same moment, and refreshing never moves
    it. After that the person signs in with Google again, however active they were.
  - **Reuse detection.** A used token presented again means two parties hold the family.
    The server cannot tell the owner from the thief, so it revokes the whole family and
    both must sign in again.
  - **Logout revokes the family.** An access token issued before it keeps working for at
    most its remaining 15 minutes, which is the accepted trade of every stateless access
    token. Task 13 writes it into §15.
- **Transport.** Sign-in and refresh return both tokens in the JSON body, for the project 2
  application, and also set them as `HttpOnly` cookies, for a browser during this phase:
  - the access cookie is `SameSite=Lax` with path `/`. `Lax`, because it must survive
    Google's redirect back.
  - the refresh cookie is `SameSite=Strict` with path `/auth`. It is sent only to the auth
    routes, and never with a request that another site starts.
- **A refused refresh returns its response; it does not raise.** Every route runs in one
  transaction that an exception rolls back. A reuse that revoked a family and then raised
  would undo the revocation it had just made.
- **The login state travels in a signed cookie, not a server table.** The `state` and the
  PKCE verifier are a second JWT with `typ: login-state`, a 10-minute life and a cookie path
  of `/auth/callback`. A `typ` claim keeps either token from being presented as the other.
- **The ciphertext is bound to its user.** The user id is AES-GCM's associated data. A
  database row copied onto another user's record does not decrypt.
- **An asset is stored under Kraken's short name, upper case: `XBT`, not `BTC`.** Kraken's
  vocabulary is translated at `core/markets.py` only. Accepting `BTC` is a presentation
  concern for the project 2 application.
- **The first `PATCH /config` creates the settings and must carry `fiat`.** After that
  `fiat` is refused unless it is unchanged. The supported fiats are a constant, not a
  Kraken call.
- **A snapshot's `total_value` is the managed value: managed assets plus cash.** It is the
  denominator of every weight (§3.2). Unmanaged holdings sit in `holdings`, valued when
  Kraken has a pair to the fiat and left unvalued when it does not.
- **`validate_key` now tells a wrong key from an unreachable Kraken.** Phase 3 reported
  both as `UNREACHABLE`. A wrong key is `422 invalid_key`; an outage is `503`. Only
  `GetApiKeyInfo` asks the client to make the distinction.

## What this phase deliberately leaves out

- **Any order.** `add_order` exists in `exchange/` and nothing in `api/` or `core/` calls it.
- **The scheduler.** `next_invest_at` and `next_rebalance_at` are shown by `GET /config`
  and set by nothing. A test refuses them in `PATCH /config`.
- **The proposal endpoints**, `POST /rebalance` — phase 6.
- **Re-verifying a stored key's permissions** — accepted in §15.
- **Master-key rotation as a procedure.** The cipher opens every version listed and seals
  with the active one; the runbook is phase 8.
- **A grace window for two refreshes at once.** Two browser tabs that refresh with the
  same token look like reuse, and the user signs in again. Strict detection is the safe
  default; a few seconds of grace is a later refinement if it proves annoying.
- **Deleting expired refresh tokens.** `delete_expired_refresh_tokens` exists and is
  tested; the scheduler calls it in phase 7, beside the `sessions` retention.

---

### Task 1: Dependencies and the application's configuration

**Files:**
- Modify: `requirements.txt`, `pyproject.toml`, `.env.example`, `core/config.py`
- Test: `tests/unit/core/test_config.py`

**Interfaces:**
- Produces: `GoogleConfig(client_id, client_secret, redirect_uri)`,
  `AppConfig(database_url, jwt_secret, jwt_ttl, refresh_ttl, cookie_secure, google, credential_keys, credential_key_version)`,
  `load_config(environ: Mapping[str, str]) -> AppConfig`, `ConfigError(RuntimeError)`.
  `database_url()` keeps its behaviour.

- [ ] **Step 1: Add the dependencies**

`requirements.txt` becomes:

```
SQLAlchemy==2.0.54
alembic==1.20.0
psycopg[binary]==3.3.6
httpx==0.28.1
fastapi==0.141.1
uvicorn==0.54.0
PyJWT==2.15.1
cryptography==50.0.1
```

In `pyproject.toml`, `[tool.coverage.run]` becomes:

```toml
[tool.coverage.run]
source = ["engine", "core", "exchange", "api"]
```

Run: `.venv/Scripts/python.exe -m pip install -r requirements.txt`

Expect one `StarletteDeprecationWarning` from `fastapi.testclient` in later test runs
(Starlette 1.7 prefers a package called `httpx2`). It is a warning about the test client,
not about the application, and it is left visible rather than filtered.

- [ ] **Step 2: Write the failing tests**

The imports at the top of `tests/unit/core/test_config.py` become:

```python
import base64
from datetime import timedelta

import pytest

from core.config import ConfigError, database_url, load_config
```

Append:

```python
MASTER_KEY = bytes(range(32))


def _env(**overrides):
    """A complete environment. `None` removes a variable."""
    env = {
        "DATABASE_URL": "postgresql+psycopg://user:dbpassword@host:5432/db",
        "JWT_SECRET": "j" * 32,
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/auth/callback/google",
        "CREDENTIAL_KEYS": "1:" + base64.b64encode(MASTER_KEY).decode(),
        "CREDENTIAL_KEY_VERSION": "1",
    }
    env.update(overrides)
    return {name: value for name, value in env.items() if value is not None}


def test_a_complete_environment_loads_with_its_defaults():
    config = load_config(_env())

    assert config.jwt_ttl == timedelta(minutes=15)
    assert config.refresh_ttl == timedelta(days=30)
    assert config.cookie_secure is True
    assert config.credential_keys == {1: MASTER_KEY}
    assert config.credential_key_version == 1
    assert config.google.client_id == "client-id"


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_URL",
        "JWT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "CREDENTIAL_KEYS",
        "CREDENTIAL_KEY_VERSION",
    ],
)
def test_every_required_variable_is_named_when_it_is_missing(name):
    with pytest.raises(ConfigError, match=name):
        load_config(_env(**{name: None}))


def test_a_short_signing_secret_is_refused():
    """A short HMAC key can be brute-forced offline from one captured token."""
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_config(_env(JWT_SECRET="j" * 31))


def test_a_master_key_of_the_wrong_length_is_refused():
    short = base64.b64encode(bytes(16)).decode()

    with pytest.raises(ConfigError, match="32 bytes"):
        load_config(_env(CREDENTIAL_KEYS=f"1:{short}"))


def test_the_active_version_must_be_one_of_the_keys():
    with pytest.raises(ConfigError, match="CREDENTIAL_KEY_VERSION"):
        load_config(_env(CREDENTIAL_KEY_VERSION="2"))


def test_several_key_versions_are_kept_for_rotation():
    second = bytes(range(32, 64))
    listed = f"1:{base64.b64encode(MASTER_KEY).decode()},2:{base64.b64encode(second).decode()}"

    config = load_config(_env(CREDENTIAL_KEYS=listed, CREDENTIAL_KEY_VERSION="2"))

    assert config.credential_keys == {1: MASTER_KEY, 2: second}


@pytest.mark.parametrize("listed", ["no-colon-here", "one:AAAA", "1:not base64!"])
def test_a_malformed_key_list_is_refused(listed):
    with pytest.raises(ConfigError, match="CREDENTIAL_KEYS"):
        load_config(_env(CREDENTIAL_KEYS=listed))


def test_a_version_listed_twice_is_refused():
    encoded = base64.b64encode(MASTER_KEY).decode()

    with pytest.raises(ConfigError, match="twice"):
        load_config(_env(CREDENTIAL_KEYS=f"1:{encoded},1:{encoded}"))


def test_the_cookie_can_be_sent_over_plain_http_for_local_development():
    assert load_config(_env(COOKIE_SECURE="false")).cookie_secure is False


@pytest.mark.parametrize("name", ["JWT_TTL_MINUTES", "REFRESH_TTL_DAYS"])
def test_a_token_lifetime_of_zero_is_refused(name):
    with pytest.raises(ConfigError, match=name):
        load_config(_env(**{name: "0"}))


def test_the_lifetimes_can_be_set():
    config = load_config(_env(JWT_TTL_MINUTES="5", REFRESH_TTL_DAYS="7"))

    assert config.jwt_ttl == timedelta(minutes=5)
    assert config.refresh_ttl == timedelta(days=7)


def test_the_repr_carries_no_secret():
    """A config object that reaches a log line through a repr must not carry its secrets."""
    text = repr(load_config(_env()))

    assert "google-client-secret" not in text
    assert "j" * 32 not in text
    assert "dbpassword" not in text
    assert repr(MASTER_KEY) not in text
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConfigError'`

- [ ] **Step 4: Write the implementation**

`core/config.py` becomes:

```python
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
```

`binascii.Error`, which `b64decode` raises, is a subclass of `ValueError`, so one clause
covers both parses.

- [ ] **Step 5: Document the variables**

Append to `.env.example`:

```
# Signs access tokens. At least 32 characters:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=
# Access token lifetime. An access token cannot be revoked, so keep it short.
JWT_TTL_MINUTES=15
# How long a sign-in lasts, counted from the Google login. Refreshing never extends it.
REFRESH_TTL_DAYS=30
# false only for http://localhost during development.
COOKIE_SECURE=false

# Google Cloud console: an OAuth client of type "Web application".
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google

# Encrypts stored Kraken keys. <version>:<base64 of 32 random bytes>, comma separated:
#   python -c "import os, base64; print('1:' + base64.b64encode(os.urandom(32)).decode())"
# Losing it makes every stored key unreadable. Back it up outside this machine.
CREDENTIAL_KEYS=
CREDENTIAL_KEY_VERSION=1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_config.py -v`
Expected: PASS, including the two tests that were already there.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml .env.example core/config.py tests/unit/core/test_config.py
git commit -m "feat(core): load the web process configuration from one mapping"
```

---

### Task 2: The credential cipher

**Files:**
- Create: `core/crypto.py`
- Test: `tests/unit/core/test_crypto.py`

**Interfaces:**
- Consumes: `exchange.types.Credentials`
- Produces: `Sealed(ciphertext: bytes, nonce: bytes, key_version: int)`,
  `CredentialCipher(keys: Mapping[int, bytes], active_version: int)` with
  `.seal(user_id: uuid.UUID, credentials: Credentials) -> Sealed` and
  `.unseal(user_id: uuid.UUID, sealed: Sealed) -> Credentials`,
  `CredentialsUnreadable(Exception)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_crypto.py`:

```python
import uuid
from dataclasses import replace

import pytest

from core.crypto import NONCE_BYTES, CredentialCipher, CredentialsUnreadable
from exchange.types import Credentials

KEY_1 = bytes(range(32))
KEY_2 = bytes(range(32, 64))
ALICE = uuid.UUID("00000000-0000-4000-8000-00000000000a")
BOB = uuid.UUID("00000000-0000-4000-8000-00000000000b")
CREDENTIALS = Credentials(api_key="THE-PUBLIC-KEY", api_secret="THE-SECRET-VALUE")


def _cipher(keys=None, active=1):
    return CredentialCipher(keys or {1: KEY_1}, active)


def test_what_is_sealed_opens_again():
    cipher = _cipher()

    assert cipher.unseal(ALICE, cipher.seal(ALICE, CREDENTIALS)) == CREDENTIALS


def test_the_ciphertext_contains_neither_the_key_nor_the_secret():
    sealed = _cipher().seal(ALICE, CREDENTIALS)

    assert b"THE-PUBLIC-KEY" not in sealed.ciphertext
    assert b"THE-SECRET-VALUE" not in sealed.ciphertext


def test_every_seal_uses_a_fresh_nonce():
    """A nonce reused under one key breaks AES-GCM completely."""
    cipher = _cipher()

    first = cipher.seal(ALICE, CREDENTIALS)
    second = cipher.seal(ALICE, CREDENTIALS)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert len(first.nonce) == NONCE_BYTES


def test_a_record_copied_to_another_user_does_not_open():
    """The user id is the associated data, so a row moved between users is useless."""
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable):
        cipher.unseal(BOB, sealed)


def test_one_changed_byte_is_detected():
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)
    tampered = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]

    with pytest.raises(CredentialsUnreadable):
        cipher.unseal(ALICE, replace(sealed, ciphertext=tampered))


def test_a_version_with_no_key_is_unreadable_not_a_crash():
    sealed = _cipher().seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable, match="version 7"):
        _cipher().unseal(ALICE, replace(sealed, key_version=7))


def test_after_rotation_old_records_open_and_new_ones_use_the_new_key():
    old = _cipher({1: KEY_1}, 1).seal(ALICE, CREDENTIALS)
    rotated = _cipher({1: KEY_1, 2: KEY_2}, 2)

    assert rotated.unseal(ALICE, old) == CREDENTIALS
    assert rotated.seal(ALICE, CREDENTIALS).key_version == 2


def test_the_active_version_must_have_a_key():
    with pytest.raises(ValueError, match="active"):
        CredentialCipher({1: KEY_1}, 2)


def test_a_key_that_is_not_256_bits_is_refused():
    with pytest.raises(ValueError, match="32 bytes"):
        CredentialCipher({1: bytes(16)}, 1)


def test_a_failure_message_carries_no_part_of_the_credential():
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable) as caught:
        cipher.unseal(BOB, sealed)

    assert "THE-SECRET-VALUE" not in str(caught.value)
    assert "THE-PUBLIC-KEY" not in str(caught.value)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.crypto'`

- [ ] **Step 3: Write the implementation**

`core/crypto.py`:

```python
"""Encryption at rest for a user's Kraken key.

The key and the secret are one payload, sealed once under one nonce (spec §5.3). The
user id is the associated data, so a record copied onto another user's row does not
open.

What this protects is a stolen database dump. It does not protect a compromised server,
which must be able to decrypt in order to trade; the permission contract bounds that.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from exchange.types import Credentials

NONCE_BYTES = 12
KEY_BYTES = 32


class CredentialsUnreadable(Exception):
    """The record does not open: another user's row, a changed byte, or a missing key."""


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class CredentialCipher:
    """Seals with the active master key and opens with any version it holds."""

    def __init__(self, keys: Mapping[int, bytes], active_version: int) -> None:
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"master key version {version} is not {KEY_BYTES} bytes")
        if active_version not in keys:
            raise ValueError(f"the active version {active_version} has no key")
        self._keys = dict(keys)
        self._active = active_version

    def seal(self, user_id: uuid.UUID, credentials: Credentials) -> Sealed:
        payload = json.dumps({"key": credentials.api_key, "secret": credentials.api_secret}).encode("utf-8")
        # Random, never counted. A counter would have to survive restarts and replicas to
        # stay unique, and 96 random bits do not collide at this system's scale.
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self._keys[self._active]).encrypt(nonce, payload, user_id.bytes)
        return Sealed(ciphertext=ciphertext, nonce=nonce, key_version=self._active)

    def unseal(self, user_id: uuid.UUID, sealed: Sealed) -> Credentials:
        key = self._keys.get(sealed.key_version)
        if key is None:
            raise CredentialsUnreadable(f"no master key for version {sealed.key_version}")
        try:
            payload = AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, user_id.bytes)
        except InvalidTag:
            raise CredentialsUnreadable("the record does not open for this user under this key") from None
        data = json.loads(payload.decode("utf-8"))
        return Credentials(api_key=data["key"], api_secret=data["secret"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_crypto.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add core/crypto.py tests/unit/core/test_crypto.py
git commit -m "feat(core): seal a Kraken key under the master key, bound to its user"
```

---

### Task 3: Access tokens, refresh token values and the login state

**Files:**
- Create: `core/tokens.py`
- Test: `tests/unit/core/test_tokens.py`

**Interfaces:**
- Produces: `TokenSigner(secret: str, ttl: timedelta, now: Callable[[], datetime] = ...)`
  with `.issue(user_id) -> IssuedToken`, `.verify(token) -> uuid.UUID`,
  `.issue_login_state(login: LoginState) -> str`, `.verify_login_state(token) -> LoginState`;
  `IssuedToken(value: str, expires_at: datetime)`; `LoginState(state: str, verifier: str)`;
  `TokenInvalid(Exception)`; `LOGIN_STATE_TTL: timedelta`;
  `new_refresh_token() -> str`; `hash_refresh_token(value: str) -> bytes` (32 bytes).

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_tokens.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from core.tokens import AUDIENCE, ISSUER, LoginState, TokenInvalid, TokenSigner

SECRET = "s" * 32
USER = uuid.UUID("00000000-0000-4000-8000-00000000000a")


def _signer(secret=SECRET, ttl=timedelta(hours=1), now=None):
    return TokenSigner(secret, ttl, now=now or (lambda: datetime.now(UTC)))


def test_a_token_verifies_back_to_its_user():
    signer = _signer()

    assert signer.verify(signer.issue(USER).value) == USER


def test_the_expiry_is_the_lifetime_after_issue():
    issued_at = datetime.now(UTC).replace(microsecond=0)
    token = _signer(now=lambda: issued_at).issue(USER)

    assert token.expires_at == issued_at + timedelta(hours=1)


def test_an_expired_token_is_refused():
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    token = _signer(now=lambda: long_ago).issue(USER)

    with pytest.raises(TokenInvalid):
        _signer().verify(token.value)


def test_a_token_signed_with_another_secret_is_refused():
    token = _signer(secret="o" * 32).issue(USER)

    with pytest.raises(TokenInvalid):
        _signer().verify(token.value)


def test_a_token_with_a_changed_payload_is_refused():
    header, payload, signature = _signer().issue(USER).value.split(".")
    changed = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1]

    with pytest.raises(TokenInvalid):
        _signer().verify(f"{header}.{changed}.{signature}")


def test_an_unsigned_token_is_refused():
    """`alg: none` is the classic JWT bypass. The algorithm is pinned, not read from the token."""
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {"sub": str(USER), "typ": "access", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + timedelta(hours=1)},
        None,
        algorithm="none",
    )

    with pytest.raises(TokenInvalid):
        _signer().verify(unsigned)


def test_a_login_state_is_not_an_access_token():
    signer = _signer()
    state = signer.issue_login_state(LoginState(state="abc", verifier="xyz"))

    with pytest.raises(TokenInvalid):
        signer.verify(state)


def test_an_access_token_is_not_a_login_state():
    signer = _signer()

    with pytest.raises(TokenInvalid):
        signer.verify_login_state(signer.issue(USER).value)


def test_a_login_state_round_trips():
    signer = _signer()
    login = LoginState(state="abc", verifier="xyz")

    assert signer.verify_login_state(signer.issue_login_state(login)) == login


def test_a_subject_that_is_not_a_user_id_is_refused():
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": "not-a-uuid", "typ": "access", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(TokenInvalid):
        _signer().verify(forged)


def test_the_token_carries_the_user_id_and_nothing_personal():
    """A JWT is readable by anyone who holds it. It must not carry the email."""
    claims = jwt.decode(_signer().issue(USER).value, options={"verify_signature": False})

    assert set(claims) == {"sub", "typ", "iss", "aud", "iat", "exp"}


def test_the_repr_of_a_token_hides_its_value():
    token = _signer().issue(USER)

    assert token.value not in repr(token)


def test_refresh_token_values_are_long_and_never_repeat():
    values = {new_refresh_token() for _ in range(100)}

    assert len(values) == 100
    assert all(len(value) >= 43 for value in values)


def test_a_refresh_token_is_stored_as_a_fixed_length_hash():
    value = new_refresh_token()

    assert hash_refresh_token(value) == hashlib.sha256(value.encode()).digest()
    assert len(hash_refresh_token(value)) == 32
    assert value.encode() not in hash_refresh_token(value)
```

The imports at the top of the file gain `import hashlib`, and the import from
`core.tokens` becomes
`from core.tokens import AUDIENCE, ISSUER, LoginState, TokenInvalid, TokenSigner, hash_refresh_token, new_refresh_token`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.tokens'`

- [ ] **Step 3: Write the implementation**

`core/tokens.py`:

```python
"""Access tokens, refresh token values, and the state that carries a login across Google's redirect.

The access token and the login state are JWTs signed with one secret. A `typ` claim tells
them apart, so neither can be presented where the other is expected. An access token
cannot be revoked, so it is short-lived; the status check on every request, in the API
layer, is what makes disabling an account immediate.

A refresh token is not a JWT. It is a random value the server looks up, which is what
makes it revocable.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
ISSUER = "coinpilot"
AUDIENCE = "coinpilot-api"
ACCESS = "access"
LOGIN_STATE = "login-state"
LOGIN_STATE_TTL = timedelta(minutes=10)
REFRESH_TOKEN_BYTES = 32


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(value: str) -> bytes:
    """What the database stores. Plain SHA-256 is enough for 256 random bits: there is no
    dictionary to guess from, so a slow password hash would only cost time."""
    return hashlib.sha256(value.encode("utf-8")).digest()


class TokenInvalid(Exception):
    """Expired, changed, signed elsewhere, or meant for something else."""


@dataclass(frozen=True)
class IssuedToken:
    value: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class LoginState:
    """What the callback needs to finish a login it did not start."""

    state: str
    verifier: str = field(repr=False)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TokenSigner:
    def __init__(self, secret: str, ttl: timedelta, now: Callable[[], datetime] = _utcnow) -> None:
        self._secret = secret
        self._ttl = ttl
        self._now = now

    def issue(self, user_id: uuid.UUID) -> IssuedToken:
        issued = self._now()
        expires = issued + self._ttl
        return IssuedToken(value=self._encode({"sub": str(user_id), "typ": ACCESS}, issued, expires), expires_at=expires)

    def verify(self, token: str) -> uuid.UUID:
        claims = self._decode(token, ACCESS)
        try:
            return uuid.UUID(str(claims["sub"]))
        except (KeyError, ValueError):
            raise TokenInvalid("the subject is not a user id") from None

    def issue_login_state(self, login: LoginState) -> str:
        issued = self._now()
        claims = {"state": login.state, "verifier": login.verifier, "typ": LOGIN_STATE}
        return self._encode(claims, issued, issued + LOGIN_STATE_TTL)

    def verify_login_state(self, token: str) -> LoginState:
        claims = self._decode(token, LOGIN_STATE)
        try:
            return LoginState(state=str(claims["state"]), verifier=str(claims["verifier"]))
        except KeyError:
            raise TokenInvalid("the login state is incomplete") from None

    def _encode(self, claims: dict[str, str], issued: datetime, expires: datetime) -> str:
        payload = {**claims, "iss": ISSUER, "aud": AUDIENCE, "iat": issued, "exp": expires}
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def _decode(self, token: str, expected_type: str) -> dict[str, object]:
        try:
            # The algorithm list is pinned: reading it from the token header is how an
            # `alg: none` token gets accepted.
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "typ"]},
            )
        except jwt.PyJWTError:
            raise TokenInvalid("the token does not verify") from None
        if claims.get("typ") != expected_type:
            raise TokenInvalid("the token is meant for something else")
        return claims
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_tokens.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add core/tokens.py tests/unit/core/test_tokens.py
git commit -m "feat(core): typed JWTs for access and login state, and refresh token values"
```

---

### Task 4: A wrong key is not an outage, and Kraken's asset names

**Files:**
- Modify: `exchange/types.py`, `exchange/client.py`, `exchange/keys.py`
- Test: `tests/unit/exchange/test_client.py`, `tests/unit/exchange/test_keys.py`

**Interfaces:**
- Produces: `KeyRejection.INVALID_KEY`; `exchange.client.KrakenError(RuntimeError)` with
  `.errors: tuple[str, ...]`; `exchange.client.KeyRefused(Exception)`;
  `KrakenClient.assets() -> dict[str, str] | None` (internal name to short name).
  `KrakenClient.api_key_info()` now raises `KeyRefused` when Kraken refuses the key or
  its secret; every other method is unchanged and still returns `None` on any failure.

Phase 3 reported a wrong key and an unreachable Kraken both as `UNREACHABLE`. Both were
refused, so nothing was unsafe, but a person who mistyped their secret was told Kraken
was down.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/exchange/test_client.py`, the import from `exchange.client` becomes
`from exchange.client import KeyRefused, KrakenClient, MissingCredentials, build_http_client`.
Append:

```python
def _error(*errors):
    return httpx.Response(200, json={"error": list(errors), "result": {}})


@pytest.mark.parametrize("error", ["EAPI:Invalid key", "EAPI:Invalid signature"])
def test_a_refused_key_is_told_apart_when_validating(error):
    client = _client(lambda request: _error(error))

    with pytest.raises(KeyRefused):
        client.api_key_info()


def test_a_secret_that_is_not_base64_is_a_refused_key_when_validating():
    """Kraken issues base64 secrets. One that does not decode was mistyped."""
    client = _client(
        lambda request: _ok({}),
        credentials=Credentials(api_key="THE-PUBLIC-KEY", api_secret="not base64 at all!"),
    )

    with pytest.raises(KeyRefused):
        client.api_key_info()


def test_a_bad_nonce_is_this_systems_problem_not_the_keys():
    client = _client(lambda request: _error("EAPI:Invalid nonce"))

    assert client.api_key_info() is None


def test_an_outage_while_validating_is_still_none():
    def handler(request):
        raise httpx.ConnectError("connection failed")

    assert _client(handler).api_key_info() is None


def test_outside_validation_a_refused_key_is_just_another_none():
    """The distinction is asked for at one call site. Everywhere else a failure is `None`."""
    client = _client(lambda request: _error("EAPI:Invalid key"))

    assert client.balance() is None


def test_a_refusal_is_logged_without_the_key(caplog):
    client = _client(lambda request: _error("EAPI:Invalid key"))

    with caplog.at_level(logging.DEBUG, logger="coinpilot.exchange"), pytest.raises(KeyRefused):
        client.api_key_info()

    assert "refused" in caplog.text
    assert CREDENTIALS.api_key not in caplog.text
    assert CREDENTIALS.api_secret not in caplog.text


def test_asset_names_map_the_internal_name_to_the_short_one():
    raw = {"XXBT": {"altname": "XBT", "decimals": 10}, "ZEUR": {"altname": "EUR"}, "SOL": {"altname": "SOL"}}
    client = _client(lambda request: _ok(raw))

    assert client.assets() == {"XXBT": "XBT", "ZEUR": "EUR", "SOL": "SOL"}


def test_an_asset_with_no_short_name_is_skipped():
    client = _client(lambda request: _ok({"XXBT": {"altname": "XBT"}, "ODD": {"decimals": 8}}))

    assert client.assets() == {"XXBT": "XBT"}


def test_asset_names_are_none_when_kraken_cannot_be_read():
    assert _client(lambda request: httpx.Response(503)).assets() is None
```

In `tests/unit/exchange/test_keys.py`, add `from exchange.client import KeyRefused` to the
imports at the top. Append:

```python
class RefusingClient:
    def api_key_info(self):
        raise KeyRefused("GetApiKeyInfo")


def test_a_key_kraken_refuses_is_invalid_not_unreachable():
    """The person mistyped something. Telling them Kraken is down sends them to wait."""
    result = validate_key(RefusingClient())

    assert result.accepted is False
    assert result.rejection is KeyRejection.INVALID_KEY
    assert result.permissions == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/exchange -v`
Expected: FAIL with `ImportError: cannot import name 'KeyRefused'`

- [ ] **Step 3: Add the rejection**

In `exchange/types.py`, `KeyRejection` becomes:

```python
class KeyRejection(StrEnum):
    """Why a key was refused. Never shown to anyone but its own owner."""

    FORBIDDEN_PERMISSIONS = "forbidden_permissions"
    INVALID_KEY = "invalid_key"
    MISSING_PERMISSIONS = "missing_permissions"
    UNREACHABLE = "unreachable"
```

- [ ] **Step 4: Teach the client the difference**

In `exchange/client.py`, below `MissingCredentials`, add:

```python
class KrakenError(RuntimeError):
    """Kraken answered, and the answer was an error."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"kraken returned {errors}")
        self.errors = tuple(errors)


class KeyRefused(Exception):
    """Kraken says this key, or its secret, is not valid.

    Raised only where the caller asked to tell this apart from an outage. Everywhere else
    it is one more `None`.
    """


# A nonce error is left out on purpose: it means this system's clock or counter is wrong,
# not that the person typed the wrong key.
_REFUSED_KEY_ERRORS = ("EAPI:Invalid key", "EAPI:Invalid signature")


def _is_refusal(errors: tuple[str, ...]) -> bool:
    return any(str(error).startswith(_REFUSED_KEY_ERRORS) for error in errors)
```

Replace `_private`, `_unwrap` and `_safely` with:

```python
    def _private(
        self,
        endpoint: str,
        payload: Mapping[str, str] | None = None,
        *,
        refusals: bool = False,
    ) -> dict | None:
        credentials = self._credentials
        if credentials is None:
            raise MissingCredentials(endpoint)
        path = f"/0/private/{endpoint}"

        def call() -> dict:
            self._limiter.wait_turn(credentials.api_key)
            nonce = self._limiter.next_nonce(credentials.api_key)
            body = encode_body({"nonce": nonce, **dict(payload or {})})
            try:
                signature = sign(path, nonce, body, credentials.api_secret)
            except ValueError:
                # Kraken issues base64 secrets, so one that does not decode was mistyped.
                if refusals:
                    raise KeyRefused(endpoint) from None
                raise
            headers = {
                "API-Key": credentials.api_key,
                "API-Sign": signature,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            response = self._http.post(path, content=body, headers=headers)
            response.raise_for_status()
            return self._unwrap(response.json())

        return self._safely(call, endpoint, refusals=refusals)

    @staticmethod
    def _unwrap(payload: dict) -> dict:
        errors = [entry for entry in payload.get("error", []) if _is_error(entry)]
        if errors:
            raise KrakenError(errors)
        return payload.get("result", {})

    def _safely(self, call: Callable[[], dict], endpoint: str, *, refusals: bool = False) -> dict | None:
        try:
            return call()
        except KeyRefused:
            logger.warning("kraken %s refused the key", endpoint)
            raise
        except KrakenError as exc:
            if refusals and _is_refusal(exc.errors):
                logger.warning("kraken %s refused the key", endpoint)
                raise KeyRefused(endpoint) from None
            logger.warning("kraken %s failed: %s", endpoint, self._redact(str(exc)))
            return None
        except Exception as exc:
            logger.warning("kraken %s failed: %s", endpoint, self._redact(str(exc)))
            return None
```

`api_key_info` becomes:

```python
    def api_key_info(self) -> dict | None:
        """Requires no permission to call, which is why key validation starts here.

        Raises `KeyRefused` when Kraken says the key or its secret is wrong. `None` still
        means Kraken could not be asked.
        """
        return self._private("GetApiKeyInfo", refusals=True)
```

Add, after `ticker`:

```python
    def assets(self) -> dict[str, str] | None:
        """Kraken's internal name for every asset, mapped to its short name: `XXBT` to `XBT`."""
        raw = self._public("Assets")
        if raw is None:
            return None
        return {
            name: str(entry["altname"])
            for name, entry in raw.items()
            if isinstance(entry, dict) and entry.get("altname")
        }
```

- [ ] **Step 5: Let `validate_key` report it**

In `exchange/keys.py`, replace the `_UNREACHABLE` constant and the start of `validate_key`:

```python
from exchange.client import KeyRefused
from exchange.types import KeyRejection, KeyValidation


def _refused(rejection: KeyRejection) -> KeyValidation:
    return KeyValidation(
        accepted=False,
        rejection=rejection,
        permissions=(),
        missing=(),
        forbidden=(),
        ip_allowlist=(),
    )


def validate_key(client) -> KeyValidation:
    """Read the key's permissions and decide whether it may be stored.

    A key that cannot be read is rejected, not deferred. Storing a key that was never
    validated is the one outcome this contract exists to prevent.
    """
    try:
        info = client.api_key_info()
    except KeyRefused:
        return _refused(KeyRejection.INVALID_KEY)
    if info is None:
        return _refused(KeyRejection.UNREACHABLE)
```

The rest of the function is unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/exchange -v`
Expected: PASS, the phase 3 tests included. `test_a_kraken_error_becomes_none` still passes
because `KrakenError` is still caught.

- [ ] **Step 7: Commit**

```bash
git add exchange tests/unit/exchange
git commit -m "feat(exchange): tell a refused key from an unreachable Kraken"
```

---

### Task 5: Kraken's asset names, and the pair for an asset

**Files:**
- Create: `core/markets.py`
- Test: `tests/unit/core/test_markets.py`

**Interfaces:**
- Consumes: `exchange.types.PairMeta`
- Produces: `short_name(code, asset_names) -> str | None`,
  `kraken_key(short, asset_names) -> str | None`,
  `split_balance_key(key, asset_names) -> tuple[str, str]`,
  `resolve_pair(asset, fiat, asset_names, pairs) -> PairMeta | None`,
  `TRADABLE_SUFFIXES`, `SUPPORTED_FIATS`. `asset_names` is what `KrakenClient.assets()`
  returns; `pairs` is what `KrakenClient.asset_pairs()` returns.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_markets.py`:

```python
from decimal import Decimal

import pytest

from core.markets import kraken_key, resolve_pair, short_name, split_balance_key
from exchange.types import PairMeta

NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "ZUSD": "USD", "SOL": "SOL"}


def _pair(name, base, quote, status="online"):
    return PairMeta(
        pair=name,
        altname=name,
        base=base,
        quote=quote,
        price_decimals=1,
        volume_decimals=8,
        order_min=Decimal("0.0001"),
        cost_min=Decimal("0.5"),
        status=status,
    )


PAIRS = {
    "XXBTZEUR": _pair("XXBTZEUR", "XXBT", "ZEUR"),
    "XXBTZUSD": _pair("XXBTZUSD", "XXBT", "ZUSD"),
    "SOLEUR": _pair("SOLEUR", "SOL", "ZEUR"),
}


@pytest.mark.parametrize(("code", "expected"), [("XBT", "XBT"), ("xbt", "XBT"), ("XXBT", "XBT"), (" sol ", "SOL")])
def test_an_asset_is_known_by_its_short_name_or_its_internal_one(code, expected):
    assert short_name(code, NAMES) == expected


@pytest.mark.parametrize("code", ["BTC", "", "NOPE"])
def test_a_name_kraken_does_not_list_is_none(code):
    assert short_name(code, NAMES) is None


def test_the_internal_name_is_found_from_the_short_one():
    assert kraken_key("xbt", NAMES) == "XXBT"
    assert kraken_key("BTC", NAMES) is None


@pytest.mark.parametrize(
    ("key", "expected"),
    [("XXBT", ("XBT", "")), ("XBT.F", ("XBT", "F")), ("DOT.S", ("DOT", "S")), ("ZEUR", ("EUR", ""))],
)
def test_a_balance_key_splits_into_the_asset_and_its_suffix(key, expected):
    assert split_balance_key(key, NAMES) == expected


def test_an_asset_resolves_to_its_pair_against_the_fiat():
    assert resolve_pair("XBT", "EUR", NAMES, PAIRS).pair == "XXBTZEUR"
    assert resolve_pair("XBT", "USD", NAMES, PAIRS).pair == "XXBTZUSD"


def test_a_pair_whose_internal_name_is_its_short_name_resolves_too():
    assert resolve_pair("SOL", "EUR", NAMES, PAIRS).pair == "SOLEUR"


def test_a_dark_pool_pair_is_never_the_answer():
    """Same base and quote as the lit pair, and it does not take market orders."""
    only_dark = {"XXBTZEUR.d": _pair("XXBTZEUR.d", "XXBT", "ZEUR")}

    assert resolve_pair("XBT", "EUR", NAMES, only_dark) is None


def test_the_lit_pair_wins_when_both_are_listed():
    both = {**PAIRS, "XXBTZEUR.d": _pair("XXBTZEUR.d", "XXBT", "ZEUR")}

    assert resolve_pair("XBT", "EUR", NAMES, both).pair == "XXBTZEUR"


def test_a_pair_that_is_not_online_is_refused_now_rather_than_at_order_time():
    halted = {"XXBTZEUR": _pair("XXBTZEUR", "XXBT", "ZEUR", status="cancel_only")}

    assert resolve_pair("XBT", "EUR", NAMES, halted) is None


def test_an_asset_with_no_pair_against_this_fiat_is_none():
    assert resolve_pair("ETH", "EUR", NAMES, PAIRS) is None


def test_the_fiat_is_not_an_asset_of_itself():
    assert resolve_pair("EUR", "EUR", NAMES, PAIRS) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_markets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.markets'`

- [ ] **Step 3: Write the implementation**

`core/markets.py`:

```python
"""Kraken's asset names, and the pair that trades one asset against the user's fiat.

Kraken names an asset three ways. `Balance` and `AssetPairs` use the internal name
(`XXBT`, `ZEUR`); people and newer endpoints use the short name (`XBT`, `EUR`); a balance
held in an earn product carries a suffix (`XBT.F`). This system stores the short name, in
upper case, and translates here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping

from exchange.types import PairMeta

# `.F` is Kraken Rewards: read-only as an asset and traded through its base asset, so it
# counts as holdings. Every other suffix is staked or bonded and cannot be sold now.
TRADABLE_SUFFIXES = frozenset({"", "F"})

# A dark-pool pair has the same base and quote as the lit one. It does not accept market
# orders, so an asset must never resolve to it.
DARK_POOL_SUFFIX = ".d"

# A constant, not a Kraken call: the fiat is chosen once and never changes.
SUPPORTED_FIATS = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD")


def short_name(code: str, asset_names: Mapping[str, str]) -> str | None:
    """The short name for a short or internal name, or `None` if Kraken does not list it."""
    wanted = code.strip().upper()
    if not wanted:
        return None
    for internal, short in asset_names.items():
        if wanted in (internal.upper(), short.upper()):
            return short.upper()
    return None


def kraken_key(short: str, asset_names: Mapping[str, str]) -> str | None:
    wanted = short.strip().upper()
    for internal, name in asset_names.items():
        if name.upper() == wanted:
            return internal
    return None


def split_balance_key(key: str, asset_names: Mapping[str, str]) -> tuple[str, str]:
    """`XBT.F` is (`XBT`, `F`). `XXBT` is (`XBT`, ``). An unlisted base keeps its own name."""
    base, _, suffix = key.partition(".")
    return short_name(base, asset_names) or base.upper(), suffix


def resolve_pair(
    asset: str,
    fiat: str,
    asset_names: Mapping[str, str],
    pairs: Mapping[str, PairMeta],
) -> PairMeta | None:
    """The one pair that trades `asset` against `fiat` with a market order, or `None`."""
    base = kraken_key(asset, asset_names)
    quote = kraken_key(fiat, asset_names)
    if base is None or quote is None or base == quote:
        return None
    for name in sorted(pairs):
        meta = pairs[name]
        if name.endswith(DARK_POOL_SUFFIX):
            continue
        if meta.base == base and meta.quote == quote and meta.tradable:
            return meta
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_markets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/markets.py tests/unit/core/test_markets.py
git commit -m "feat(core): translate Kraken asset names and resolve an asset's pair"
```

---

### Task 6: The portfolio view

**Files:**
- Create: `core/portfolio.py`
- Test: `tests/unit/core/test_portfolio.py`

**Interfaces:**
- Consumes: `engine.valuation.value_portfolio`, `engine.types.UnpricedAsset`,
  `core.markets.split_balance_key`, `core.markets.TRADABLE_SUFFIXES`,
  `exchange.precision.format_decimal`
- Produces: `Holding`, `PortfolioView` with `.snapshot_json() -> dict[str, object]`, and
  `build_view(balances, asset_names, fiat, targets, prices) -> PortfolioView`.
  `balances` is keyed by Kraken's balance keys; `prices` and `targets` by short name.
  Raises `UnpricedAsset` when a managed asset has no price.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_portfolio.py`:

```python
from decimal import Decimal

import pytest

from core.portfolio import build_view
from engine.types import UnpricedAsset

D = Decimal
NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "SOL": "SOL"}
PRICES = {"XBT": D("50000"), "ETH": D("2500"), "SOL": D("100")}


def _view(balances, targets, prices=PRICES):
    return build_view(balances, NAMES, "EUR", targets, prices)


def _holding(view, asset):
    return next(h for h in view.holdings if h.asset == asset)


def test_an_internal_name_is_shown_under_its_short_name():
    view = _view({"XXBT": D("0.02"), "ZEUR": D("1000")}, {"XBT": D("50")})

    xbt = _holding(view, "XBT")
    assert xbt.amount == D("0.02")
    assert xbt.value == D("1000")
    assert xbt.managed is True
    assert xbt.weight_pct == D("50")


def test_a_rewards_balance_counts_as_holdings_of_its_asset():
    """Kraken trades `XBT.F` through `XBT`. Leaving it out would understate the weight."""
    view = _view({"XXBT": D("0.01"), "XBT.F": D("0.01"), "ZEUR": D("1000")}, {"XBT": D("50")})

    assert _holding(view, "XBT").amount == D("0.02")
    assert view.managed_value == D("2000")


def test_a_staked_balance_is_shown_locked_and_counts_for_nothing():
    view = _view({"ZEUR": D("100"), "DOT.S": D("5")}, {})

    dot = _holding(view, "DOT.S")
    assert dot.locked is True
    assert dot.managed is False
    assert dot.value is None
    assert view.managed_value == D("100")


def test_the_fiat_is_cash_and_not_a_holding():
    view = _view({"ZEUR": D("250.5")}, {})

    assert view.cash == D("250.5")
    assert all(h.asset != "EUR" for h in view.holdings)


def test_fiat_on_hold_is_not_spendable_cash():
    view = _view({"ZEUR": D("100"), "EUR.HOLD": D("40")}, {})

    assert view.cash == D("100")
    assert _holding(view, "EUR.HOLD").locked is True


def test_an_unmanaged_asset_is_shown_valued_but_outside_the_denominator():
    view = _view({"ZEUR": D("100"), "XETH": D("1")}, {})

    eth = _holding(view, "ETH")
    assert eth.managed is False
    assert eth.value == D("2500")
    assert eth.weight_pct is None
    assert view.managed_value == D("100")


def test_an_unmanaged_asset_with_no_price_is_shown_unvalued():
    view = _view({"ZEUR": D("100"), "XETH": D("1")}, {}, prices={})

    assert _holding(view, "ETH").value is None


def test_an_unmanaged_asset_with_nothing_left_is_not_shown():
    """Kraken keeps reporting a zero for every asset the account ever held."""
    view = _view({"ZEUR": D("100"), "XETH": D("0")}, {})

    assert all(h.asset != "ETH" for h in view.holdings)


def test_a_managed_asset_with_nothing_held_is_still_shown():
    view = _view({"ZEUR": D("100")}, {"SOL": D("10")})

    sol = _holding(view, "SOL")
    assert sol.amount == D("0")
    assert sol.weight_pct == D("0")


def test_a_managed_asset_with_no_price_raises():
    """Every weight would be wrong. The caller records nothing instead."""
    with pytest.raises(UnpricedAsset):
        _view({"ZEUR": D("100"), "XXBT": D("1")}, {"XBT": D("50")}, prices={})


def test_the_cash_target_is_what_the_weights_leave():
    view = _view({"ZEUR": D("100")}, {"XBT": D("60"), "SOL": D("35")})

    assert view.cash_target_pct == D("5")


def test_an_empty_account_has_no_value_and_no_weights():
    view = _view({}, {"XBT": D("50")})

    assert view.managed_value == D("0")
    assert _holding(view, "XBT").weight_pct == D("0")


def test_the_snapshot_holds_strings_never_floats():
    """JSON has no decimal type. A float here loses money silently."""
    view = _view({"XXBT": D("0.00000001"), "ZEUR": D("1000"), "DOT.S": D("5")}, {"XBT": D("50")})
    snapshot = view.snapshot_json()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        else:
            assert value is None or isinstance(value, (str, bool))

    walk(snapshot)
    assert snapshot["assets"]["XBT"]["amount"] == "0.00000001"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_portfolio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio'`

- [ ] **Step 3: Write the implementation**

`core/portfolio.py`:

```python
"""What the account holds, valued and weighted, as one view.

Pure: the balances, names, prices and targets arrive as arguments. The engine's own
valuation produces the weights, so this view and a reconciliation can never disagree
about what the portfolio is worth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from core.markets import TRADABLE_SUFFIXES, split_balance_key
from engine.types import HUNDRED, ZERO
from engine.valuation import value_portfolio
from exchange.precision import format_decimal

PERCENT_STEP = Decimal("0.01")


@dataclass(frozen=True)
class Holding:
    asset: str
    amount: Decimal
    price: Decimal | None
    value: Decimal | None
    managed: bool
    locked: bool
    target_pct: Decimal | None
    weight_pct: Decimal | None


@dataclass(frozen=True)
class PortfolioView:
    fiat: str
    cash: Decimal
    cash_target_pct: Decimal
    cash_weight_pct: Decimal
    # Managed assets plus cash: the denominator of every weight (spec §3.2).
    managed_value: Decimal
    holdings: tuple[Holding, ...]

    def snapshot_json(self) -> dict[str, object]:
        """The `holdings` column of a snapshot. Every number is a string."""
        return {
            "cash_target_pct": _pct(self.cash_target_pct),
            "cash_weight_pct": _pct(self.cash_weight_pct),
            "assets": {holding.asset: _holding_json(holding) for holding in self.holdings},
        }


def build_view(
    balances: Mapping[str, Decimal],
    asset_names: Mapping[str, str],
    fiat: str,
    targets: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
) -> PortfolioView:
    """Raises `UnpricedAsset` when a managed asset has no price."""
    tradable: dict[str, Decimal] = {}
    locked: dict[str, Decimal] = {}
    for key, amount in balances.items():
        name, suffix = split_balance_key(key, asset_names)
        if suffix in TRADABLE_SUFFIXES:
            tradable[name] = tradable.get(name, ZERO) + amount
        else:
            label = f"{name}.{suffix}"
            locked[label] = locked.get(label, ZERO) + amount

    cash = tradable.pop(fiat, ZERO)
    valuation = value_portfolio(tradable, prices, targets, cash)

    holdings: list[Holding] = [
        Holding(
            asset=asset,
            amount=tradable.get(asset, ZERO),
            price=prices[asset],
            value=valuation.asset_values[asset],
            managed=True,
            locked=False,
            target_pct=targets[asset],
            weight_pct=valuation.weights[asset],
        )
        for asset in sorted(targets)
    ]
    for asset in sorted(set(tradable) - set(targets)):
        amount = tradable[asset]
        if amount == ZERO:
            continue
        price = prices.get(asset)
        holdings.append(
            Holding(
                asset=asset,
                amount=amount,
                price=price,
                value=None if price is None else amount * price,
                managed=False,
                locked=False,
                target_pct=None,
                weight_pct=None,
            )
        )
    for label in sorted(locked):
        if locked[label] == ZERO:
            continue
        holdings.append(
            Holding(
                asset=label,
                amount=locked[label],
                price=None,
                value=None,
                managed=False,
                locked=True,
                target_pct=None,
                weight_pct=None,
            )
        )

    return PortfolioView(
        fiat=fiat,
        cash=cash,
        cash_target_pct=HUNDRED - sum(targets.values(), ZERO),
        cash_weight_pct=valuation.cash_weight,
        managed_value=valuation.managed_value,
        holdings=tuple(holdings),
    )


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value.quantize(PERCENT_STEP))


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _holding_json(holding: Holding) -> dict[str, object]:
    return {
        "amount": _amount(holding.amount),
        "price": _amount(holding.price),
        "value": _amount(holding.value),
        "managed": holding.managed,
        "locked": holding.locked,
        "target_pct": _pct(holding.target_pct),
        "weight_pct": _pct(holding.weight_pct),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_portfolio.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/portfolio.py tests/unit/core/test_portfolio.py
git commit -m "feat(core): build the portfolio view from Kraken's balances"
```

---

### Task 7: Google sign-in

**Files:**
- Create: `core/google.py`
- Test: `tests/unit/core/test_google.py`

**Interfaces:**
- Consumes: `core.config.GoogleConfig`, `core.tokens.LoginState`
- Produces: `new_login() -> LoginState`, `code_challenge(verifier) -> str`,
  `authorization_url(config, login) -> str`,
  `exchange_code(http: httpx.Client, config, code: str, verifier: str) -> GoogleIdentity`,
  `GoogleIdentity(subject: str, email: str)`, `GoogleLoginFailed(Exception)` whose message
  is safe to show to the person signing in.

Written against httpx directly, not an OAuth library. The flow is two requests, and
`httpx.MockTransport` tests every branch of it the same way phase 3 tested Kraken.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_google.py`:

```python
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from core.config import GoogleConfig
from core.google import (
    AUTHORIZE_URL,
    GoogleLoginFailed,
    authorization_url,
    code_challenge,
    exchange_code,
    new_login,
)

CONFIG = GoogleConfig(
    client_id="test-client",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:8000/auth/callback/google",
)


def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _google(userinfo=None, token_status=200, userinfo_status=200, seen=None):
    """Answers the token and userinfo endpoints. `seen` collects the token request form."""

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            if seen is not None:
                seen.update(parse_qs(request.content.decode()))
            return httpx.Response(token_status, json={"access_token": "google-access", "token_type": "Bearer"})
        if request.url.host == "openidconnect.googleapis.com":
            assert request.headers["Authorization"] == "Bearer google-access"
            body = userinfo or {"sub": "1234567890", "email": "alice@example.test", "email_verified": True}
            return httpx.Response(userinfo_status, json=body)
        return httpx.Response(404)

    return handler


def test_every_login_gets_its_own_state_and_verifier():
    first, second = new_login(), new_login()

    assert first.state != second.state
    assert first.verifier != second.verifier
    assert 43 <= len(first.verifier) <= 128


def test_the_challenge_is_the_s256_of_the_verifier():
    verifier = new_login().verifier
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    assert code_challenge(verifier) == expected


def test_the_authorization_url_asks_for_a_code_with_pkce():
    login = new_login()
    url = urlparse(authorization_url(CONFIG, login))
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == AUTHORIZE_URL
    assert query["client_id"] == ["test-client"]
    assert query["redirect_uri"] == [CONFIG.redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email"]
    assert query["state"] == [login.state]
    assert query["code_challenge"] == [code_challenge(login.verifier)]
    assert query["code_challenge_method"] == ["S256"]


def test_the_authorization_url_never_carries_the_client_secret():
    assert "test-client-secret" not in authorization_url(CONFIG, new_login())


def test_a_code_becomes_a_verified_identity():
    identity = exchange_code(_http(_google()), CONFIG, "the-code", "the-verifier")

    assert identity.subject == "1234567890"
    assert identity.email == "alice@example.test"


def test_the_exchange_sends_the_verifier_and_the_redirect():
    seen = {}

    exchange_code(_http(_google(seen=seen)), CONFIG, "the-code", "the-verifier")

    assert seen["code"] == ["the-code"]
    assert seen["code_verifier"] == ["the-verifier"]
    assert seen["grant_type"] == ["authorization_code"]
    assert seen["redirect_uri"] == [CONFIG.redirect_uri]


def test_a_refused_code_fails_the_login():
    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(token_status=400)), CONFIG, "used-code", "v")


def test_an_unreadable_userinfo_fails_the_login():
    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(userinfo_status=500)), CONFIG, "c", "v")


def test_an_unverified_email_fails_the_login():
    """An address nobody proved they own is not an identity to hand a portfolio to."""
    userinfo = {"sub": "1", "email": "alice@example.test", "email_verified": False}

    with pytest.raises(GoogleLoginFailed, match="verified"):
        exchange_code(_http(_google(userinfo=userinfo)), CONFIG, "c", "v")


def test_an_answer_with_no_subject_fails_the_login():
    userinfo = {"email": "alice@example.test", "email_verified": True}

    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(userinfo=userinfo)), CONFIG, "c", "v")


def test_an_unreachable_google_fails_the_login():
    def handler(request):
        raise httpx.ConnectError("connection failed")

    with pytest.raises(GoogleLoginFailed, match="reached"):
        exchange_code(_http(handler), CONFIG, "c", "v")


def test_a_failure_message_carries_no_secret():
    with pytest.raises(GoogleLoginFailed) as caught:
        exchange_code(_http(_google(token_status=400)), CONFIG, "c", "the-verifier")

    assert "test-client-secret" not in str(caught.value)
    assert "the-verifier" not in str(caught.value)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_google.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.google'`

- [ ] **Step 3: Write the implementation**

`core/google.py`:

```python
"""Sign-in with Google: the authorization code flow with PKCE.

Two requests after the redirect: the code for an access token, and the access token for
the user's identity. The identity is the `sub` claim, which Google never reassigns; the
email is kept for display only and must be verified.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from core.config import GoogleConfig
from core.tokens import LoginState

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email"


class GoogleLoginFailed(Exception):
    """The login did not produce an identity. The message is safe to show."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str


def new_login() -> LoginState:
    # 64 bytes of randomness encode to 86 characters, inside PKCE's 43 to 128.
    return LoginState(state=secrets.token_urlsafe(32), verifier=secrets.token_urlsafe(64))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(config: GoogleConfig, login: LoginState) -> str:
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": login.state,
        "code_challenge": code_challenge(login.verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def exchange_code(http: httpx.Client, config: GoogleConfig, code: str, verifier: str) -> GoogleIdentity:
    try:
        token = http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if token.status_code != 200:
            raise GoogleLoginFailed("google refused the authorization code")
        access = token.json().get("access_token")
        if not access:
            raise GoogleLoginFailed("google returned no access token")

        userinfo = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
        if userinfo.status_code != 200:
            raise GoogleLoginFailed("google did not return the account")
        body = userinfo.json()
    except httpx.HTTPError:
        raise GoogleLoginFailed("google could not be reached") from None
    except ValueError:
        raise GoogleLoginFailed("google returned something that is not JSON") from None

    subject = body.get("sub")
    email = body.get("email")
    if not subject or not email:
        raise GoogleLoginFailed("google returned no account id or email")
    if body.get("email_verified") is not True:
        raise GoogleLoginFailed("the google account has no verified email")
    return GoogleIdentity(subject=str(subject), email=str(email))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_google.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/google.py tests/unit/core/test_google.py
git commit -m "feat(core): sign in with Google using the code flow and PKCE"
```

---

### Task 8: Refresh tokens — the table, and their rotation

**Files:**
- Modify: `core/db/models.py`, `core/database.py`, `tests/integration/test_schema.py`
- Create: `core/db/refresh_tokens.py`, `core/refresh.py`,
  `scripts/migrations/versions/<rev>_refresh_tokens.py` (autogenerated)
- Test: `tests/integration/test_refresh_tokens.py`

**Interfaces:**
- Consumes: `core.tokens.new_refresh_token`, `core.tokens.hash_refresh_token`
- Produces:
  - `RefreshToken` model, table `refresh_tokens`.
  - DAL, re-exported by `core.database`: `add_refresh_token(session, user_id, family_id, token_hash, issued_at, expires_at) -> RefreshToken`,
    `get_refresh_token_for_update(session, token_hash) -> RefreshToken | None`,
    `mark_refresh_token_used(session, token, used_at) -> None`,
    `revoke_family(session, family_id, revoked_at) -> int`,
    `delete_expired_refresh_tokens(session, before) -> int`.
  - `core.refresh`: `IssuedRefresh(value, expires_at, user_id, family_id)`,
    `RefreshFailure` (`UNKNOWN`, `EXPIRED`, `REVOKED`, `REUSED`),
    `start_family(session, user_id, now, ttl) -> IssuedRefresh`,
    `rotate(session, presented, now) -> IssuedRefresh | RefreshFailure` — the new token
    inherits the family's expiry,
    `revoke(session, presented, now) -> bool`.

The spec's data model (§6) gains a ninth table. Task 13 adds it to the spec.

`rotate` **returns** a failure; it never raises one. The route that calls it runs in one
transaction, and an exception would roll back the family revocation that a reuse has just
made.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_schema.py`, add `"refresh_tokens"` to `EXPECTED_TABLES`. It
carries a `user_id`, so the second schema test covers it with no other change.

`tests/integration/test_refresh_tokens.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.db.models import RefreshToken
from core.db.refresh_tokens import delete_expired_refresh_tokens
from core.refresh import IssuedRefresh, RefreshFailure, revoke, rotate, start_family
from core.tokens import hash_refresh_token

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TTL = timedelta(days=30)
LATER = NOW + timedelta(minutes=20)


def _family(session, family_id):
    stmt = select(RefreshToken).where(RefreshToken.family_id == family_id).order_by(RefreshToken.issued_at)
    return list(session.execute(stmt).scalars())


def test_a_new_family_stores_the_hash_and_never_the_value(db_session, make_user):
    user = make_user()

    issued = start_family(db_session, user.id, NOW, TTL)

    [row] = _family(db_session, issued.family_id)
    assert row.token_hash == hash_refresh_token(issued.value)
    assert issued.value.encode() not in row.token_hash
    assert row.expires_at == NOW + TTL
    assert issued.user_id == user.id


def test_a_rotation_uses_up_the_token_and_issues_the_next_in_the_family(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    second = rotate(db_session, first.value, LATER)

    assert isinstance(second, IssuedRefresh)
    assert second.value != first.value
    assert second.family_id == first.family_id
    old, new = _family(db_session, first.family_id)
    assert old.used_at == LATER
    assert new.used_at is None
    assert new.expires_at == NOW + TTL


def test_refreshing_never_extends_the_sign_in(db_session, make_user):
    """The family's expiry is fixed at the Google login. Activity does not move it."""
    first = start_family(db_session, make_user().id, NOW, TTL)
    almost = NOW + TTL - timedelta(minutes=1)

    second = rotate(db_session, first.value, almost)

    assert second.expires_at == NOW + TTL
    assert rotate(db_session, second.value, NOW + TTL) is RefreshFailure.EXPIRED


def test_the_next_token_rotates_in_turn(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)
    second = rotate(db_session, first.value, LATER)

    assert isinstance(rotate(db_session, second.value, LATER), IssuedRefresh)


def test_a_used_token_presented_again_revokes_the_whole_family(db_session, make_user):
    """Two parties hold the family. The server cannot tell the owner from the thief."""
    first = start_family(db_session, make_user().id, NOW, TTL)
    second = rotate(db_session, first.value, LATER)

    assert rotate(db_session, first.value, LATER) is RefreshFailure.REUSED
    assert rotate(db_session, second.value, LATER) is RefreshFailure.REVOKED
    assert all(row.revoked_at == LATER for row in _family(db_session, first.family_id))


def test_a_token_nobody_issued_is_unknown(db_session):
    assert rotate(db_session, "never-issued", NOW) is RefreshFailure.UNKNOWN


def test_an_expired_token_is_refused_and_not_used_up(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    assert rotate(db_session, first.value, NOW + TTL) is RefreshFailure.EXPIRED
    assert _family(db_session, first.family_id)[0].used_at is None


def test_revoking_ends_the_family_and_says_whether_there_was_one(db_session, make_user):
    first = start_family(db_session, make_user().id, NOW, TTL)

    assert revoke(db_session, first.value, LATER) is True
    assert rotate(db_session, first.value, LATER) is RefreshFailure.REVOKED
    assert revoke(db_session, "never-issued", LATER) is False


def test_revoking_one_family_leaves_the_users_other_sign_ins(db_session, make_user):
    """Logging out on one device does not log out the others."""
    user = make_user()
    phone = start_family(db_session, user.id, NOW, TTL)
    laptop = start_family(db_session, user.id, NOW, TTL)

    revoke(db_session, phone.value, LATER)

    assert isinstance(rotate(db_session, laptop.value, LATER), IssuedRefresh)


def test_retention_deletes_only_what_has_expired(db_session, make_user):
    user = make_user()
    old = start_family(db_session, user.id, NOW - TTL - timedelta(days=1), TTL)
    fresh = start_family(db_session, user.id, NOW, TTL)

    assert delete_expired_refresh_tokens(db_session, before=NOW) == 1
    assert _family(db_session, old.family_id) == []
    assert len(_family(db_session, fresh.family_id)) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_refresh_tokens.py tests/integration/test_schema.py -v`
Expected: ERROR at collection, `ImportError: cannot import name 'RefreshToken'`

- [ ] **Step 3: Add the model**

Append to `core/db/models.py`:

```python
class RefreshToken(Base):
    """One refresh token. Only its SHA-256 is stored; the value exists only on the client.

    Tokens from one sign-in share a `family_id`. `used_at` is set when a token is rotated
    and `revoked_at` when its family ends. A token with either set is never accepted again.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    # Written from the application's clock, not `now()`, so a test can move time.
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        # Revoking a family updates every row in it.
        Index("ix_refresh_tokens_family_id", "family_id"),
        # Retention deletes across every user by date.
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )
```

The module docstring says "The eight tables"; it becomes "The nine tables".

- [ ] **Step 4: Generate the migration**

The development database must be up and at head:

```bash
docker compose -f docker-compose.dev.yml up -d
set -a; . ./.env; set +a
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. alembic revision --autogenerate -m "refresh tokens"
.venv/Scripts/python.exe -m ruff check --fix scripts/migrations/versions
.venv/Scripts/python.exe -m ruff format scripts/migrations/versions
```

Read the generated file. Its `upgrade` must hold exactly this, and `downgrade` the reverse
(both indexes dropped, then the table):

```python
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"], unique=False)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)
```

Anything else in the diff — a change to another table — means the models and the first
migration have drifted. Stop and find out why before going on.

- [ ] **Step 5: Write the DAL**

`core/db/refresh_tokens.py`:

```python
"""Refresh tokens, stored as hashes. The rules for using them live in `core/refresh.py`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from core.db.models import RefreshToken


def add_refresh_token(
    session: Session,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    token_hash: bytes,
    issued_at: datetime,
    expires_at: datetime,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    session.add(token)
    session.flush()
    return token


def get_refresh_token_for_update(session: Session, token_hash: bytes) -> RefreshToken | None:
    """The row, locked until the transaction ends.

    Two requests with the same token are serialised here: the second sees the first one's
    `used_at` and is treated as a reuse, never as a second valid rotation.
    """
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def mark_refresh_token_used(session: Session, token: RefreshToken, used_at: datetime) -> None:
    token.used_at = used_at
    session.flush()


def revoke_family(session: Session, family_id: uuid.UUID, revoked_at: datetime) -> int:
    """Revokes every live token of one sign-in. Returns how many were still live."""
    result = session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )
    session.flush()
    return result.rowcount


def delete_expired_refresh_tokens(session: Session, before: datetime) -> int:
    """Retention, across every user at once, like the `sessions` sweep. Returns how many went."""
    result = session.execute(delete(RefreshToken).where(RefreshToken.expires_at < before))
    session.flush()
    return result.rowcount
```

In `core/database.py`, import the five functions from `core.db.refresh_tokens` and add
them to `__all__`, in alphabetical order.

- [ ] **Step 6: Write the rotation**

`core/refresh.py`:

```python
"""The life of a refresh token: issued at sign-in, rotated on every use, revoked at logout.

The tokens of one sign-in form a family, and each token is good for one use. Every token
of a family expires when the first one does: a sign-in lasts a fixed time from the Google
login, and refreshing never extends it. A used token
that comes back means two parties hold the family. The server cannot tell the owner from
the thief, so it revokes the whole family, and both must sign in again.

Nothing here raises for a refused token. The caller's transaction must commit a
revocation even when the answer is no.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

import core.database as db
from core.tokens import hash_refresh_token, new_refresh_token

logger = logging.getLogger("coinpilot.auth")


class RefreshFailure(StrEnum):
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REUSED = "reused"


@dataclass(frozen=True)
class IssuedRefresh:
    value: str = field(repr=False)
    expires_at: datetime
    user_id: uuid.UUID
    family_id: uuid.UUID


def start_family(session: Session, user_id: uuid.UUID, now: datetime, ttl: timedelta) -> IssuedRefresh:
    return _issue(session, user_id, uuid.uuid4(), now, expires_at=now + ttl)


def rotate(session: Session, presented: str, now: datetime) -> IssuedRefresh | RefreshFailure:
    """Uses up the token and issues the next one of its family, with the family's expiry."""
    token = db.get_refresh_token_for_update(session, hash_refresh_token(presented))
    if token is None:
        return RefreshFailure.UNKNOWN
    if token.revoked_at is not None:
        return RefreshFailure.REVOKED
    if token.used_at is not None:
        db.revoke_family(session, token.family_id, now)
        # The user id only; never the token or its hash.
        logger.warning("a used refresh token came back for user %s; its sign-in is revoked", token.user_id)
        return RefreshFailure.REUSED
    if token.expires_at <= now:
        return RefreshFailure.EXPIRED
    db.mark_refresh_token_used(session, token, now)
    # The expiry is inherited, never recomputed: a sign-in has an absolute lifetime.
    return _issue(session, token.user_id, token.family_id, now, expires_at=token.expires_at)


def revoke(session: Session, presented: str, now: datetime) -> bool:
    """Ends the sign-in the token belongs to. False when the token is unknown."""
    token = db.get_refresh_token_for_update(session, hash_refresh_token(presented))
    if token is None:
        return False
    db.revoke_family(session, token.family_id, now)
    return True


def _issue(
    session: Session,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    now: datetime,
    expires_at: datetime,
) -> IssuedRefresh:
    value = new_refresh_token()
    db.add_refresh_token(
        session,
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_refresh_token(value),
        issued_at=now,
        expires_at=expires_at,
    )
    return IssuedRefresh(value=value, expires_at=expires_at, user_id=user_id, family_id=family_id)
```

`core/refresh.py` imports `core.database`. The layering test only forbids that inside
`core/db/`, so this is allowed and is the direction the facade exists for.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration tests/unit/core/test_layering.py -v`
Expected: PASS. The schema tests now see nine tables.

- [ ] **Step 8: Commit**

```bash
git add core/db core/database.py core/refresh.py scripts/migrations/versions tests/integration
git commit -m "feat(core): rotating refresh tokens, revoked by family on reuse"
```

---

### Task 9: The application, and signing in

**Files:**
- Create: `api/__init__.py`, `api/routes/__init__.py` (both empty), `api/context.py`,
  `api/app.py`, `api/deps.py`, `api/schemas.py`, `api/main.py`, `api/routes/health.py`,
  `api/routes/auth.py`
- Modify: `tests/integration/conftest.py`
- Test: `tests/integration/test_api_auth.py`

**Interfaces:**
- Consumes: `AppConfig`, `CredentialCipher`, `TokenSigner`, `LoginState`, `TokenInvalid`,
  `LOGIN_STATE_TTL`, `core.google.*`, `core.refresh.*`, `KrakenClient`, `KeyLimiter`,
  `core.database`
- Produces: `AppContext` with `.public_kraken() -> KrakenClient` and
  `.kraken_for(credentials) -> KrakenClient`; `create_app(context) -> FastAPI`;
  `api.deps.Db`, `api.deps.Ctx`, `api.deps.CurrentUser` (annotated dependencies);
  `api.deps.ACCESS_COOKIE = "coinpilot_token"`; the routes `GET /auth/login/{provider}`,
  `GET /auth/callback/{provider}`, `POST /auth/refresh`, `POST /auth/logout`,
  `GET /auth/me`. Test fixtures `fake_kraken`, `fake_google`, `app_context`, `api` (a
  `TestClient`) and `login(user) -> headers`.

- [ ] **Step 1: Build the integration fixtures**

Append to `tests/integration/conftest.py`. The imports go at the top of the file with the
others.

```python
import urllib.parse
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from api.app import create_app
from api.context import AppContext
from core.config import AppConfig, GoogleConfig
from core.crypto import CredentialCipher
from core.tokens import TokenSigner
from exchange.client import KRAKEN_BASE_URL
from exchange.limits import KeyLimiter

FIXED_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
REQUIRED = ["query-funds", "modify-trades", "query-open-trades", "query-closed-trades"]


def _raw_pair(altname, base, quote, status="online"):
    return {
        "altname": altname,
        "base": base,
        "quote": quote,
        "pair_decimals": 1,
        "lot_decimals": 8,
        "ordermin": "0.0001",
        "costmin": "0.5",
        "status": status,
    }


class FakeKraken:
    """Answers Kraken from attributes a test sets. Nothing reaches the network."""

    def __init__(self):
        self.permissions = list(REQUIRED)
        self.ip_allowlist = []
        self.refuse_key = False
        self.down = set()
        self.assets = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "ZUSD": "USD", "SOL": "SOL"}
        self.pairs = {
            "XXBTZEUR": _raw_pair("XBTEUR", "XXBT", "ZEUR"),
            "XETHZEUR": _raw_pair("ETHEUR", "XETH", "ZEUR"),
            "SOLEUR": _raw_pair("SOLEUR", "SOL", "ZEUR"),
        }
        self.balance = {}
        self.prices = {"XXBTZEUR": "50000", "XETHZEUR": "2500", "SOLEUR": "100"}
        self.calls = []

    def __call__(self, request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(endpoint)
        if endpoint in self.down:
            return httpx.Response(503)
        if endpoint == "GetApiKeyInfo":
            if self.refuse_key:
                return httpx.Response(200, json={"error": ["EAPI:Invalid key"], "result": {}})
            return _ok({"permissions": self.permissions, "ipAllowlist": self.ip_allowlist})
        if endpoint == "Assets":
            return _ok({name: {"altname": short} for name, short in self.assets.items()})
        if endpoint == "AssetPairs":
            return _ok(self.pairs)
        if endpoint == "Balance":
            return _ok({name: str(amount) for name, amount in self.balance.items()})
        if endpoint == "Ticker":
            wanted = request.url.params.get("pair", "").split(",")
            return _ok({pair: {"c": [self.prices[pair], "1"]} for pair in wanted if pair in self.prices})
        return httpx.Response(404)


def _ok(result):
    return httpx.Response(200, json={"error": [], "result": result})


class FakeGoogle:
    """Answers Google's token and userinfo endpoints."""

    def __init__(self):
        self.subject = "google-subject-1"
        self.email = "alice@example.test"
        self.email_verified = True
        self.refuse_code = False
        self.token_requests = []

    def __call__(self, request):
        if request.url.host == "oauth2.googleapis.com":
            self.token_requests.append(dict(urllib.parse.parse_qsl(request.content.decode())))
            if self.refuse_code:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "google-access", "token_type": "Bearer"})
        if request.url.host == "openidconnect.googleapis.com":
            return httpx.Response(
                200, json={"sub": self.subject, "email": self.email, "email_verified": self.email_verified}
            )
        return httpx.Response(404)


@pytest.fixture
def fake_kraken() -> FakeKraken:
    return FakeKraken()


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def app_context(db_session: Session, fake_kraken: FakeKraken, fake_google: FakeGoogle) -> AppContext:
    """The application's dependencies, with every provider fake and the database real."""
    config = AppConfig(
        database_url="postgresql+psycopg://unused",
        jwt_secret="t" * 32,
        jwt_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=30),
        cookie_secure=False,
        google=GoogleConfig(
            client_id="test-client",
            client_secret="test-client-secret",
            redirect_uri="http://testserver/auth/callback/google",
        ),
        credential_keys={1: bytes(range(32))},
        credential_key_version=1,
    )

    @contextmanager
    def sessions():
        # A savepoint per request, so a request that fails rolls back exactly as it
        # would in production, and the test's own transaction still discards everything.
        nested = db_session.begin_nested()
        try:
            yield db_session
        except Exception:
            nested.rollback()
            raise
        else:
            nested.commit()

    return AppContext(
        config=config,
        sessions=sessions,
        kraken_http=httpx.Client(base_url=KRAKEN_BASE_URL, transport=httpx.MockTransport(fake_kraken)),
        google_http=httpx.Client(transport=httpx.MockTransport(fake_google)),
        limiter=KeyLimiter(0.0),
        cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
        signer=TokenSigner(config.jwt_secret, config.jwt_ttl),
        now=lambda: FIXED_NOW,
    )


@pytest.fixture
def api(app_context: AppContext) -> TestClient:
    return TestClient(create_app(app_context))


@pytest.fixture
def login(app_context: AppContext) -> Callable[[User], dict[str, str]]:
    """Headers that authenticate as `user`, without going through Google."""

    def _headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {app_context.signer.issue(user.id).value}"}

    return _headers
```

- [ ] **Step 2: Write the failing tests**

`tests/integration/test_api_auth.py`:

```python
import uuid
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select

from core.db.models import RefreshToken, User
from core.db.types import UserStatus
from core.db.users import create_user, get_user_by_identity, set_user_status
from core.google import code_challenge
from core.tokens import hash_refresh_token


def _start_login(api):
    response = api.get("/auth/login/google", follow_redirects=False)
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)


def _finish_login(api, query, code="the-code"):
    return api.get("/auth/callback/google", params={"code": code, "state": query["state"][0]})


def _sign_in(api):
    response = _finish_login(api, _start_login(api))
    assert response.status_code == 200
    return response.json()


def _refresh(api, token=None):
    """With no token, the browser path: the refresh cookie alone."""
    return api.post("/auth/refresh", json=None if token is None else {"refresh_token": token})


def test_health_needs_no_login(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_login_redirects_to_google_with_pkce_and_remembers_the_state(api):
    query = _start_login(api)

    assert query["code_challenge_method"] == ["S256"]
    assert api.cookies.get("coinpilot_login")


def test_an_unknown_provider_is_not_found(api):
    assert api.get("/auth/login/github", follow_redirects=False).status_code == 404


def test_a_completed_login_creates_the_user_and_returns_both_tokens(api, db_session, fake_google, app_context):
    body = _sign_in(api)

    user = get_user_by_identity(db_session, "google", fake_google.subject)
    assert user.email == fake_google.email
    assert app_context.signer.verify(body["access_token"]) == user.id
    assert body["token_type"] == "bearer"
    assert body["refresh_expires_at"].startswith("2026-10-29T12:00:00")
    stored = db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)).scalar_one()
    assert stored.token_hash == hash_refresh_token(body["refresh_token"])
    assert api.cookies.get("coinpilot_token") == body["access_token"]
    assert api.cookies.get("coinpilot_refresh") == body["refresh_token"]


def test_the_verifier_sent_to_google_matches_the_challenge(api, fake_google):
    query = _start_login(api)
    _finish_login(api, query)

    assert code_challenge(fake_google.token_requests[0]["code_verifier"]) == query["code_challenge"][0]


def test_signing_in_twice_is_one_user(api, db_session, fake_google):
    _sign_in(api)
    _sign_in(api)

    count = db_session.execute(select(func.count()).where(User.subject == fake_google.subject)).scalar_one()
    assert count == 1


def test_a_state_that_does_not_match_is_refused(api, db_session, fake_google):
    """The state is what stops someone else's code being planted in this browser."""
    _start_login(api)

    response = api.get("/auth/callback/google", params={"code": "c", "state": "forged"})

    assert response.status_code == 400
    assert get_user_by_identity(db_session, "google", fake_google.subject) is None


def test_a_callback_with_no_login_started_is_refused(api):
    assert api.get("/auth/callback/google", params={"code": "c", "state": "s"}).status_code == 400


def test_a_login_google_did_not_grant_is_refused(api):
    _start_login(api)

    assert api.get("/auth/callback/google", params={"error": "access_denied"}).status_code == 400


def test_a_code_google_refuses_is_refused(api, fake_google):
    fake_google.refuse_code = True

    assert _finish_login(api, _start_login(api)).status_code == 400


def test_an_unverified_google_email_is_refused(api, db_session, fake_google):
    fake_google.email_verified = False

    assert _finish_login(api, _start_login(api)).status_code == 400
    assert get_user_by_identity(db_session, "google", fake_google.subject) is None


def test_a_refresh_returns_a_new_pair_for_the_same_user(api, app_context):
    signed_in = _sign_in(api)

    response = _refresh(api, signed_in["refresh_token"])

    assert response.status_code == 200
    renewed = response.json()
    assert renewed["refresh_token"] != signed_in["refresh_token"]
    assert renewed["refresh_expires_at"] == signed_in["refresh_expires_at"]
    assert app_context.signer.verify(renewed["access_token"]) == app_context.signer.verify(
        signed_in["access_token"]
    )
    assert api.cookies.get("coinpilot_refresh") == renewed["refresh_token"]


def test_the_refresh_cookie_alone_is_enough(api):
    _sign_in(api)

    assert _refresh(api).status_code == 200


def test_a_reused_refresh_token_ends_the_whole_sign_in(api):
    """The second assertion is the one that matters. It passes only if the revocation was
    committed although the request that made it was refused."""
    first = _sign_in(api)["refresh_token"]
    second = _refresh(api, first).json()["refresh_token"]

    assert _refresh(api, first).status_code == 401
    assert _refresh(api, second).status_code == 401


def test_a_refresh_token_nobody_issued_is_refused(api):
    assert _refresh(api, "never-issued").status_code == 401


def test_a_refresh_with_no_token_at_all_is_refused(api):
    assert _refresh(api).status_code == 401


def test_a_disabled_user_cannot_refresh_and_the_sign_in_is_ended(api, db_session, fake_google):
    token = _sign_in(api)["refresh_token"]
    user = get_user_by_identity(db_session, "google", fake_google.subject)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert _refresh(api, token).status_code == 403

    set_user_status(db_session, user.id, UserStatus.ACTIVE)
    assert _refresh(api, token).status_code == 401


def test_me_answers_to_a_bearer_token(api, make_user, login):
    user = make_user(email="alice@example.test")

    response = api.get("/auth/me", headers=login(user))

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.test"
    assert response.json()["id"] == str(user.id)


def test_me_answers_to_the_cookie_a_login_left(api):
    _sign_in(api)

    assert api.get("/auth/me").status_code == 200


def test_no_token_is_401(api):
    assert api.get("/auth/me").status_code == 401


def test_a_token_that_does_not_verify_is_401(api):
    assert api.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_a_token_for_a_user_that_does_not_exist_is_401(api, app_context):
    token = app_context.signer.issue(uuid.uuid4()).value

    assert api.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_disabled_user_with_a_valid_access_token_is_refused(api, db_session, make_user, login):
    """An access token cannot be revoked. This check makes disabling an account immediate."""
    user = make_user()
    headers = login(user)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert api.get("/auth/me", headers=headers).status_code == 403


def test_a_disabled_user_cannot_sign_in_again(api, db_session, fake_google):
    user = create_user(db_session, provider="google", subject=fake_google.subject, email=fake_google.email)
    set_user_status(db_session, user.id, UserStatus.DISABLED)

    assert _finish_login(api, _start_login(api)).status_code == 403


def test_logout_revokes_the_refresh_token_and_removes_both_cookies(api):
    token = _sign_in(api)["refresh_token"]

    assert api.post("/auth/logout").status_code == 204

    assert api.cookies.get("coinpilot_token") is None
    assert api.cookies.get("coinpilot_refresh") is None
    assert _refresh(api, token).status_code == 401


def test_an_application_logs_out_with_the_token_in_the_body(api):
    token = _sign_in(api)["refresh_token"]
    api.cookies.clear()

    assert api.post("/auth/logout", json={"refresh_token": token}).status_code == 204
    assert _refresh(api, token).status_code == 401


def test_an_access_token_outlives_logout_only_by_its_own_short_life(api):
    """Pinned on purpose. An access token is never looked up, so logout cannot reach it;
    its lifetime, 15 minutes by default, is the bound (spec §15)."""
    access = _sign_in(api)["access_token"]
    api.post("/auth/logout")

    assert api.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200
```

- [ ] **Step 3: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_auth.py -v`
Expected: ERROR at collection, `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 4: Write the context**

`api/context.py`:

```python
"""Everything the application needs, built once and handed to `create_app`.

The entry point builds it from the environment. A test builds it with fake transports
and a session that rolls back. Nothing under `api/` constructs a dependency of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from core.config import AppConfig
from core.crypto import CredentialCipher
from core.tokens import TokenSigner
from exchange.client import KrakenClient
from exchange.limits import KeyLimiter
from exchange.types import Credentials


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    # One unit of work per request: commits on success, rolls back on any exception.
    sessions: Callable[[], AbstractContextManager[Session]]
    kraken_http: httpx.Client
    google_http: httpx.Client
    limiter: KeyLimiter
    cipher: CredentialCipher
    signer: TokenSigner
    now: Callable[[], datetime]

    def public_kraken(self) -> KrakenClient:
        return KrakenClient(self.kraken_http, self.limiter)

    def kraken_for(self, credentials: Credentials) -> KrakenClient:
        """A client for one request. The limiter is shared, so pacing still counts per key."""
        return KrakenClient(self.kraken_http, self.limiter, credentials=credentials)
```

- [ ] **Step 5: Write the dependencies**

`api/deps.py`:

```python
"""What a route can ask for: the context, a database session, the signed-in user."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

import core.database as db
from api.context import AppContext
from core.db.models import User
from core.db.types import UserStatus
from core.tokens import TokenInvalid

ACCESS_COOKIE = "coinpilot_token"


def _context(request: Request) -> AppContext:
    return request.app.state.context


Ctx = Annotated[AppContext, Depends(_context)]


def _session(context: Ctx) -> Iterator[Session]:
    with context.sessions() as session:
        yield session


# Function scope: the transaction commits before the response is sent. With FastAPI's
# default scope it commits afterwards, and a failed commit reaches the client as a 200.
Db = Annotated[Session, Depends(_session, scope="function")]


def _token(request: Request) -> str | None:
    """The bearer header first, for an application; the cookie second, for a browser."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(ACCESS_COOKIE)


def _current_user(request: Request, session: Db, context: Ctx) -> User:
    unauthenticated = HTTPException(401, "not signed in", headers={"WWW-Authenticate": "Bearer"})
    token = _token(request)
    if token is None:
        raise unauthenticated
    try:
        user_id = context.signer.verify(token)
    except TokenInvalid:
        raise unauthenticated from None
    user = db.get_user(session, user_id)
    if user is None:
        raise unauthenticated
    # A token cannot be revoked. Reading the status on every request is what makes
    # disabling an account take effect now rather than when the token expires.
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "this account is disabled")
    return user


CurrentUser = Annotated[User, Depends(_current_user)]
```

- [ ] **Step 6: Write the schemas this task needs**

`api/schemas.py`:

```python
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
```

- [ ] **Step 7: Write the routes**

`api/routes/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only. It touches neither the database nor Kraken."""
    return {"status": "ok"}
```

`api/routes/auth.py`:

```python
"""Sign-in with Google, the refresh of a sign-in, and who the caller is.

The login state and the PKCE verifier cross Google's redirect in a signed cookie scoped
to the callback path, so no table holds half-finished logins.

A refused refresh or logout is returned, never raised. Every route runs in one
transaction, and an exception would roll back a revocation made on the way to the
refusal.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

import core.database as db
from api.context import AppContext
from api.deps import ACCESS_COOKIE, Ctx, CurrentUser, Db
from api.schemas import MeOut, RefreshIn, TokenPairOut
from core import google
from core.db.types import UserStatus
from core.refresh import IssuedRefresh, RefreshFailure, revoke, rotate, start_family
from core.tokens import LOGIN_STATE_TTL, TokenInvalid

router = APIRouter(prefix="/auth", tags=["auth"])

PROVIDER = "google"
LOGIN_COOKIE = "coinpilot_login"
LOGIN_COOKIE_PATH = "/auth/callback"
REFRESH_COOKIE = "coinpilot_refresh"
# Sent to the auth routes only. `Strict`: a request another site starts never carries it.
REFRESH_COOKIE_PATH = "/auth"
START_AGAIN = "the login expired or was not started here; start again"


def _only_google(provider: str) -> None:
    if provider != PROVIDER:
        raise HTTPException(404, "unknown provider")


def _presented_refresh(request: Request, body: RefreshIn | None) -> str | None:
    """The body first, for an application; the cookie second, for a browser."""
    if body is not None and body.refresh_token is not None:
        return body.refresh_token.get_secret_value()
    return request.cookies.get(REFRESH_COOKIE)


def _signed_in(context: AppContext, user_id: uuid.UUID, refresh: IssuedRefresh) -> JSONResponse:
    access = context.signer.issue(user_id)
    body = TokenPairOut(
        access_token=access.value,
        expires_at=access.expires_at,
        refresh_token=refresh.value,
        refresh_expires_at=refresh.expires_at,
    )
    response = JSONResponse(body.model_dump(mode="json"))
    response.set_cookie(
        ACCESS_COOKIE,
        access.value,
        max_age=int(context.config.jwt_ttl.total_seconds()),
        path="/",
        httponly=True,
        secure=context.config.cookie_secure,
        # `Lax`, not `Strict`: it must arrive on the navigation back from Google.
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh.value,
        # What is left of the sign-in, not a fresh lifetime: the expiry is absolute.
        max_age=int((refresh.expires_at - context.now()).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=context.config.cookie_secure,
        samesite="strict",
    )
    return response


def _signed_out(status_code: int, detail: str | None = None) -> Response:
    if detail is None:
        response = Response(status_code=status_code)
    else:
        response = JSONResponse({"detail": detail}, status_code=status_code)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return response


@router.get("/login/{provider}")
def login(provider: str, context: Ctx) -> RedirectResponse:
    _only_google(provider)
    started = google.new_login()
    response = RedirectResponse(google.authorization_url(context.config.google, started), status_code=302)
    response.set_cookie(
        LOGIN_COOKIE,
        context.signer.issue_login_state(started),
        max_age=int(LOGIN_STATE_TTL.total_seconds()),
        path=LOGIN_COOKIE_PATH,
        httponly=True,
        secure=context.config.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/callback/{provider}", response_model=TokenPairOut)
def callback(
    provider: str,
    request: Request,
    session: Db,
    context: Ctx,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> JSONResponse:
    _only_google(provider)
    if error:
        raise HTTPException(400, "google did not grant the login")
    cookie = request.cookies.get(LOGIN_COOKIE)
    if not cookie or not code or not state:
        raise HTTPException(400, START_AGAIN)
    try:
        expected = context.signer.verify_login_state(cookie)
    except TokenInvalid:
        raise HTTPException(400, START_AGAIN) from None
    if not secrets.compare_digest(expected.state, state):
        raise HTTPException(400, "the login state does not match; start again")

    try:
        identity = google.exchange_code(context.google_http, context.config.google, code, expected.verifier)
    except google.GoogleLoginFailed as exc:
        raise HTTPException(400, str(exc)) from None

    user = db.get_user_by_identity(session, PROVIDER, identity.subject)
    if user is None:
        user = db.create_user(session, PROVIDER, identity.subject, identity.email)
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "this account is disabled")

    refresh = start_family(session, user.id, context.now(), context.config.refresh_ttl)
    response = _signed_in(context, user.id, refresh)
    response.delete_cookie(LOGIN_COOKIE, path=LOGIN_COOKIE_PATH)
    return response


@router.post("/refresh", response_model=TokenPairOut)
def refresh(request: Request, session: Db, context: Ctx, body: RefreshIn | None = None) -> Response:
    """Trades a refresh token for a new pair. The token presented is used up."""
    presented = _presented_refresh(request, body)
    if presented is None:
        return _signed_out(401, "no refresh token")

    now = context.now()
    outcome = rotate(session, presented, now)
    if isinstance(outcome, RefreshFailure):
        return _signed_out(401, f"the refresh token is {outcome.value}; sign in again")

    user = db.get_user(session, outcome.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        db.revoke_family(session, outcome.family_id, now)
        return _signed_out(403, "this account is disabled")
    return _signed_in(context, user.id, outcome)


@router.post("/logout", status_code=204)
def logout(request: Request, session: Db, context: Ctx, body: RefreshIn | None = None) -> Response:
    """Ends this sign-in: its refresh tokens are revoked and both cookies removed.

    An access token already issued keeps working until it expires, at most
    `JWT_TTL_MINUTES` later. That is the trade of every stateless access token (spec §15).
    """
    presented = _presented_refresh(request, body)
    if presented is not None:
        revoke(session, presented, context.now())
    return _signed_out(204)


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return MeOut.model_validate(user)
```

- [ ] **Step 8: Assemble the application and its entry point**

`api/app.py`:

```python
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
```

`api/main.py`:

```python
"""The process entry point: `uvicorn --factory api.main:build`.

The only place that reads the environment for the web process. Nothing imports this
module, and no test runs it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from api.app import create_app
from api.context import AppContext
from core.config import load_config
from core.crypto import CredentialCipher
from core.db.session import configure, session_scope
from core.tokens import TokenSigner
from exchange.client import build_http_client
from exchange.limits import KeyLimiter

# Kraken's private counter allows more; one call a second per key is what phase 3 tested.
KRAKEN_MIN_INTERVAL_SECONDS = 1.0


def build() -> FastAPI:
    config = load_config(os.environ)
    configure(config.database_url)
    context = AppContext(
        config=config,
        sessions=session_scope,
        kraken_http=build_http_client(),
        google_http=httpx.Client(timeout=10.0),
        limiter=KeyLimiter(KRAKEN_MIN_INTERVAL_SECONDS),
        cipher=CredentialCipher(config.credential_keys, config.credential_key_version),
        signer=TokenSigner(config.jwt_secret, config.jwt_ttl),
        now=lambda: datetime.now(UTC),
    )
    return create_app(context)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_auth.py -v`
Expected: PASS, 27 tests.

- [ ] **Step 10: Commit**

```bash
git add api tests/integration/conftest.py tests/integration/test_api_auth.py
git commit -m "feat(api): sign in with Google, short-lived JWTs and rotating refresh tokens"
```

---

### Task 10: Registering a Kraken key

**Files:**
- Create: `api/routes/credentials.py`
- Modify: `api/app.py`, `api/schemas.py`
- Test: `tests/integration/test_api_credentials.py`

**Interfaces:**
- Consumes: `validate_key`, `KeyRejection`, `Credentials`, `CredentialCipher.seal`,
  `db.save_credentials`, `db.get_credentials`, `db.delete_credentials`
- Produces: `POST /credentials` (201, 422, 503), `DELETE /credentials` (204, 404),
  `GET /credentials/status`; the application-wide validation-error handler.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_api_credentials.py`:

```python
import base64
import logging

from api.app import create_app
from core.crypto import Sealed
from core.db.users import get_credentials
from exchange.types import Credentials

# Built at run time, so no literal that looks like a secret sits in the repository.
KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()
OTHER_SECRET = base64.b64encode(b"alice-second-secret").decode()


def _register(api, headers, key=KEY, secret=SECRET):
    return api.post("/credentials", json={"api_key": key, "api_secret": secret}, headers=headers)


def test_an_accepted_key_is_stored_encrypted(api, db_session, make_user, login, app_context):
    user = make_user()

    response = _register(api, login(user))

    assert response.status_code == 201
    record = get_credentials(db_session, user.id)
    assert SECRET.encode() not in record.ciphertext
    assert KEY.encode() not in record.ciphertext
    sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
    assert app_context.cipher.unseal(user.id, sealed) == Credentials(KEY, SECRET)


def test_the_answer_carries_the_permissions_and_never_the_key(api, make_user, login, fake_kraken):
    fake_kraken.ip_allowlist = ["203.0.113.7"]

    response = _register(api, login(make_user()))

    assert response.json()["ip_allowlist"] == ["203.0.113.7"]
    assert "query-funds" in response.json()["permissions"]
    assert KEY not in response.text
    assert SECRET not in response.text


def test_a_key_that_can_withdraw_is_refused_and_not_stored(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.permissions.append("withdraw-funds")

    response = _register(api, login(user))

    assert response.status_code == 422
    assert response.json()["detail"]["rejection"] == "forbidden_permissions"
    assert response.json()["detail"]["forbidden"] == ["withdraw-funds"]
    assert get_credentials(db_session, user.id) is None


def test_a_key_missing_a_permission_is_refused_and_says_which(api, make_user, login, fake_kraken):
    fake_kraken.permissions.remove("query-closed-trades")

    response = _register(api, login(make_user()))

    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == ["query-closed-trades"]


def test_a_key_kraken_refuses_is_invalid(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.refuse_key = True

    response = _register(api, login(user))

    assert response.status_code == 422
    assert response.json()["detail"]["rejection"] == "invalid_key"
    assert get_credentials(db_session, user.id) is None


def test_an_unreachable_kraken_stores_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    fake_kraken.down.add("GetApiKeyInfo")

    response = _register(api, login(user))

    assert response.status_code == 503
    assert get_credentials(db_session, user.id) is None


def test_a_refused_replacement_leaves_the_working_key_in_place(
    api, db_session, make_user, login, fake_kraken, app_context
):
    user = make_user()
    headers = login(user)
    _register(api, headers)
    fake_kraken.permissions.append("withdraw-funds")

    assert _register(api, headers, secret=OTHER_SECRET).status_code == 422

    record = get_credentials(db_session, user.id)
    sealed = Sealed(record.ciphertext, record.nonce, record.key_version)
    assert app_context.cipher.unseal(user.id, sealed).api_secret == SECRET


def test_the_status_says_whether_a_key_is_registered(api, make_user, login):
    headers = login(make_user())

    assert api.get("/credentials/status", headers=headers).json()["registered"] is False
    _register(api, headers)
    status = api.get("/credentials/status", headers=headers).json()
    assert status["registered"] is True
    assert status["key_version"] == 1
    assert status["validated_at"].startswith("2026-09-29T12:00:00")


def test_a_key_can_be_deleted_once(api, make_user, login):
    headers = login(make_user())
    _register(api, headers)

    assert api.delete("/credentials", headers=headers).status_code == 204
    assert api.delete("/credentials", headers=headers).status_code == 404
    assert api.get("/credentials/status", headers=headers).json()["registered"] is False


def test_registering_needs_a_signed_in_user(api):
    assert _register(api, {}).status_code == 401


def test_a_malformed_body_is_refused_without_echoing_it(api, make_user, login):
    """FastAPI's default 422 carries the rejected input. Here that input is a credential."""
    headers = login(make_user())

    missing_secret = api.post("/credentials", json={"api_key": KEY}, headers=headers)
    too_long = api.post("/credentials", json={"api_key": KEY, "api_secret": "x" * 600}, headers=headers)

    assert missing_secret.status_code == 422
    assert KEY not in missing_secret.text
    assert too_long.status_code == 422
    assert "x" * 600 not in too_long.text
    assert KEY not in too_long.text


def test_no_log_line_carries_the_key_or_the_secret(api, make_user, login, fake_kraken, caplog):
    headers = login(make_user())

    with caplog.at_level(logging.DEBUG):
        _register(api, headers)
        fake_kraken.refuse_key = True
        _register(api, headers)

    assert KEY not in caplog.text
    assert SECRET not in caplog.text


def test_no_response_model_has_a_field_for_a_credential(app_context):
    for route in create_app(app_context).routes:
        model = getattr(route, "response_model", None)
        fields = getattr(model, "model_fields", {})
        assert not any("secret" in name or name == "api_key" for name in fields), route.path
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_credentials.py -v`
Expected: FAIL, `/credentials` answers 404.

- [ ] **Step 3: Add the schemas**

Append to `api/schemas.py`. The `pydantic` import becomes
`from pydantic import BaseModel, ConfigDict, Field, SecretStr`:

```python
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
```

- [ ] **Step 4: Write the routes**

`api/routes/credentials.py`:

```python
"""A user's Kraken key: validated on write (spec §5.2), sealed at rest (§5.3), never read back."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import CredentialsIn, CredentialStatusOut, KeyAcceptedOut
from exchange.keys import validate_key
from exchange.types import Credentials, KeyRejection

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post("", status_code=201, response_model=KeyAcceptedOut)
def register(body: CredentialsIn, user: CurrentUser, session: Db, context: Ctx) -> KeyAcceptedOut:
    credentials = Credentials(
        api_key=body.api_key.get_secret_value(),
        api_secret=body.api_secret.get_secret_value(),
    )
    result = validate_key(context.kraken_for(credentials))
    if result.rejection is KeyRejection.UNREACHABLE:
        raise HTTPException(503, "kraken could not be reached; the key was not stored")
    if not result.accepted:
        raise HTTPException(
            422,
            {
                "rejection": result.rejection.value,
                "missing": list(result.missing),
                "forbidden": list(result.forbidden),
            },
        )

    sealed = context.cipher.seal(user.id, credentials)
    validated_at = context.now()
    db.save_credentials(session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, validated_at)
    return KeyAcceptedOut(
        validated_at=validated_at,
        permissions=list(result.permissions),
        ip_allowlist=list(result.ip_allowlist),
    )


@router.delete("", status_code=204)
def remove(user: CurrentUser, session: Db) -> Response:
    if not db.delete_credentials(session, user.id):
        raise HTTPException(404, "no key is registered")
    return Response(status_code=204)


@router.get("/status", response_model=CredentialStatusOut)
def status(user: CurrentUser, session: Db) -> CredentialStatusOut:
    record = db.get_credentials(session, user.id)
    if record is None:
        return CredentialStatusOut(registered=False)
    return CredentialStatusOut(registered=True, validated_at=record.validated_at, key_version=record.key_version)
```

- [ ] **Step 5: Register the router and stop validation errors echoing input**

`api/app.py` becomes:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_credentials.py tests/integration/test_api_auth.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api tests/integration/test_api_credentials.py
git commit -m "feat(api): register a Kraken key only after it passes the permission contract"
```

---

### Task 11: Settings and target weights

**Files:**
- Create: `api/routes/config.py`, `api/routes/assets.py`
- Modify: `core/db/settings.py`, `core/database.py`, `api/app.py`, `api/schemas.py`
- Test: `tests/integration/test_settings.py`, `tests/integration/test_api_config.py`,
  `tests/integration/test_api_assets.py`

**Interfaces:**
- Consumes: `core.markets.short_name`, `resolve_pair`, `SUPPORTED_FIATS`,
  `KrakenClient.assets`, `KrakenClient.asset_pairs`
- Produces: `db.lock_settings(session, user_id) -> UserSettings | None`;
  `GET /config`, `PATCH /config`, `GET /assets`, `PUT /assets/{asset}`,
  `DELETE /assets/{asset}`.

The rule that the weights sum to 100 or less lives here, in the application layer (§3.1).
Two concurrent `PUT /assets` could each pass the check on their own and exceed 100
together, so both lock the user's settings row first and the second waits for the first.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_settings.py`, add `lock_settings` (and `create_settings`, if it
is not there yet) to the import from `core.db.settings` at the top. Append:

```python
def test_locking_settings_returns_the_row(db_session, make_user):
    user = make_user()
    create_settings(db_session, user.id, fiat="EUR")

    assert lock_settings(db_session, user.id).fiat == "EUR"


def test_locking_settings_that_do_not_exist_is_none(db_session, make_user):
    assert lock_settings(db_session, make_user().id) is None
```

`tests/integration/test_api_config.py`:

```python
from decimal import Decimal

from core.db.settings import get_settings


def test_there_are_no_settings_until_the_first_patch(api, make_user, login):
    assert api.get("/config", headers=login(make_user())).status_code == 404


def test_the_first_patch_must_choose_the_fiat(api, make_user, login):
    assert api.patch("/config", json={"paused": True}, headers=login(make_user())).status_code == 409


def test_the_first_patch_creates_the_settings_with_their_defaults(api, make_user, login):
    response = api.patch("/config", json={"fiat": "eur"}, headers=login(make_user()))

    assert response.status_code == 200
    body = response.json()
    assert body["fiat"] == "EUR"
    assert body["invest_cash_enabled"] is True
    assert body["invest_cadence_mode"] == "MIN"
    assert Decimal(body["min_order_fiat"]) == 0


def test_a_fiat_this_system_does_not_support_is_refused(api, make_user, login):
    assert api.patch("/config", json={"fiat": "BTC"}, headers=login(make_user())).status_code == 422


def test_the_fiat_cannot_change_once_chosen(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"fiat": "USD"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"fiat": "EUR", "paused": True}, headers=headers).status_code == 200


def test_amounts_come_back_as_strings(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    body = api.patch("/config", json={"min_drift_pct": "5.5", "min_order_fiat": "10"}, headers=headers).json()

    assert isinstance(body["min_drift_pct"], str)
    assert Decimal(body["min_drift_pct"]) == Decimal("5.5")
    assert Decimal(body["min_order_fiat"]) == Decimal("10")


def test_a_drift_threshold_the_column_cannot_hold_is_refused(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"min_drift_pct": "5.55"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"min_drift_pct": "101"}, headers=headers).status_code == 422
    assert api.patch("/config", json={"min_order_fiat": "-1"}, headers=headers).status_code == 422


def test_an_interval_cadence_needs_a_length_and_an_anchor(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    no_anchor = api.patch("/config", json={"invest_cadence_mode": "INTERVAL", "invest_interval_months": 1}, headers=headers)
    no_length = api.patch(
        "/config",
        json={"invest_cadence_mode": "INTERVAL", "invest_cadence_anchor": "2026-10-01T09:00:00+00:00"},
        headers=headers,
    )

    assert no_anchor.status_code == 422
    assert no_length.status_code == 422
    assert get_settings(db_session, user.id).invest_cadence_mode == "MIN"


def test_a_complete_interval_cadence_is_accepted(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch(
        "/config",
        json={
            "rebalance_cadence_mode": "INTERVAL",
            "rebalance_interval_months": 3,
            "rebalance_cadence_anchor": "2026-01-15T09:00:00+00:00",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["rebalance_interval_months"] == 3


def test_an_anchor_without_a_timezone_is_refused(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch("/config", json={"invest_cadence_anchor": "2026-10-01T09:00:00"}, headers=headers)

    assert response.status_code == 422


def test_a_required_setting_cannot_be_set_to_null(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.patch("/config", json={"paused": None}, headers=headers).status_code == 422


def test_the_times_the_scheduler_owns_cannot_be_patched(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    response = api.patch("/config", json={"next_invest_at": "2026-10-01T09:00:00+00:00"}, headers=headers)

    assert response.status_code == 422
```

`tests/integration/test_api_assets.py`:

```python
from decimal import Decimal

from core.db.settings import list_assets


def _with_fiat(api, headers, fiat="EUR"):
    api.patch("/config", json={"fiat": fiat}, headers=headers)


def test_a_weight_needs_a_fiat_first(api, make_user, login):
    assert api.put("/assets/XBT", json={"target_pct": "60"}, headers=login(make_user())).status_code == 409


def test_an_asset_is_stored_with_its_resolved_pair(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)

    response = api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["asset"] == "XBT"
    assert response.json()["pair"] == "XXBTZEUR"
    assert Decimal(response.json()["target_pct"]) == Decimal("60")
    assert [row.asset for row in list_assets(db_session, user.id)] == ["XBT"]


def test_the_internal_name_and_lower_case_both_mean_the_same_asset(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)

    api.put("/assets/xxbt", json={"target_pct": "30"}, headers=headers)
    api.put("/assets/xbt", json={"target_pct": "40"}, headers=headers)

    rows = list_assets(db_session, user.id)
    assert [(row.asset, row.target_pct) for row in rows] == [("XBT", Decimal("40"))]


def test_an_asset_kraken_does_not_list_is_refused(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/BTC", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_the_fiat_cannot_also_be_an_asset(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/EUR", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_weights_above_one_hundred_in_total_are_refused(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    response = api.put("/assets/ETH", json={"target_pct": "40.01"}, headers=headers)

    assert response.status_code == 422
    assert [row.asset for row in list_assets(db_session, user.id)] == ["XBT"]


def test_changing_one_weight_does_not_count_it_twice(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert api.put("/assets/XBT", json={"target_pct": "100"}, headers=headers).status_code == 200


def test_a_weight_of_zero_is_accepted_because_it_means_exit(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/SOL", json={"target_pct": "0"}, headers=headers).status_code == 200


def test_an_asset_with_no_pair_against_the_fiat_is_refused_now(api, make_user, login):
    """Refused at configuration time, not discovered at order time (spec §3.1)."""
    headers = login(make_user())
    _with_fiat(api, headers, fiat="USD")

    assert api.put("/assets/SOL", json={"target_pct": "10"}, headers=headers).status_code == 422


def test_an_unreachable_kraken_stores_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _with_fiat(api, headers)
    fake_kraken.down.add("Assets")

    assert api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers).status_code == 503
    assert list_assets(db_session, user.id) == []


def test_a_weight_with_three_decimals_is_refused(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)

    assert api.put("/assets/XBT", json={"target_pct": "10.005"}, headers=headers).status_code == 422


def test_the_list_carries_the_cash_target(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.put("/assets/SOL", json={"target_pct": "35"}, headers=headers)

    body = api.get("/assets", headers=headers).json()

    assert [row["asset"] for row in body["assets"]] == ["SOL", "XBT"]
    assert Decimal(body["cash_target_pct"]) == Decimal("5")


def test_an_asset_can_be_removed_once(api, make_user, login):
    headers = login(make_user())
    _with_fiat(api, headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)

    assert api.delete("/assets/xbt", headers=headers).status_code == 204
    assert api.delete("/assets/XBT", headers=headers).status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_settings.py tests/integration/test_api_config.py tests/integration/test_api_assets.py -v`
Expected: FAIL with `ImportError: cannot import name 'lock_settings'`

- [ ] **Step 3: Add the lock**

Append to `core/db/settings.py`:

```python
def lock_settings(session: Session, user_id: uuid.UUID) -> UserSettings | None:
    """The settings row, locked until the transaction ends.

    Taken before a change that is checked against the user's other rows, such as the
    weights summing to 100 or less. A second request for the same user waits instead of
    passing the same check at the same time.
    """
    return session.get(UserSettings, user_id, with_for_update=True, populate_existing=True)
```

In `core/database.py`, add `lock_settings` to the import from `core.db.settings` and to
`__all__`, in alphabetical order.

- [ ] **Step 4: Add the schemas**

The import block at the top of `api/schemas.py` becomes:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator

from core.db.types import CadenceMode
```

Append:

```python
# Nullable columns may be cleared with an explicit null. These may not.
_NOT_NULL = (
    "invest_cash_enabled",
    "cash_rebalance_enabled",
    "auto_rebalance_enabled",
    "paused",
    "min_drift_pct",
    "min_order_fiat",
    "invest_cadence_mode",
    "rebalance_cadence_mode",
)


class ConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fiat: str
    invest_cash_enabled: bool
    cash_rebalance_enabled: bool
    auto_rebalance_enabled: bool
    min_drift_pct: Decimal
    min_order_fiat: Decimal
    invest_cadence_mode: CadenceMode
    invest_interval_days: int | None
    invest_interval_months: int | None
    invest_cadence_anchor: datetime | None
    rebalance_cadence_mode: CadenceMode
    rebalance_interval_days: int | None
    rebalance_interval_months: int | None
    rebalance_cadence_anchor: datetime | None
    next_invest_at: datetime | None
    next_rebalance_at: datetime | None
    paused: bool


class ConfigPatch(BaseModel):
    """Every field optional. `next_invest_at` and `next_rebalance_at` are absent on purpose:
    the scheduler owns them, and `extra="forbid"` turns an attempt into a 422."""

    model_config = ConfigDict(extra="forbid")

    fiat: str | None = None
    invest_cash_enabled: bool | None = None
    cash_rebalance_enabled: bool | None = None
    auto_rebalance_enabled: bool | None = None
    paused: bool | None = None
    # Numeric(4,1) and Numeric(10,1): the bounds are the columns'.
    min_drift_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=1)
    min_order_fiat: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999.9"), decimal_places=1)
    invest_cadence_mode: CadenceMode | None = None
    invest_interval_days: int | None = Field(default=None, ge=0, le=3650)
    invest_interval_months: int | None = Field(default=None, ge=0, le=120)
    invest_cadence_anchor: AwareDatetime | None = None
    rebalance_cadence_mode: CadenceMode | None = None
    rebalance_interval_days: int | None = Field(default=None, ge=0, le=3650)
    rebalance_interval_months: int | None = Field(default=None, ge=0, le=120)
    rebalance_cadence_anchor: AwareDatetime | None = None

    @model_validator(mode="after")
    def _no_null_for_required(self) -> ConfigPatch:
        cleared = [name for name in _NOT_NULL if name in self.model_fields_set and getattr(self, name) is None]
        if cleared:
            raise ValueError(f"these settings cannot be null: {', '.join(cleared)}")
        return self


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_pct: Decimal = Field(ge=0, le=100, decimal_places=2)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset: str
    pair: str
    target_pct: Decimal


class AssetsOut(BaseModel):
    assets: list[AssetOut]
    cash_target_pct: Decimal
```

The tests compare amounts as `Decimal`, never as strings. `Decimal("60")` and the column's
`Decimal("60.00")` are the same amount and print differently, depending on whether the
row was reloaded.

- [ ] **Step 5: Write the settings routes**

`api/routes/config.py`:

```python
"""A user's settings. The first PATCH creates them and chooses the fiat, which then never changes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import core.database as db
from api.deps import CurrentUser, Db
from api.schemas import ConfigOut, ConfigPatch
from core.db.models import UserSettings
from core.db.types import CadenceMode
from core.markets import SUPPORTED_FIATS

router = APIRouter(prefix="/config", tags=["config"])

_CADENCES = ("invest", "rebalance")


def _cadence_problem(prefix: str, merged: dict[str, object]) -> str | None:
    """An INTERVAL cadence needs a length and an anchor. MIN ignores both."""
    if merged[f"{prefix}_cadence_mode"] != CadenceMode.INTERVAL:
        return None
    days = merged[f"{prefix}_interval_days"] or 0
    months = merged[f"{prefix}_interval_months"] or 0
    if days + months == 0:
        return f"an INTERVAL {prefix} cadence needs interval_days or interval_months"
    if merged[f"{prefix}_cadence_anchor"] is None:
        return f"an INTERVAL {prefix} cadence needs a cadence_anchor"
    return None


def _merged(settings: UserSettings, changes: dict[str, object]) -> dict[str, object]:
    fields = [
        f"{prefix}_{name}"
        for prefix in _CADENCES
        for name in ("cadence_mode", "interval_days", "interval_months", "cadence_anchor")
    ]
    return {name: getattr(settings, name) for name in fields} | changes


@router.get("", response_model=ConfigOut)
def read_config(user: CurrentUser, session: Db) -> UserSettings:
    settings = db.get_settings(session, user.id)
    if settings is None:
        raise HTTPException(404, "no settings yet; PATCH /config with a fiat to create them")
    return settings


@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch, user: CurrentUser, session: Db) -> UserSettings:
    changes = body.model_dump(exclude_unset=True)
    fiat = changes.pop("fiat", None)
    fiat = fiat.strip().upper() if isinstance(fiat, str) else None

    settings = db.lock_settings(session, user.id)
    if settings is None:
        if fiat is None:
            raise HTTPException(409, "the first PATCH /config must choose a fiat")
        if fiat not in SUPPORTED_FIATS:
            raise HTTPException(422, f"supported fiats are {', '.join(SUPPORTED_FIATS)}")
        settings = db.create_settings(session, user.id, fiat=fiat)
    elif fiat is not None and fiat != settings.fiat:
        raise HTTPException(422, "the fiat cannot be changed")

    merged = _merged(settings, changes)
    for prefix in _CADENCES:
        problem = _cadence_problem(prefix, merged)
        if problem is not None:
            raise HTTPException(422, problem)

    if changes:
        settings = db.update_settings(session, user.id, **changes)
    return settings
```

A 422 raised after `create_settings` still leaves no row: the exception rolls the request
back.

- [ ] **Step 6: Write the weights routes**

`api/routes/assets.py`:

```python
"""Target weights. An asset is refused here if Kraken cannot trade it against the fiat (§3.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import AssetIn, AssetOut, AssetsOut
from core.db.models import AssetConfig
from core.markets import resolve_pair, short_name
from engine.types import HUNDRED, ZERO

router = APIRouter(prefix="/assets", tags=["assets"])

KRAKEN_DOWN = "kraken could not be reached; nothing was changed"


@router.get("", response_model=AssetsOut)
def list_assets(user: CurrentUser, session: Db) -> AssetsOut:
    rows = db.list_assets(session, user.id)
    return AssetsOut(
        assets=[AssetOut.model_validate(row) for row in rows],
        cash_target_pct=HUNDRED - sum((row.target_pct for row in rows), ZERO),
    )


@router.put("/{asset}", response_model=AssetOut)
def put_asset(asset: str, body: AssetIn, user: CurrentUser, session: Db, context: Ctx) -> AssetConfig:
    settings = db.lock_settings(session, user.id)
    if settings is None:
        raise HTTPException(409, "choose a fiat with PATCH /config first")

    kraken = context.public_kraken()
    names = kraken.assets()
    if names is None:
        raise HTTPException(503, KRAKEN_DOWN)
    code = short_name(asset, names)
    if code is None:
        raise HTTPException(422, f"kraken lists no asset called {asset!r}")
    if code == settings.fiat:
        raise HTTPException(422, "the fiat is the cash target; it cannot also be an asset")

    others = sum((row.target_pct for row in db.list_assets(session, user.id) if row.asset != code), ZERO)
    if others + body.target_pct > HUNDRED:
        raise HTTPException(422, f"the weights would sum to {others + body.target_pct}; the limit is 100")

    pairs = kraken.asset_pairs()
    if pairs is None:
        raise HTTPException(503, KRAKEN_DOWN)
    meta = resolve_pair(code, settings.fiat, names, pairs)
    if meta is None:
        raise HTTPException(422, f"kraken has no tradable {code}/{settings.fiat} pair")

    return db.upsert_asset(session, user.id, asset=code, pair=meta.pair, target_pct=body.target_pct)


@router.delete("/{asset}", status_code=204)
def delete_asset(asset: str, user: CurrentUser, session: Db) -> Response:
    # Stored names are short and upper case, so this needs no call to Kraken.
    if not db.delete_asset(session, user.id, asset.strip().upper()):
        raise HTTPException(404, "that asset has no weight")
    return Response(status_code=204)
```

`test_the_internal_name_and_lower_case_both_mean_the_same_asset` deletes by short name
only: `DELETE /assets/XXBT` answers 404. That is deliberate — the path names what is
stored, and resolving it would cost a Kraken call on a delete.

- [ ] **Step 7: Register the routers**

In `api/app.py`, the import becomes
`from api.routes import assets, auth, config, credentials, health` and the loop:

```python
    for router in (health.router, auth.router, credentials.router, config.router, assets.router):
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add core/db/settings.py core/database.py api tests/integration
git commit -m "feat(api): settings and target weights, with the pair resolved at configuration time"
```

---

### Task 12: Reading the portfolio, and the history

**Files:**
- Create: `core/reading.py`, `api/routes/portfolio.py`, `api/routes/history.py`
- Modify: `api/app.py`, `api/schemas.py`, `tests/unit/core/test_layering.py`
- Test: `tests/unit/core/test_reading.py`, `tests/integration/test_api_portfolio.py`

**Interfaces:**
- Consumes: `build_view`, `resolve_pair`, `split_balance_key`, `TRADABLE_SUFFIXES`,
  `UnpricedAsset`, `CredentialCipher.unseal`, `Sealed`, `CredentialsUnreadable`,
  `db.record_snapshot`, `db.latest_snapshot`, `db.list_orders`, `db.list_evaluations`
- Produces: `read_portfolio(public, private, fiat, assets) -> PortfolioView` and
  `PortfolioUnavailable(Exception)`; `GET /portfolio`, `POST /portfolio/refresh`,
  `GET /orders`, `GET /sessions`. The scheduler in phase 7 calls `read_portfolio` too.

A refresh makes four Kraken calls: three public (`Assets`, `AssetPairs` only when
something unmanaged is held, `Ticker`) and one private (`Balance`). Any one of them
missing means no snapshot at all, never a partial one.

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/core/test_reading.py`:

```python
from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.reading import PortfolioUnavailable, read_portfolio
from exchange.types import PairMeta

D = Decimal
NAMES = {"XXBT": "XBT", "XETH": "ETH", "ZEUR": "EUR", "SOL": "SOL"}


def _pair(name, base, quote):
    return PairMeta(name, name, base, quote, 1, 8, D("0.0001"), D("0.5"), "online")


@dataclass
class Configured:
    asset: str
    pair: str
    target_pct: Decimal


class FakePublic:
    def __init__(self, names=NAMES, pairs=None, prices=None):
        self.names = names
        self.pairs = pairs if pairs is not None else {"XETHZEUR": _pair("XETHZEUR", "XETH", "ZEUR")}
        self.prices = prices if prices is not None else {"XXBTZEUR": D("50000"), "XETHZEUR": D("2500")}
        self.calls = []

    def assets(self):
        self.calls.append("assets")
        return self.names

    def asset_pairs(self):
        self.calls.append("asset_pairs")
        return self.pairs

    def ticker(self, pairs):
        self.calls.append(("ticker", tuple(pairs)))
        return None if self.prices is None else {p: self.prices[p] for p in pairs if p in self.prices}


class FakePrivate:
    def __init__(self, balance):
        self._balance = balance

    def balance(self):
        return self._balance


XBT_60 = [Configured("XBT", "XXBTZEUR", D("60"))]


def test_a_portfolio_is_read_and_valued():
    view = read_portfolio(FakePublic(), FakePrivate({"XXBT": D("0.02"), "ZEUR": D("1000")}), "EUR", XBT_60)

    assert view.managed_value == D("2000")
    assert view.cash == D("1000")


def test_a_managed_asset_is_priced_through_its_stored_pair():
    public = FakePublic()

    read_portfolio(public, FakePrivate({"ZEUR": D("1")}), "EUR", XBT_60)

    assert ("ticker", ("XXBTZEUR",)) in public.calls


def test_pairs_are_only_read_when_something_unmanaged_is_held():
    public = FakePublic()

    read_portfolio(public, FakePrivate({"XXBT": D("1"), "ZEUR": D("1")}), "EUR", XBT_60)

    assert "asset_pairs" not in public.calls


def test_an_unmanaged_asset_is_priced_when_it_has_a_pair_to_the_fiat():
    view = read_portfolio(FakePublic(), FakePrivate({"XETH": D("2"), "ZEUR": D("1")}), "EUR", [])

    eth = next(h for h in view.holdings if h.asset == "ETH")
    assert eth.value == D("5000")


def test_an_unmanaged_asset_with_no_pair_is_shown_unvalued_and_does_not_fail():
    view = read_portfolio(FakePublic(), FakePrivate({"SOL": D("3"), "ZEUR": D("1")}), "EUR", [])

    sol = next(h for h in view.holdings if h.asset == "SOL")
    assert sol.value is None


@pytest.mark.parametrize(
    ("public", "private", "what"),
    [
        (FakePublic(names=None), FakePrivate({}), "asset names"),
        (FakePublic(), FakePrivate(None), "balance"),
        (FakePublic(prices=None), FakePrivate({"ZEUR": D("1")}), "prices"),
        (FakePublic(pairs=None), FakePrivate({"XETH": D("1")}), "asset pairs"),
    ],
)
def test_any_read_that_fails_fails_the_whole_view(public, private, what):
    targets = XBT_60 if what != "asset pairs" else []

    with pytest.raises(PortfolioUnavailable, match=what):
        read_portfolio(public, private, "EUR", targets)


def test_a_managed_asset_with_no_price_fails_the_view_and_names_it():
    public = FakePublic(prices={})

    with pytest.raises(PortfolioUnavailable, match="XBT"):
        read_portfolio(public, FakePrivate({"XXBT": D("1"), "ZEUR": D("1")}), "EUR", XBT_60)
```

Append to `tests/unit/core/test_layering.py`:

```python
ROOT = Path(__file__).resolve().parents[3]


def test_nothing_outside_the_exchange_layer_places_an_order_yet():
    """Phase 4 reads a real account and must have no way to spend from it.

    Phase 5 removes this test on purpose, in the commit that adds the order path.
    """
    offenders = [
        str(path.relative_to(ROOT))
        for package in ("api", "core")
        for path in sorted((ROOT / package).rglob("*.py"))
        if "add_order" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.reading'`. The layering
test passes already; it is a guard, not a feature.

- [ ] **Step 3: Write the read**

`core/reading.py`:

```python
"""The Kraken reads a portfolio view needs, through clients the caller hands in.

Used by `POST /portfolio/refresh` now and by the scheduler in phase 7. Every read is
required: one that fails raises, and nothing is recorded from a partial answer.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

from core.markets import TRADABLE_SUFFIXES, resolve_pair, split_balance_key
from core.portfolio import PortfolioView, build_view
from engine.types import ZERO, UnpricedAsset


class PortfolioUnavailable(Exception):
    """Kraken did not answer one of the reads. The message names which."""


class ConfiguredAsset(Protocol):
    asset: str
    pair: str
    target_pct: Decimal


def read_portfolio(public, private, fiat: str, assets: Iterable[ConfiguredAsset]) -> PortfolioView:
    configured = list(assets)
    names = public.assets()
    if names is None:
        raise PortfolioUnavailable("asset names")
    balances = private.balance()
    if balances is None:
        raise PortfolioUnavailable("balance")

    targets = {row.asset: row.target_pct for row in configured}
    pair_of = {row.asset: row.pair for row in configured}

    held = set()
    for key, amount in balances.items():
        name, suffix = split_balance_key(key, names)
        if amount != ZERO and suffix in TRADABLE_SUFFIXES:
            held.add(name)
    unmanaged = sorted(held - set(targets) - {fiat})
    if unmanaged:
        pairs = public.asset_pairs()
        if pairs is None:
            raise PortfolioUnavailable("asset pairs")
        for asset in unmanaged:
            meta = resolve_pair(asset, fiat, names, pairs)
            if meta is not None:
                pair_of[asset] = meta.pair

    quotes = public.ticker(sorted(set(pair_of.values()))) if pair_of else {}
    if quotes is None:
        raise PortfolioUnavailable("prices")
    prices = {asset: quotes[pair] for asset, pair in pair_of.items() if pair in quotes}

    try:
        return build_view(balances, names, fiat, targets, prices)
    except UnpricedAsset as exc:
        raise PortfolioUnavailable(f"a price for {exc.asset}") from None
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core -v`
Expected: PASS.

- [ ] **Step 5: Write the failing integration tests**

`tests/integration/test_api_portfolio.py`:

```python
import base64
from datetime import UTC, datetime
from decimal import Decimal

from core.db.orders import record_attempt
from core.db.telemetry import latest_snapshot, start_evaluation
from core.db.types import OrderReason
from core.db.users import get_credentials
from engine.types import Side

KEY = "TEST-API-KEY-FOR-ALICE"
SECRET = base64.b64encode(b"alice-test-secret-value").decode()


def _ready(api, headers, *, weights=(("XBT", "50"),)):
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    for asset, pct in weights:
        api.put(f"/assets/{asset}", json={"target_pct": pct}, headers=headers)
    api.post("/credentials", json={"api_key": KEY, "api_secret": SECRET}, headers=headers)


def test_there_is_no_portfolio_until_the_first_refresh(api, make_user, login):
    assert api.get("/portfolio", headers=login(make_user())).status_code == 404


def test_a_refresh_needs_settings(api, make_user, login):
    assert api.post("/portfolio/refresh", headers=login(make_user())).status_code == 409


def test_a_refresh_needs_a_registered_key(api, make_user, login):
    headers = login(make_user())
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.post("/portfolio/refresh", headers=headers).status_code == 409


def test_a_refresh_values_the_real_account_and_records_it(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "1000", "XXBT": "0.01", "XBT.F": "0.01", "XETH": "0", "DOT.S": "5"}

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["total_value"]) == Decimal("2000")
    assert Decimal(body["cash"]) == Decimal("1000")
    assets = body["holdings"]["assets"]
    assert assets["XBT"]["weight_pct"] == "50.00"
    assert assets["DOT.S"]["locked"] is True
    assert "ETH" not in assets
    assert body["as_of"].startswith("2026-09-29T12:00:00")
    assert latest_snapshot(db_session, user.id) is not None


def test_the_last_snapshot_is_read_back_without_calling_kraken(api, make_user, login, fake_kraken):
    headers = login(make_user())
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100"}
    refreshed = api.post("/portfolio/refresh", headers=headers).json()
    fake_kraken.calls.clear()

    assert api.get("/portfolio", headers=headers).json() == refreshed
    assert fake_kraken.calls == []


def test_a_failed_read_records_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.down.add("Balance")

    assert api.post("/portfolio/refresh", headers=headers).status_code == 503
    assert latest_snapshot(db_session, user.id) is None


def test_a_managed_asset_with_no_price_records_nothing(api, db_session, make_user, login, fake_kraken):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    fake_kraken.balance = {"ZEUR": "100", "XXBT": "1"}
    del fake_kraken.prices["XXBTZEUR"]

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 503
    assert "XBT" in response.json()["detail"]
    assert latest_snapshot(db_session, user.id) is None


def test_a_stored_key_that_no_longer_opens_is_reported(api, db_session, make_user, login):
    user = make_user()
    headers = login(user)
    _ready(api, headers)
    record = get_credentials(db_session, user.id)
    record.ciphertext = bytes([record.ciphertext[0] ^ 1]) + record.ciphertext[1:]
    db_session.flush()

    response = api.post("/portfolio/refresh", headers=headers)

    assert response.status_code == 500
    assert "register" in response.json()["detail"]


def test_the_history_is_empty_before_anything_happened(api, make_user, login):
    headers = login(make_user())

    assert api.get("/orders", headers=headers).json() == []
    assert api.get("/sessions", headers=headers).json() == []


def test_the_history_shows_this_users_orders_and_evaluations(api, db_session, make_user, login):
    user = make_user()
    record_attempt(
        db_session,
        user.id,
        cl_ord_id="a" * 32,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=Decimal("100"),
    )
    start_evaluation(db_session, user.id, started_at=datetime(2026, 9, 29, 11, 0, tzinfo=UTC))
    headers = login(user)

    orders = api.get("/orders", headers=headers).json()
    sessions = api.get("/sessions", headers=headers).json()

    assert [order["cl_ord_id"] for order in orders] == ["a" * 32]
    assert Decimal(orders[0]["requested_fiat"]) == Decimal("100")
    assert len(sessions) == 1


def test_a_history_page_is_bounded(api, make_user, login):
    headers = login(make_user())

    assert api.get("/orders", params={"limit": 201}, headers=headers).status_code == 422
    assert api.get("/sessions", params={"limit": 0}, headers=headers).status_code == 422
```

- [ ] **Step 6: Add the schemas**

Append to `api/schemas.py`:

```python
class PortfolioOut(BaseModel):
    as_of: datetime
    fiat: str
    # Managed assets plus cash: the denominator of every weight.
    total_value: Decimal
    cash: Decimal
    holdings: dict[str, object]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cl_ord_id: str
    txid: str | None
    pair: str
    asset: str
    side: str
    reason: str
    status: str
    requested_fiat: Decimal
    executed_volume: Decimal | None
    executed_price: Decimal | None
    fee: Decimal | None
    created_at: datetime


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: str
    log_messages: str | None
```

- [ ] **Step 7: Write the routes**

`api/routes/portfolio.py`:

```python
"""The last snapshot, shown at once, and a refresh that reads Kraken now (spec §10.4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import PortfolioOut
from core.crypto import CredentialsUnreadable, Sealed
from core.db.models import PortfolioSnapshot
from core.reading import PortfolioUnavailable, read_portfolio

logger = logging.getLogger("coinpilot.api")

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _out(snapshot: PortfolioSnapshot) -> PortfolioOut:
    return PortfolioOut(
        as_of=snapshot.as_of,
        fiat=snapshot.fiat,
        total_value=snapshot.total_value,
        cash=snapshot.cash,
        holdings=snapshot.holdings,
    )


@router.get("", response_model=PortfolioOut)
def read(user: CurrentUser, session: Db) -> PortfolioOut:
    snapshot = db.latest_snapshot(session, user.id)
    if snapshot is None:
        raise HTTPException(404, "no snapshot yet; POST /portfolio/refresh to take one")
    return _out(snapshot)


@router.post("/refresh", response_model=PortfolioOut)
def refresh(user: CurrentUser, session: Db, context: Ctx) -> PortfolioOut:
    settings = db.get_settings(session, user.id)
    if settings is None:
        raise HTTPException(409, "choose a fiat with PATCH /config first")
    record = db.get_credentials(session, user.id)
    if record is None:
        raise HTTPException(409, "register a Kraken key with POST /credentials first")

    try:
        credentials = context.cipher.unseal(user.id, Sealed(record.ciphertext, record.nonce, record.key_version))
    except CredentialsUnreadable:
        # The user id only: which record, never anything read from it.
        logger.error("stored credentials for user %s do not open", user.id)
        raise HTTPException(500, "the stored key cannot be read; register it again") from None

    try:
        view = read_portfolio(
            context.public_kraken(),
            context.kraken_for(credentials),
            settings.fiat,
            db.list_assets(session, user.id),
        )
    except PortfolioUnavailable as exc:
        raise HTTPException(503, f"kraken did not return {exc}; nothing was recorded") from None

    snapshot = db.record_snapshot(
        session,
        user.id,
        as_of=context.now(),
        fiat=settings.fiat,
        total_value=view.managed_value,
        cash=view.cash,
        holdings=view.snapshot_json(),
    )
    return _out(snapshot)
```

`api/routes/history.py`:

```python
"""What happened: the orders attempted and the evaluations run. Both empty until phase 5."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

import core.database as db
from api.deps import CurrentUser, Db
from api.schemas import EvaluationOut, OrderOut

router = APIRouter(tags=["history"])

Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("/orders", response_model=list[OrderOut])
def orders(user: CurrentUser, session: Db, limit: Limit = 50) -> list[OrderOut]:
    return [OrderOut.model_validate(row) for row in db.list_orders(session, user.id, limit=limit)]


@router.get("/sessions", response_model=list[EvaluationOut])
def sessions(user: CurrentUser, session: Db, limit: Limit = 50) -> list[EvaluationOut]:
    return [EvaluationOut.model_validate(row) for row in db.list_evaluations(session, user.id, limit=limit)]
```

- [ ] **Step 8: Register the routers**

In `api/app.py`, the import becomes
`from api.routes import assets, auth, config, credentials, health, history, portfolio` and:

```python
    for router in (
        health.router,
        auth.router,
        credentials.router,
        config.router,
        assets.router,
        portfolio.router,
        history.router,
    ):
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests -v`
Expected: PASS, the whole suite.

- [ ] **Step 10: Commit**

```bash
git add core/reading.py api tests
git commit -m "feat(api): read the portfolio from Kraken and keep the snapshot"
```

---

### Task 13: Tenant isolation over HTTP, the sign-in design in the spec, and the phase gate

**Files:**
- Create: `tests/integration/test_api_tenant_isolation.py`
- Modify: `docs/specs/2026-09-17-platform-design.md`, `README.md`

**Interfaces:**
- Consumes: every route above. Produces nothing new.

Phase 2 proved the DAL cannot mix users. This proves the routes do not either: no route
takes a user id, and every one of them derives the user from the token.

- [ ] **Step 1: Write the tests**

`tests/integration/test_api_tenant_isolation.py`:

```python
"""User A must never read or change user B's data through the API.

Every route here would pass its own tests with one user. This file is the only place a
second user exists.
"""

import base64
from decimal import Decimal

import pytest

from core.db.orders import record_attempt
from core.db.settings import list_assets
from core.db.types import OrderReason
from engine.types import Side

SECRET = base64.b64encode(b"alice-test-secret-value").decode()


@pytest.fixture
def alice(make_user):
    return make_user(email="alice@example.test")


@pytest.fixture
def bob(make_user):
    return make_user(email="bob@example.test")


@pytest.fixture
def alice_ready(api, login, alice, fake_kraken):
    headers = login(alice)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)
    api.put("/assets/XBT", json={"target_pct": "60"}, headers=headers)
    api.post("/credentials", json={"api_key": "ALICE-KEY", "api_secret": SECRET}, headers=headers)
    fake_kraken.balance = {"ZEUR": "100"}
    api.post("/portfolio/refresh", headers=headers)
    return headers


def test_settings_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/config", headers=login(bob)).status_code == 404


def test_weights_are_not_shared(api, login, bob, alice_ready):
    assert api.get("/assets", headers=login(bob)).json()["assets"] == []


def test_deleting_a_weight_touches_only_ones_own(api, db_session, login, alice, bob, alice_ready):
    assert api.delete("/assets/XBT", headers=login(bob)).status_code == 404
    assert [row.asset for row in list_assets(db_session, alice.id)] == ["XBT"]


def test_a_key_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/credentials/status", headers=login(bob)).json()["registered"] is False


def test_deleting_a_key_touches_only_ones_own(api, login, bob, alice_ready):
    assert api.delete("/credentials", headers=login(bob)).status_code == 404
    assert api.get("/credentials/status", headers=alice_ready).json()["registered"] is True


def test_a_refresh_never_borrows_another_users_key(api, login, bob):
    headers = login(bob)
    api.patch("/config", json={"fiat": "EUR"}, headers=headers)

    assert api.post("/portfolio/refresh", headers=headers).status_code == 409


def test_a_snapshot_is_not_shared(api, login, bob, alice_ready):
    assert api.get("/portfolio", headers=login(bob)).status_code == 404


def test_orders_are_not_shared(api, db_session, login, alice, bob):
    record_attempt(
        db_session,
        alice.id,
        cl_ord_id="b" * 32,
        pair="XXBTZEUR",
        asset="XBT",
        side=Side.BUY,
        reason=OrderReason.INVEST,
        requested_fiat=Decimal("10"),
    )

    assert api.get("/orders", headers=login(bob)).json() == []
```

- [ ] **Step 2: Run them**

Run: `RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/integration/test_api_tenant_isolation.py -v`
Expected: PASS. These tests pin behaviour the earlier tasks already built; one that fails
is a real defect in a route, not in this file.

- [ ] **Step 3: Write the sign-in design into the spec**

In `docs/specs/2026-09-17-platform-design.md`, four changes.

§5.1 gains a final paragraph:

```markdown
The provider is Google. A sign-in returns two tokens. The **access token** is a JWT that
lives 15 minutes and carries the user id and nothing personal. The **refresh token** is a
random value the server stores only as a SHA-256, and it is good for one use. Every
refresh issues the next token in the same *family*. A sign-in lasts 30 days from the
Google login, and refreshing never extends it, and a used token presented
again revokes the whole family, because the server cannot tell the owner from the thief.
Logout revokes the family. An application sends both tokens in the body and the bearer
header; a browser receives them as `HttpOnly` cookies, the refresh cookie `SameSite=Strict`
and scoped to `/auth`.
```

The table in §6 gains a row after `users`:

```markdown
| `refresh_tokens` | One row per refresh token: SHA-256, family, expiry, used and revoked timestamps. Expired rows are deleted by retention. |
```

The OAuth row of §11 becomes:

```markdown
| `GET /auth/login/{provider}`, `GET /auth/callback/{provider}`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | OAuth sign-in, token refresh and logout |
```

§15 gains, after the first bullet:

```markdown
- **An access token outlives logout by at most its own lifetime.** It is never looked up,
  so logout cannot reach it. Its 15 minutes are the bound, and the check of the user's
  status on every request makes disabling an account immediate regardless.
- **Two refreshes with the same token at once end the sign-in.** Strict reuse detection
  cannot tell two browser tabs from a thief. A grace window of a few seconds is the
  refinement if it proves annoying.
```

§14 gains:

```markdown
- **A rotating refresh token, not a long-lived JWT.** A JWT cannot be revoked, so it is
  kept short; the refresh token is what a session lasts on, and it is revocable because
  the server looks it up. Rotation with reuse detection turns a stolen refresh token into
  a signed-out user instead of a silent second session.
```

- [ ] **Step 4: Update the README**

In `README.md`, the status line becomes:

```markdown
> **Status: in development.** Phase 4 of 8: sign-in, encrypted keys and the read path.
> It cannot place an order yet.
```

and add, before `## Security`:

````markdown
## Running it locally

```bash
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env    # then fill in the secrets it describes
set -a; . ./.env; set +a
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. uvicorn --factory api.main:build --port 8000
```

Sign in at `http://localhost:8000/auth/login/google`. The API is described at
`http://localhost:8000/docs`.
````

- [ ] **Step 5: Run the whole gate**

Run each, and expect each to pass:

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
RUN_DB_INTEGRATION=true PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests --cov-fail-under=80
```

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_api_tenant_isolation.py
git commit -m "test(api): no route shows or changes another user's data"
git add docs/specs/2026-09-17-platform-design.md README.md
git commit -m "docs: record the sign-in design and its accepted risks"
```

---

## What you verify before phase 5

Phase 4 is the first phase that reads a real account. It still cannot spend from it: a
test fails if `add_order` appears anywhere under `api/` or `core/`.

### 1. The check deferred from phase 3

Run `scripts/check_key.py` with two keys, as the phase 3 plan describes:

| Key | Permissions | Expected |
|---|---|---|
| A | Query Funds, Query Open Orders & Trades, Query Closed Orders & Trades, Create & Modify Orders | `accepted: True` |
| B | The same, **plus Withdraw Funds** | `accepted: False`, `forbidden: withdraw-funds` |

**Delete key B as soon as you have seen it refused.** Keep key A for the steps below.

### 2. Set up the local environment

1. In the Google Cloud console, create an OAuth client of type **Web application** with
   the redirect URI `http://localhost:8000/auth/callback/google`. While the consent screen
   is in testing, add your own address as a test user.
2. Copy `.env.example` to `.env` and fill it in. The file itself says how to generate
   `JWT_SECRET` and `CREDENTIAL_KEYS`, and `COOKIE_SECURE=false` is correct for
   `http://localhost`.
3. Start the database, apply the migrations and start the API, as the README's
   "Running it locally" section shows.

### 3. Sign in

Open `http://localhost:8000/auth/login/google` in a browser. After Google, the page
shows a JSON body with `access_token` and `refresh_token`. Then open
`http://localhost:8000/auth/me`: it answers with your email, through the cookie.

Copy both tokens for the commands below:

```bash
TOKEN=...
```

```bash
REFRESH=...
```

The access token lives 15 minutes. When a command answers `401`, trade the refresh
token for a new pair and copy both values again:

```bash
curl -s -X POST localhost:8000/auth/refresh -H "Content-Type: application/json" -d "{\"refresh_token\": \"$REFRESH\"}"
```

### 4. Declare a fiat and weights

```bash
curl -s -X PATCH localhost:8000/config -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"fiat": "EUR"}'
```

```bash
curl -s -X PUT localhost:8000/assets/XBT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"target_pct": "60"}'
```

Use your real weights. Bitcoin is `XBT` in Kraken's vocabulary; `BTC` is refused.

### 5. Register key A

`read -s` keeps the secret off the screen and out of the shell history:

```bash
read -rp "API key: " K; read -rsp "API secret: " S; echo
```

```bash
curl -s -X POST localhost:8000/credentials -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"api_key\": \"$K\", \"api_secret\": \"$S\"}"; unset K S
```

Expect `201` with your permissions and, if you set one, your IP allowlist. Try it once
with a mistyped secret too: the answer is `invalid_key`, no longer "unreachable".

### 6. Read your real portfolio

```bash
curl -s -X POST localhost:8000/portfolio/refresh -H "Authorization: Bearer $TOKEN"
```

Compare it with Kraken's own screen:

- Each managed asset's amount, including anything in Kraken Rewards (`.F`).
- Staked balances appear as locked, and count for nothing.
- `cash` is your free fiat, and `total_value` is managed assets plus cash.
- An asset you hold but did not configure is listed with `managed: false`.

Then `GET /portfolio` returns the same body at once, without calling Kraken.

### 7. Read the data at rest

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "select user_id, length(ciphertext), key_version, validated_at from user_credentials"
```

There is one row, and nothing in it is readable. Nothing in the API's own log shows the
key either.

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "select family_id, issued_at, used_at, revoked_at from refresh_tokens order by issued_at"
```

One row per refresh you made, all in one family, every one but the last with `used_at`
set. No column holds a token you could present.

### 8. See a stolen refresh token end the sign-in

1. Refresh once with `$REFRESH`, and keep the new refresh token the answer gives you.
2. Refresh again with the **old** `$REFRESH`. The answer is `401`, `reused`.
3. Refresh with the new token from step 1. It is `401` as well: the whole sign-in ended.
4. The `refresh_tokens` query above now shows `revoked_at` on every row of that family.

Then sign in again in the browser, and use `POST /auth/logout` there. `/auth/me` answers
`401` afterwards.

### 9. Two decisions deserve a deliberate look

- **An access token outlives logout by up to 15 minutes.** It is never looked up, so
  logout cannot reach it. Section §15 says so, and a test pins it.
- **Assets use Kraken's short names.** `XBT`, not `BTC`. The project 2 application is the
  natural place to translate for people; this API stays exact.
