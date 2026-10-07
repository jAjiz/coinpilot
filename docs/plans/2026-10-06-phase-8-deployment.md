# Phase 8 — Deployment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The platform runs in production on a Google Cloud VM that has no port open to
the internet. A release is an image in GHCR, deployed or rolled back with one dispatched
workflow, and the master encryption key can be rotated without losing a stored
credential.

**Architecture:** The code changes are the production hardening earlier phases deferred:
`core/logs.py` keeps OAuth codes and PostgreSQL row values out of the log,
the Kraken rate limiter counts per user, and `core/rotation.py` re-seals every stored credential
under the active master key. The image is one `Dockerfile`. Everything the host runs is
in `deploy/`: a compose file (PostgreSQL, a one-shot migration, the platform), a wrapper
around `docker compose`, and `deploy.sh`, which backs up, migrates, starts and waits for
health, or rolls back. GitHub Actions builds an image for every green commit on `main`
(`release.yml`). A deploy is dispatched by hand (`deploy.yml`): it authenticates to
Google Cloud with Workload Identity Federation, with no stored key, and runs `deploy.sh`
over SSH through an IAP tunnel. `docs/operations.md` is the runbook: provisioning,
secrets, access, deploy, rollback, rotation, backups.

**Tech Stack:** Python 3.13, Docker, Docker Compose v2, GitHub Actions, GHCR, Google
Compute Engine, Identity-Aware Proxy, Workload Identity Federation, Debian 13. No new
Python dependency.

**Spec:** [`docs/specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md) — §4.1, §5.3, §9.2, §10.3, §12, §13, §15, §16

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — this is phase 8 of 8

## Global Constraints

- **Python 3.13.** One version, not a range: the image is `python:3.13-slim-trixie`,
  CI's `setup-python` says `3.13`, and so does the local venv.
- **Pin every dependency with `==`.** This phase adds no Python dependency. Every GitHub
  Action is pinned to an exact release tag, as `actions/checkout@v7.0.1` already is.
- **No secret, project id, IP address, host name or service-account e-mail in the
  repository.** They live on the host (`/opt/coinpilot/.env`), in the GitHub environment
  `production` (as variables), or in the operator's shell. The runbook uses shell
  variables (`$PROJECT`, `$ZONE`, …) for them.
- **No port of the host is open to the internet.** SSH is reached only through IAP
  (`35.235.240.0/20`); the API listens on the host's loopback only.
- **A migration must leave the previous release working.** Additive only: a new column
  is nullable or has a default, nothing is renamed or dropped in the release that stops
  using it. A rollback then never needs a downgrade.
- **No test reads configuration from the environment**, no test touches the network,
  and no test places a real order.
- **Integration tests share the development database**, inside a transaction that is
  rolled back. No test asserts a count across every user: the development database holds
  the real user's row.
- **No log line contains a credential** or anything read with one. A script prints user
  ids and counts, nothing else about a user.
- **Coverage gate is 80 %**, enforced by the CI command.
- **`ruff check` and `ruff format --check` must pass.** Lines are 110 characters. Run
  `ruff format` on every Python file before its commit. **`shellcheck` must pass** on
  every file in `deploy/`.
- Commit messages follow Conventional Commits, and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Test command, used by every Python task (PostgreSQL from `docker-compose.dev.yml`
running):

```bash
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests
```

## Review Focus

Each of these, if wrong, loses data, leaks a secret, or leaves the host reachable. Each
has a test or a CI check in the task that owns it.

1. **Rotation never loses a credential.** A record is re-sealed under a row lock, in its
   own transaction, and only after it opened; one that does not open is left as it was
   and reported. → Task 3.
2. **A deploy backs up before it migrates, and a failed start is loud.** `deploy.sh`
   dumps the database before the migration and exits non-zero, with the platform's log,
   when the new release does not become healthy. → Task 5, exercised in CI.
3. **A rollback runs no migration.** It starts the previous image against the current
   schema, which the additive rule keeps compatible. → Task 5, exercised in CI.
4. **Stopping the platform waits for the tick.** `stop_grace_period` is longer than a
   tick can take, so a deploy never kills an evaluation between an order and its answer.
   → Task 5.
5. **No secret in the log.** The OAuth `code` leaves the access log, and PostgreSQL's
   `DETAIL:` lines leave every traceback. → Task 1.
6. **Nothing listens on the internet.** The API is published on `127.0.0.1` only, and the
   firewall admits SSH from IAP's range only. → Tasks 5 and 7, checked by hand.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/logs.py` | `configure()`; `Formatter` drops `DETAIL:` lines; `WithoutQuery` strips the query from uvicorn's access log |
| `api/main.py` | Calls `logs.configure()` instead of its own `_log_to_stderr` |
| `exchange/client.py` | `KrakenClient(..., bucket=)`: what the limiter counts private calls under |
| `api/context.py`, `core/execution.py`, `api/routes/credentials.py`, `api/routes/portfolio.py` | `kraken_for(user_id, credentials)` counts under the user |
| `core/crypto.py` | `CredentialCipher.active_version` |
| `core/db/users.py` | `credential_owners_not_at`, `lock_credentials` |
| `core/database.py` | Exports the two |
| `core/rotation.py` | `Outcome`, `RotationReport`, `reseal`, `rotate` |
| `scripts/rotate_master_key.py` | The rotation, run by hand on the host; `--check` changes nothing |
| `Dockerfile`, `.dockerignore` | The production image |
| `deploy/compose.yml` | PostgreSQL, `migrate` (on demand), `platform` |
| `deploy/compose.sh` | `docker compose` with the host's `.env` and `release.env` |
| `deploy/deploy.sh` | `deploy <tag>` and `rollback` |
| `deploy/bootstrap.sh` | Prepares a fresh Debian 13 VM, run once |
| `deploy/env.production.example` | The production `.env`, every value to be generated on the host |
| `.github/workflows/ci.yml` | New job `image`: build, shellcheck, deploy, deploy again, roll back |
| `.github/workflows/release.yml` | Builds and pushes `ghcr.io/jajiz/coinpilot:<sha>` for every green commit on `main` |
| `.github/workflows/deploy.yml` | Dispatched by hand: deploy a tag, or roll back |
| `docs/operations.md` | The runbook |
| `docs/specs/2026-09-17-platform-design.md` | §13 describes the deployment as built; status |
| `README.md` | Status; a Production section pointing at the runbook |

---

## Decisions taken in this plan

The spec settles what to build. These settle how, where the spec leaves room or where
the user chose while this plan was written.

- **A new VM on Google Cloud, not the old bot's.** `e2-small` (2 vCPU shared, 2 GB) with
  Debian 13 and a 20 GB balanced disk. 1 GB would hold PostgreSQL and one Python process,
  but with nothing to spare during a deploy, when two images are on disk and a dump is
  written. Region and zone are the operator's choice; the runbook's commands take them
  as variables.
- **SSH only through IAP.** The default `default-allow-ssh` and `default-allow-rdp` rules
  are deleted, and one rule admits `tcp:22` from `35.235.240.0/20`, Google's IAP range.
  Every SSH session (the operator's and the pipeline's) is
  `gcloud compute ssh --tunnel-through-iap`, with OS Login. The VM runs with no service
  account: nothing on it calls a Google API.
- **The API stays on the host's loopback.** The operator reaches it with an SSH tunnel
  (`-L 8000:localhost:8000`), so the Google callback stays
  `http://localhost:8000/auth/callback/google` and the OAuth client needs no change.
  Exposing it is project 2 (§16).
- **A static external IP, already reserved by the user.** The VM needs outbound access
  to Kraken, GHCR and Debian. A static address also lets the Kraken key be restricted to
  it, so a stolen key works from nowhere else; that adds to the permission contract
  (§5.2), which already refuses a key that can withdraw. Google charges an external IPv4
  in use the same whether it is static or ephemeral. The address and the VM must be in
  the same region.
- **The image is public.** The repository is public, so the image holds nothing that
  is not, and the host pulls with no registry credential. Tags are full commit SHAs and
  never move; there is no `latest`.
- **Build on green, deploy by hand.** `release.yml` builds an image for every commit on
  `main` whose CI passed. A deploy is `deploy.yml`, dispatched with the SHA. This system
  spends money on its own, so a merge does not put code in charge of it until someone
  decides it should.
- **Workload Identity Federation, not a service-account key.** GitHub's OIDC token is
  exchanged for a short-lived Google token. The provider accepts only this repository
  and only the `production` environment. The deploy service account holds
  `roles/iap.tunnelResourceAccessor`, `roles/compute.viewer` and, on the instance only,
  `roles/compute.osAdminLogin`. Each SSH key the pipeline registers expires after 30
  minutes.
- **Migrations run as a separate one-shot container, before the new platform starts.**
  `deploy.sh` brings PostgreSQL up, dumps it, runs `alembic upgrade head` with the new
  image, then recreates the platform and waits until Docker reports it healthy. A
  rollback skips the migration; the additive rule is what makes that safe. A migration
  that breaks the rule needs a restore from the dump taken before it, and the runbook
  says how.
- **Backups: a dump before every deploy, a disk snapshot every day.** The dump is the
  consistent copy taken at the risky moment, kept on the host (the newest ten). The
  snapshot schedule keeps 14 daily copies of the whole disk off the host. No other backup
  tool.
- **Logs stay in Docker.** The daemon's `local` driver, 10 MB × 5 files per container.
  Shipping them anywhere, and turning the failure-streak warning into a message, is
  project 2 with notifications. The runbook says how to read them.
- **Rotation re-seals in place.** The cipher already opens every version it holds and
  seals with the active one (phase 4). Rotating is: add the new key and make it active,
  restart, run `scripts/rotate_master_key.py`, check nothing is left under the old
  version, remove the old key, restart. Each record is re-sealed in its own transaction
  under `SELECT … FOR UPDATE`, so a user who registers a new key meanwhile is neither lost
  nor overwritten. `validated_at` does not change: nothing was validated again.
- **The master key's backup lives outside Google Cloud**, in the operator's password
  manager. Losing the project must not also lose the only thing that opens the
  credentials in a restored dump.
- **Deferred items from earlier phases, settled here:** the uvicorn access log no longer
  carries the callback's `code` (phase 4); PostgreSQL's `DETAIL:` lines no longer reach
  the log (phase 7); the rate limiter holds one entry per user, not one per key ever tried (phase 4); `stop()` waiting for the
  batch is now what `stop_grace_period` is sized for (phase 7). Two stay deferred, see
  below.

## What this phase deliberately leaves out

- **Exposing the API to the internet**, TLS, a domain — project 2 (§16).
- **Notifications and log shipping.** The alert is still a log line read by hand.
- **Monitoring and uptime checks.** Docker restarts a platform that dies; nothing pages
  anyone. A single-user service accepts that until project 2.
- **The database connection budget.** The pool's default (5 + 10 overflow) and
  `SCHEDULER_WORKERS=4` fit PostgreSQL's 100 connections many times over. Revisit only if
  either is raised.
- **A synchronous backfill at start-up.** It takes milliseconds for a handful of users.
- **Automatic deploy on merge**, and automatic rollback on a failed start — a failed
  start leaves nothing trading, which is the safe state; the operator decides.

---

### Task 1: Logs that can be kept

**Files:**
- Create: `core/logs.py`
- Modify: `api/main.py`
- Test: `tests/unit/core/test_logs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `core.logs.configure() -> None`, `core.logs.Formatter`,
  `core.logs.WithoutQuery`, `core.logs.FORMAT: str`.

uvicorn's access log records the request line with its query string, and Google's
callback carries the single-use `code` in its query. PostgreSQL's own error text carries
a `DETAIL:` line with the values of the row it refused (`Key (txid)=(…) already
exists`), and `hide_parameters=True` does not reach it: it is part of the driver's
message, printed in every traceback.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_logs.py`:

```python
import logging
import sys

import pytest

from core.logs import FORMAT, Formatter, WithoutQuery, configure

ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


def _record_raising(exc: Exception) -> logging.LogRecord:
    try:
        raise exc
    except Exception:
        return logging.LogRecord("coinpilot.scheduler", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())


def _access(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, ACCESS_FORMAT, ("10.0.0.1:5000", "GET", path, "1.1", 302), None
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
        RuntimeError('duplicate key value violates unique constraint "orders_txid"\nDETAIL:  Key (txid)=(OABC-1) exists.')
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_logs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.logs'`

- [ ] **Step 3: Write `core/logs.py`**

```python
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
```

uvicorn's access logger does not propagate and has its own handler; with the default
`--log-config`, its access formatter is uvicorn's. Only the filter is needed there: the
query leaves the record before any formatter sees it.

- [ ] **Step 4: Use it in `api/main.py`**

Delete `_log_to_stderr` and its `import logging`. Add `from core import logs` to the
imports and make the first line of `build()`:

```python
    logs.configure()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_logs.py -v`
Expected: PASS (6 tests). Then the whole suite with the test command: PASS.

- [ ] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff format core/logs.py api/main.py tests/unit/core/test_logs.py
git add core/logs.py api/main.py tests/unit/core/test_logs.py
git commit -m "feat(logs): no OAuth code in the access log and no PostgreSQL DETAIL in a traceback"
```

---

### Task 2: One limiter entry per user

**Files:**
- Modify: `exchange/client.py`, `api/context.py`, `core/execution.py`,
  `api/routes/credentials.py`, `api/routes/portfolio.py`
- Test: `tests/unit/exchange/test_client.py`, `tests/integration/test_api_credentials.py`

**Interfaces:**
- Consumes: `KeyLimiter.wait_turn(bucket)`, `KeyLimiter.next_nonce(bucket)` (unchanged).
- Produces: `KrakenClient(http, limiter, credentials=None, *, bucket: str | None = None)`
  — private calls pace and count nonces under `bucket`, or under the API key when it is
  `None`; `AppContext.kraken_for(user_id: uuid.UUID, credentials) -> KrakenClient`, and
  the same signature on the `ExecutionContext` protocol.

The limiter's two dicts are keyed by API key, and every key sent to
`POST /credentials`, wrong ones included, stays in them until the process restarts.
Keyed by user instead, the limiter holds at most one entry per user (plus the public
bucket), as the database holds at most one credential per user.

Nothing is lost by it. A user has one key at a time. While they register a new one, the
validation and a scheduled evaluation with the old one share one pace, which is only
more conservative than Kraken requires. Their nonces come from one counter, which still
increases for each key, and a new key accepts any first nonce. `scripts/check_key.py`
has no user and passes no bucket, so it still counts under the key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/exchange/test_client.py`:

```python
OTHER_CREDENTIALS = Credentials(api_key="ANOTHER-PUBLIC-KEY", api_secret=CREDENTIALS.api_secret)


class RecordingLimiter(KeyLimiter):
    """Paces nothing, and remembers the bucket of every call."""

    def __init__(self) -> None:
        super().__init__(0.0)
        self.buckets: list[str] = []

    def wait_turn(self, bucket: str) -> None:
        self.buckets.append(bucket)


def _balance_answer(request):
    return httpx.Response(200, json={"error": [], "result": {"ZEUR": "1"}})


def _recording_client(limiter, credentials, bucket=None):
    http = httpx.Client(base_url="https://api.kraken.com", transport=httpx.MockTransport(_balance_answer))
    return KrakenClient(http, limiter, credentials=credentials, bucket=bucket)


def test_a_private_call_counts_under_the_bucket_it_was_given():
    limiter = RecordingLimiter()

    _recording_client(limiter, CREDENTIALS, bucket="user-1")._call_private("Balance")
    _recording_client(limiter, OTHER_CREDENTIALS, bucket="user-1")._call_private("Balance")

    assert limiter.buckets == ["user-1", "user-1"]


def test_with_no_bucket_a_private_call_counts_under_its_key():
    limiter = RecordingLimiter()

    _recording_client(limiter, CREDENTIALS)._call_private("Balance")

    assert limiter.buckets == ["THE-PUBLIC-KEY"]
```

Append to `tests/integration/test_api_credentials.py`, with `import dataclasses` and
`from exchange.limits import KeyLimiter` added to its imports, and a copy of the
`RecordingLimiter` class above (the integration tests import nothing from `tests.unit`):

```python
def test_the_keys_a_user_tries_are_paced_as_one(app_context, make_user):
    limiter = RecordingLimiter()
    context = dataclasses.replace(app_context, limiter=limiter)
    user = make_user()

    context.kraken_for(user.id, Credentials("FIRST-KEY", "c2VjcmV0"))._call_private("Balance")
    context.kraken_for(user.id, Credentials("SECOND-KEY", "c2VjcmV0"))._call_private("Balance")

    assert limiter.buckets == [str(user.id), str(user.id)]
```

`FakeKraken` (the `fake_kraken` fixture behind `app_context.kraken_http`) answers
`Balance`; if it answers it only for a key it was given, use the key and secret it
expects, as the other tests in the file do. The test is about the bucket, not the answer.

- [ ] **Step 2: Run them to verify they fail**

Run the test command on `tests/unit/exchange/test_client.py tests/integration/test_api_credentials.py`.
Expected: FAIL with `TypeError` (unexpected keyword `bucket`; `kraken_for` takes one
argument).

- [ ] **Step 3: Implement**

`exchange/client.py`, `KrakenClient.__init__` gains a keyword-only argument and stores it:

```python
    def __init__(
        self,
        http: httpx.Client,
        limiter: KeyLimiter,
        credentials: Credentials | None = None,
        *,
        bucket: str | None = None,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._credentials = credentials
        # What the limiter counts this identity under: the user, when there is one, so the
        # limiter holds one entry per user however many keys they try.
        self._bucket = bucket
```

In `_call_private`, replace the two limiter lines with:

```python
        bucket = self._bucket or credentials.api_key
        self._limiter.wait_turn(bucket)
        nonce = self._limiter.next_nonce(bucket)
```

`api/context.py`:

```python
    def kraken_for(self, user_id: uuid.UUID, credentials: Credentials) -> KrakenClient:
        """A client for one request. The limiter is shared and counts per user: one entry
        per user, however many keys they try, as the database holds one."""
        return KrakenClient(self.kraken_http, self.limiter, credentials=credentials, bucket=str(user_id))
```

`core/execution.py`, the protocol: `def kraken_for(self, user_id: uuid.UUID, credentials: Credentials): ...`,
and both call sites become `context.kraken_for(user_id, context.cipher.unseal(user_id, account.sealed))`.

`api/routes/credentials.py`: `validate_key(context.kraken_for(user.id, credentials))`.
`api/routes/portfolio.py`: `context.kraken_for(user.id, credentials)`.

Then `grep -rn "kraken_for(" api core tests` must show no call with one argument; the
scheduler's tick context delegates to the application's, so it needs no change, but
check it.

- [ ] **Step 4: Run the whole suite**

Run the test command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
.venv/Scripts/python.exe -m ruff format exchange api core tests
git add exchange/client.py api/context.py core/execution.py api/routes/credentials.py api/routes/portfolio.py tests/unit/exchange/test_client.py tests/integration/test_api_credentials.py
git commit -m "fix(limits): count Kraken calls per user, so the limiter holds one entry per user"
```

---

### Task 3: Master-key rotation

**Files:**
- Modify: `core/crypto.py`, `core/db/users.py`, `core/database.py`
- Create: `core/rotation.py`, `scripts/rotate_master_key.py`
- Test: `tests/unit/core/test_crypto.py`, `tests/integration/test_users.py`,
  `tests/integration/test_rotation.py`

**Interfaces:**
- Consumes: `CredentialCipher.seal/unseal`, `Sealed`, `CredentialsUnreadable`
  (`core/crypto.py`); `save_credentials`, `get_credentials` (`core/db/users.py`).
- Produces:
  - `CredentialCipher.active_version -> int` (property)
  - `db.credential_owners_not_at(session, version: int) -> list[uuid.UUID]`
  - `db.lock_credentials(session, user_id) -> UserCredentials | None`
  - `core.rotation.Outcome` (`RESEALED`, `CURRENT`, `GONE`, `UNREADABLE`)
  - `core.rotation.reseal(session, cipher, user_id) -> Outcome`
  - `core.rotation.RotationReport(resealed: tuple[UUID, ...], unreadable: tuple[UUID, ...])`
    with `.ok -> bool`
  - `core.rotation.rotate(sessions, cipher) -> RotationReport`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/core/test_crypto.py`:

```python
def test_the_cipher_says_which_version_it_seals_with():
    assert _cipher({1: KEY_1, 2: KEY_2}, active=2).active_version == 2
```

Append to `tests/integration/test_users.py` (add `credential_owners_not_at` and
`lock_credentials` to its `core.db.users` import):

```python
def _store_at(session: Session, user_id, version: int) -> None:
    save_credentials(session, user_id, b"cipher", b"n" * 12, version, VALIDATED)


def test_the_owners_of_records_under_another_version_are_listed(db_session: Session, make_user):
    old, current = make_user(), make_user()
    _store_at(db_session, old.id, 1)
    _store_at(db_session, current.id, 2)

    owners = credential_owners_not_at(db_session, 2)

    # Membership only: the development database holds the real user's record too.
    assert old.id in owners
    assert current.id not in owners


def test_a_record_is_locked_and_returned(db_session: Session, make_user):
    user = make_user()
    _store_at(db_session, user.id, 1)

    assert lock_credentials(db_session, user.id).key_version == 1


def test_locking_a_missing_record_returns_none(db_session: Session, make_user):
    assert lock_credentials(db_session, make_user().id) is None
```

`tests/integration/test_rotation.py`:

```python
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.crypto import CredentialCipher, Sealed
from core.db.users import credential_owners_not_at, get_credentials, save_credentials
from core.rotation import Outcome, reseal, rotate
from exchange.types import Credentials

KEY_1 = bytes(range(32))
KEY_2 = bytes(range(32, 64))
KEY_3 = bytes(range(64, 96))
OLD = CredentialCipher({1: KEY_1}, 1)
NEW = CredentialCipher({1: KEY_1, 2: KEY_2}, 2)
ONLY_NEW = CredentialCipher({2: KEY_2}, 2)
CREDENTIALS = Credentials(api_key="THE-PUBLIC-KEY", api_secret="THE-SECRET-VALUE")
VALIDATED = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _store(session: Session, user_id, cipher: CredentialCipher) -> None:
    sealed = cipher.seal(user_id, CREDENTIALS)
    save_credentials(session, user_id, sealed.ciphertext, sealed.nonce, sealed.key_version, VALIDATED)


def _opened(session: Session, user_id, cipher: CredentialCipher) -> Credentials:
    record = get_credentials(session, user_id)
    return cipher.unseal(user_id, Sealed(record.ciphertext, record.nonce, record.key_version))


def _sessions(session: Session) -> Callable:
    """What `rotate` is given in production is `session_scope`. Here each unit of work is a
    savepoint inside the test's transaction, which is rolled back."""

    @contextmanager
    def sessions():
        nested = session.begin_nested()
        try:
            yield session
        except Exception:
            nested.rollback()
            raise
        else:
            nested.commit()

    return sessions


def test_a_record_under_an_old_key_is_sealed_again_under_the_active_one(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, OLD)

    outcome = reseal(db_session, NEW, alice.id)

    assert outcome is Outcome.RESEALED
    assert get_credentials(db_session, alice.id).key_version == 2
    # The old key is no longer needed to open it.
    assert _opened(db_session, alice.id, ONLY_NEW) == CREDENTIALS


def test_resealing_does_not_pretend_the_key_was_validated_again(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, OLD)

    reseal(db_session, NEW, alice.id)

    assert get_credentials(db_session, alice.id).validated_at == VALIDATED


def test_a_record_already_under_the_active_key_is_not_touched(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, NEW)
    before = get_credentials(db_session, alice.id).ciphertext

    assert reseal(db_session, NEW, alice.id) is Outcome.CURRENT
    assert get_credentials(db_session, alice.id).ciphertext == before


def test_a_user_with_no_record_is_gone(db_session: Session, make_user):
    assert reseal(db_session, NEW, make_user().id) is Outcome.GONE


def test_a_record_that_does_not_open_is_left_as_it_was(db_session: Session, make_user):
    alice = make_user()
    _store(db_session, alice.id, CredentialCipher({3: KEY_3}, 3))
    before = get_credentials(db_session, alice.id).ciphertext

    assert reseal(db_session, NEW, alice.id) is Outcome.UNREADABLE
    record = get_credentials(db_session, alice.id)
    assert (record.key_version, record.ciphertext) == (3, before)


def test_rotate_reseals_every_old_record_and_reports_the_unreadable(db_session: Session, make_user):
    alice, bob, carol, dave = make_user(), make_user(), make_user(), make_user()
    _store(db_session, alice.id, OLD)
    _store(db_session, bob.id, OLD)
    _store(db_session, carol.id, NEW)
    _store(db_session, dave.id, CredentialCipher({3: KEY_3}, 3))

    report = rotate(_sessions(db_session), NEW)

    # Membership only: the development database's real record is listed too, and it does
    # not open under this test's keys.
    assert {alice.id, bob.id} <= set(report.resealed)
    assert carol.id not in report.resealed
    assert dave.id in report.unreadable
    assert not report.ok
    left = credential_owners_not_at(db_session, 2)
    assert alice.id not in left and bob.id not in left
    assert dave.id in left
```

- [ ] **Step 2: Run them to verify they fail**

Run the test command on `tests/unit/core/test_crypto.py tests/integration/test_users.py tests/integration/test_rotation.py`.
Expected: FAIL — `AttributeError: 'CredentialCipher' object has no attribute 'active_version'`,
`ImportError` for `credential_owners_not_at`, `ModuleNotFoundError: core.rotation`.

- [ ] **Step 3: Implement the cipher property and the DAL**

`core/crypto.py`, in `CredentialCipher` after `__init__`:

```python
    @property
    def active_version(self) -> int:
        """The version `seal` uses."""
        return self._active
```

`core/db/users.py`, after `get_credentials`:

```python
def credential_owners_not_at(session: Session, version: int) -> list[uuid.UUID]:
    """The users whose record is sealed under a master key other than `version`."""
    return list(
        session.scalars(
            select(UserCredentials.user_id)
            .where(UserCredentials.key_version != version)
            .order_by(UserCredentials.user_id)
        )
    )


def lock_credentials(session: Session, user_id: uuid.UUID) -> UserCredentials | None:
    """The record, locked until the transaction ends. A concurrent `save_credentials` waits
    for it, and then writes over what this transaction wrote."""
    return session.scalars(
        select(UserCredentials).where(UserCredentials.user_id == user_id).with_for_update()
    ).one_or_none()
```

`core/database.py`: add both names to the `core.db.users` import and to `__all__`, in
alphabetical order.

- [ ] **Step 4: Write `core/rotation.py`**

```python
"""Master-key rotation: every stored credential sealed again under the active key (spec §5.3).

The cipher opens any version it holds and seals with the active one. Rotating is: add the
new key and make it active, restart, run this, check that nothing is left under the old
version, remove the old key, restart (runbook: docs/operations.md).

Each record is re-sealed in its own transaction, under a row lock. A user who registers a
new key meanwhile is neither lost nor overwritten: whichever write comes second wins, and
both are sealed with the active key. A record that does not open is left exactly as it was.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

import core.database as db
from core.crypto import CredentialCipher, CredentialsUnreadable, Sealed


class Outcome(StrEnum):
    RESEALED = "RESEALED"
    # Already under the active key.
    CURRENT = "CURRENT"
    # Deleted since it was listed.
    GONE = "GONE"
    # Under a version the cipher does not hold, or altered. Left as it was.
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class RotationReport:
    resealed: tuple[uuid.UUID, ...]
    unreadable: tuple[uuid.UUID, ...]

    @property
    def ok(self) -> bool:
        return not self.unreadable


def reseal(session: Session, cipher: CredentialCipher, user_id: uuid.UUID) -> Outcome:
    """One record, inside the caller's transaction. `validated_at` is kept: nothing was
    validated again."""
    record = db.lock_credentials(session, user_id)
    if record is None:
        return Outcome.GONE
    if record.key_version == cipher.active_version:
        return Outcome.CURRENT
    try:
        credentials = cipher.unseal(user_id, Sealed(record.ciphertext, record.nonce, record.key_version))
    except CredentialsUnreadable:
        return Outcome.UNREADABLE
    sealed = cipher.seal(user_id, credentials)
    record.ciphertext = sealed.ciphertext
    record.nonce = sealed.nonce
    record.key_version = sealed.key_version
    session.flush()
    return Outcome.RESEALED


def rotate(sessions: Callable[[], AbstractContextManager[Session]], cipher: CredentialCipher) -> RotationReport:
    """Every record not under the active key, one transaction each."""
    with sessions() as session:
        owners = db.credential_owners_not_at(session, cipher.active_version)
    resealed: list[uuid.UUID] = []
    unreadable: list[uuid.UUID] = []
    for user_id in owners:
        with sessions() as session:
            outcome = reseal(session, cipher, user_id)
        if outcome is Outcome.RESEALED:
            resealed.append(user_id)
        elif outcome is Outcome.UNREADABLE:
            unreadable.append(user_id)
    return RotationReport(tuple(resealed), tuple(unreadable))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run the test command on the three files.
Expected: PASS.

- [ ] **Step 6: Write `scripts/rotate_master_key.py`**

```python
"""Seal every stored Kraken key again under the active master key.

Run by hand on the host, after the new key was added to CREDENTIAL_KEYS, made active with
CREDENTIAL_KEY_VERSION, and the platform restarted (runbook: docs/operations.md):

    /opt/coinpilot/compose.sh run --rm platform python scripts/rotate_master_key.py
    /opt/coinpilot/compose.sh run --rm platform python scripts/rotate_master_key.py --check

`--check` changes nothing. Both exit 0 when every record is under the active key, and 1
otherwise. Only user ids and counts are printed.
"""

from __future__ import annotations

import os
import sys

import core.database as db
from core.config import load_config
from core.crypto import CredentialCipher
from core.rotation import rotate


def main(argv: list[str]) -> int:
    config = load_config(os.environ)
    db.configure(config.database_url)
    cipher = CredentialCipher(config.credential_keys, config.credential_key_version)
    print(f"active version: {cipher.active_version}")

    if argv == ["--check"]:
        with db.session_scope() as session:
            left = db.credential_owners_not_at(session, cipher.active_version)
        print(f"not under it  : {len(left)}")
        return 0 if not left else 1
    if argv:
        print("usage: rotate_master_key.py [--check]", file=sys.stderr)
        return 2

    report = rotate(db.session_scope, cipher)
    print(f"resealed      : {len(report.resealed)}")
    print(f"unreadable    : {len(report.unreadable)}")
    for user_id in report.unreadable:
        print(f"  {user_id}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Check `core/database.py` exports `configure` and `session_scope` (it imports them from
`core.db.session`); if either is missing from `__all__`, import it from
`core.db.session` directly instead.

Smoke it against the development database (it holds your real record under version 1
of your local `.env`). Run with the local `.env` loaded:

```bash
set -a; . ./.env; set +a
PYTHONPATH=. .venv/Scripts/python.exe scripts/rotate_master_key.py --check
```

Expected: `active version: 1`, `not under it  : 0`, exit 0. Do not run it without
`--check` here.

- [ ] **Step 7: Run the whole suite and commit**

Run the test command. Expected: PASS.

```bash
.venv/Scripts/python.exe -m ruff format core scripts tests
git add core/crypto.py core/db/users.py core/database.py core/rotation.py scripts/rotate_master_key.py tests/unit/core/test_crypto.py tests/integration/test_users.py tests/integration/test_rotation.py
git commit -m "feat(crypto): rotate the master key by re-sealing every credential under the active one"
```

---

### Task 4: The production image

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `api.main:build`, `alembic.ini`, `scripts/` (Task 3's script included).
- Produces: an image that runs `uvicorn --factory api.main:build` on port 8000 as uid
  10001, with a Docker `HEALTHCHECK` on `/health`; `alembic upgrade head` and
  `python scripts/rotate_master_key.py` run in it with `PYTHONPATH=/app`. Task 5 starts
  it; Task 6 publishes it as `ghcr.io/jajiz/coinpilot:<sha>`.

- [ ] **Step 1: Write `.dockerignore`**

```
# Only what the image needs goes into the build context. Above all, no .env.
.git
.github
.venv
venv
.env
.env.*
**/__pycache__
**/*.py[cod]
.pytest_cache
.ruff_cache
.coverage
htmlcov
docs
tests
deploy
*.dump
*.sql.gz
docker-compose.dev.yml
```

- [ ] **Step 2: Write the `Dockerfile`**

```dockerfile
# The platform: FastAPI and the scheduler in one process (spec §4.1).
# The same Python as CI and the venv: one version, not a range (spec §14).
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY engine engine
COPY exchange exchange
COPY core core
COPY api api
COPY scripts scripts

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin coinpilot
USER coinpilot

EXPOSE 8000

# No curl in a slim image; Python is there anyway.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# The graceful timeout covers open requests; the scheduler's stop runs after it, and the
# compose file's stop_grace_period covers both.
CMD ["uvicorn", "--factory", "api.main:build", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "60"]

LABEL org.opencontainers.image.source="https://github.com/jAjiz/coinpilot" \
      org.opencontainers.image.description="CoinPilot platform"
```

`requirements.txt` holds only wheels for this platform (`psycopg[binary]`,
`cryptography`), so no compiler and no second stage are needed.

- [ ] **Step 3: Build and check it locally**

Docker Desktop running:

```bash
docker build -t coinpilot:local .
docker run --rm coinpilot:local id -u
docker run --rm coinpilot:local python -c "import api.main, scripts.rotate_master_key; print('ok')"
docker run --rm coinpilot:local alembic --help
```

Expected: the build succeeds; `10001`; `ok`; alembic's usage text. Also check that no
secret entered the image:

```bash
docker run --rm coinpilot:local sh -c "ls -a /app"
```

Expected: `alembic.ini api core engine exchange requirements.txt scripts` and nothing
else (no `.env`, `tests`, `docs`).

- [ ] **Step 4: Build it in CI**

Append to `.github/workflows/ci.yml`, as a second job under `jobs:`:

```yaml
  image:
    name: Image and deploy script
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v7.0.1

      - name: Build
        run: docker build -t ghcr.io/jajiz/coinpilot:ci-1 .

      - name: Runs as an unprivileged user
        run: test "$(docker run --rm ghcr.io/jajiz/coinpilot:ci-1 id -u)" = 10001

      - name: Imports the application and the scripts
        run: docker run --rm ghcr.io/jajiz/coinpilot:ci-1 python -c "import api.main, scripts.rotate_master_key"
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore .github/workflows/ci.yml
git commit -m "build: the production image, built in CI"
```

Dependabot's `docker` entry (already in `.github/dependabot.yml`, directory `/`) now
finds the `Dockerfile` and proposes Python patch updates.

---

### Task 5: What the host runs, and the deploy script

**Files:**
- Create: `deploy/compose.yml`, `deploy/compose.sh`, `deploy/deploy.sh`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 4's image, tagged `ghcr.io/jajiz/coinpilot:<tag>`; Task 3's script.
- Produces, on the host in one directory (`/opt/coinpilot` in production):
  - `compose.yml`, services `postgres`, `migrate` (profile `tools`), `platform`;
    images `ghcr.io/jajiz/coinpilot:${TAG}`.
  - `compose.sh <compose args>` — `docker compose` with `.env` and, when present,
    `release.env`.
  - `deploy.sh deploy <tag>` and `deploy.sh rollback`. Writes `release.env`
    (`TAG=<tag>`), appends to `releases` (one tag per line, newest last), and keeps the
    newest ten dumps in `backups/`.
  - Task 6 copies the three files there and runs `sudo /opt/coinpilot/deploy.sh …`.

Everything is relative to the directory the scripts sit in, so CI runs the very same
files in a temporary directory.

- [ ] **Step 1: Write `deploy/compose.yml`**

```yaml
# Production: what runs on the host (runbook: docs/operations.md). compose.sh supplies
# .env, which holds the secrets and never enters this repository, and release.env, which
# names the release (TAG) that deploy.sh last started.
name: coinpilot

x-database-url: &database-url postgresql+psycopg://coinpilot:${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set}@postgres:5432/coinpilot

services:
  postgres:
    image: postgres:18.6
    restart: unless-stopped
    environment:
      POSTGRES_USER: coinpilot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set}
      POSTGRES_DB: coinpilot
    volumes:
      # 18+ mounts the parent, not data/ (see docker-compose.dev.yml).
      - pgdata:/var/lib/postgresql
    # No port: only the containers of this project reach it.
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U coinpilot"]
      interval: 5s
      timeout: 5s
      retries: 10

  # Run by deploy.sh with the new image before the platform is recreated.
  migrate:
    image: ghcr.io/jajiz/coinpilot:${TAG:-none}
    profiles: [tools]
    command: ["alembic", "upgrade", "head"]
    environment:
      DATABASE_URL: *database-url
    depends_on:
      postgres:
        condition: service_healthy

  platform:
    image: ghcr.io/jajiz/coinpilot:${TAG:-none}
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: *database-url
    # Loopback only: reached through an SSH tunnel over IAP, never from the internet.
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    # Stopping waits for open requests (60 s, the Dockerfile) and then for a scheduler tick
    # under way, which can be between an order and its answer (spec §9.2). Docker's default
    # of 10 s would kill it there.
    stop_grace_period: 180s

volumes:
  pgdata:
```

`${TAG:-none}` lets `compose.sh` run commands on `postgres` before any release exists;
`none` is never pulled because nothing starts `platform` or `migrate` without a `TAG`.

- [ ] **Step 2: Write `deploy/compose.sh`**

```bash
#!/usr/bin/env bash
# docker compose for this host's platform, with its secrets (.env) and its current release
# (release.env). Everything after the script's name goes to docker compose:
#
#   compose.sh ps
#   compose.sh logs -f platform
#   compose.sh run --rm platform python scripts/rotate_master_key.py --check
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
args=(--project-directory "$here" -f "$here/compose.yml" --env-file "$here/.env")
if [[ -f "$here/release.env" ]]; then
  args+=(--env-file "$here/release.env")
fi
exec docker compose "${args[@]}" "$@"
```

- [ ] **Step 3: Write `deploy/deploy.sh`**

```bash
#!/usr/bin/env bash
# Deploys a release of the platform on this host, or goes back to the previous one.
#
#   deploy.sh deploy <tag>   dump the database, migrate, start <tag>, wait until healthy
#   deploy.sh rollback       start the release before the current one; no migration runs
#
# Lives next to compose.yml, compose.sh and .env (/opt/coinpilot in production). <tag> is
# the commit SHA the Release workflow built. A rollback is safe because every migration
# leaves the previous release working (docs/operations.md).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="$here/compose.sh"
releases="$here/releases"
backups="$here/backups"
repository="ghcr.io/jajiz/coinpilot"
keep_backups=10

fail() {
  echo "deploy: $*" >&2
  exit 1
}

# Starts <tag>, waits until Docker reports it healthy, and records it as the current release.
start() {
  local tag="$1"
  printf 'TAG=%s\n' "$tag" > "$here/release.env"
  if ! "$compose" up -d --wait --wait-timeout 240 platform; then
    "$compose" logs --tail 100 platform >&2 || true
    fail "release $tag did not become healthy; 'deploy.sh rollback' goes back"
  fi
  echo "$tag" >> "$releases"
  echo "deploy: release $tag is running"
}

# A custom-format dump of the whole database, before the migration touches it.
backup() {
  local tag="$1" file
  mkdir -p "$backups"
  file="$backups/$(date -u +%Y%m%dT%H%M%SZ)-before-$tag.dump"
  "$compose" exec -T postgres pg_dump -U coinpilot -Fc coinpilot > "$file.partial"
  mv "$file.partial" "$file"
  # Newest first; everything past the newest $keep_backups goes.
  find "$backups" -name '*.dump' -printf '%T@ %p\n' | sort -rn | tail -n +"$((keep_backups + 1))" \
    | cut -d' ' -f2- | xargs -r rm --
  echo "deploy: database saved to $file"
}

deploy() {
  local tag="$1" image
  [[ "$tag" =~ ^[A-Za-z0-9._-]+$ ]] || fail "'$tag' is not an image tag"
  image="$repository:$tag"
  # Tags are commit SHAs and never move: an image already here is the right one.
  docker image inspect "$image" > /dev/null 2>&1 || docker pull "$image"
  "$compose" up -d --wait postgres
  backup "$tag"
  # The new image migrates. TAG in the environment wins over release.env, which still
  # names the release that is running.
  TAG="$tag" "$compose" run --rm migrate
  start "$tag"
}

rollback() {
  [[ -f "$releases" && -f "$here/release.env" ]] || fail "no release has run here yet"
  local current last previous
  current="$(sed -n 's/^TAG=//p' "$here/release.env")"
  last="$(tail -n 1 "$releases")"
  if [[ "$current" != "$last" ]]; then
    # The last deploy never became healthy, so it was not recorded: go back to the last
    # release that did.
    previous="$last"
  else
    [[ $(wc -l < "$releases") -ge 2 ]] || fail "there is no previous release to go back to"
    previous="$(tail -n 2 "$releases" | head -n 1)"
  fi
  start "$previous"
}

case "${1:-}" in
  deploy)
    [[ $# -eq 2 ]] || fail "usage: deploy.sh deploy <tag>"
    deploy "$2"
    ;;
  rollback)
    [[ $# -eq 1 ]] || fail "usage: deploy.sh rollback"
    rollback
    ;;
  *)
    fail "usage: deploy.sh deploy <tag> | deploy.sh rollback"
    ;;
esac
```

A release is appended to `releases` only once it is healthy. So after a failed deploy,
`release.env` names a tag that `releases` does not end with, and a rollback goes to the
last healthy release, not the one before it. A rollback appends the release it started,
so a second rollback returns to the release the first one left. The runbook says so.

Make both scripts executable in git, which Windows does not record by itself:

```bash
git add deploy/compose.sh deploy/deploy.sh
git update-index --chmod=+x deploy/compose.sh deploy/deploy.sh
```

- [ ] **Step 4: Exercise it in CI**

Append these steps to the `image` job in `.github/workflows/ci.yml`, after "Imports the
application and the scripts":

```yaml
      - name: shellcheck
        run: shellcheck deploy/*.sh

      - name: Deploy, deploy again, roll back
        run: |
          home="$RUNNER_TEMP/coinpilot"
          mkdir -p "$home"
          cp deploy/compose.yml deploy/compose.sh deploy/deploy.sh "$home/"
          # Throwaway values, generated here and gone with the runner.
          {
            echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
            echo "JWT_SECRET=$(openssl rand -hex 32)"
            echo "CREDENTIAL_KEYS=1:$(openssl rand -base64 32)"
            echo "CREDENTIAL_KEY_VERSION=1"
            echo "GOOGLE_CLIENT_ID=ci"
            echo "GOOGLE_CLIENT_SECRET=ci"
            echo "GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google"
          } > "$home/.env"
          docker tag ghcr.io/jajiz/coinpilot:ci-1 ghcr.io/jajiz/coinpilot:ci-2

          "$home/deploy.sh" deploy ci-1
          curl -fsS http://127.0.0.1:8000/health
          "$home/deploy.sh" deploy ci-2
          test "$(tail -n 1 "$home/releases")" = ci-2
          "$home/deploy.sh" rollback
          test "$(tail -n 1 "$home/releases")" = ci-1
          curl -fsS http://127.0.0.1:8000/health
          test "$(ls "$home"/backups/*.dump | wc -l)" = 2
          "$home/compose.sh" run --rm platform python scripts/rotate_master_key.py --check

          # A deploy that never became healthy leaves release.env ahead of releases. The
          # rollback must return to the last healthy release (ci-1), not the one before (ci-2).
          echo "TAG=never-healthy" > "$home/release.env"
          "$home/deploy.sh" rollback
          test "$(tail -n 1 "$home/releases")" = ci-1
          curl -fsS http://127.0.0.1:8000/health

      - name: The platform's log, when something failed
        if: failure()
        run: docker compose -p coinpilot logs --tail 200
```

`git push` the branch and check the `image` job passes before committing anything
further on top. If `shellcheck` flags something, fix the script, not the check.

- [ ] **Step 5: Commit**

```bash
git add deploy/compose.yml deploy/compose.sh deploy/deploy.sh .github/workflows/ci.yml
git commit -m "feat(deploy): compose file and deploy script for the host, exercised in CI"
```

---

### Task 6: Release and deploy workflows

**Files:**
- Create: `.github/workflows/release.yml`, `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: the `Dockerfile` (Task 4); `deploy/compose.yml`, `deploy/compose.sh`,
  `deploy/deploy.sh` (Task 5); the CI workflow named `CI`.
- Produces: `ghcr.io/jajiz/coinpilot:<full sha>` for every green push to `main`; a
  dispatchable `Deploy` workflow with inputs `action` (`deploy`|`rollback`) and `tag`.
  It reads these variables from the GitHub environment `production` (Task 7 creates
  them): `GCP_PROJECT`, `GCP_ZONE`, `GCP_VM`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`.

Pin `google-github-actions/auth` and `google-github-actions/setup-gcloud` to their latest
release tags at the time of implementation, written in full (`@vX.Y.Z`), as
`actions/checkout@v7.0.1` is. Look them up on each action's GitHub releases page.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

```yaml
name: Release

# An image for every commit on main whose CI passed. Deploying it is a separate,
# deliberate step (deploy.yml).
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main]

permissions:
  contents: read
  packages: write

jobs:
  image:
    name: Build and push
    if: github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event == 'push'
    runs-on: ubuntu-latest

    env:
      IMAGE: ghcr.io/jajiz/coinpilot:${{ github.event.workflow_run.head_sha }}

    steps:
      - name: Checkout
        uses: actions/checkout@v7.0.1
        with:
          ref: ${{ github.event.workflow_run.head_sha }}

      - name: Log in to GHCR
        run: echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u "${{ github.actor }}" --password-stdin

      - name: Build
        run: docker build -t "$IMAGE" .

      - name: Push
        run: docker push "$IMAGE"
```

- [ ] **Step 2: Write `.github/workflows/deploy.yml`**

```yaml
name: Deploy

# Run by hand: Actions → Deploy → Run workflow. A deploy names the full commit SHA of an
# image the Release workflow built; a rollback names nothing and starts the release
# before the current one (runbook: docs/operations.md).
on:
  workflow_dispatch:
    inputs:
      action:
        description: deploy or rollback
        type: choice
        options: [deploy, rollback]
        default: deploy
      tag:
        description: Full commit SHA to deploy (ignored by a rollback)
        type: string
        required: false

# One at a time, and never cancelled halfway.
concurrency:
  group: deploy
  cancel-in-progress: false

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    name: ${{ inputs.action }}
    runs-on: ubuntu-latest
    environment: production

    env:
      ACTION: ${{ inputs.action }}
      TAG: ${{ inputs.tag }}
      VM: ${{ vars.GCP_VM }}
      ZONE: ${{ vars.GCP_ZONE }}

    steps:
      - name: Check the tag
        if: inputs.action == 'deploy'
        run: |
          [[ "$TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "tag must be a full commit SHA"; exit 1; }
          docker manifest inspect "ghcr.io/jajiz/coinpilot:$TAG" > /dev/null

      - name: Checkout
        uses: actions/checkout@v7.0.1

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@vX.Y.Z  # pin: latest release
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOY_SA }}

      - name: Set up gcloud
        uses: google-github-actions/setup-gcloud@vX.Y.Z  # pin: latest release
        with:
          project_id: ${{ vars.GCP_PROJECT }}

      - name: Copy the deploy files
        run: |
          ssh_flags=(--zone "$ZONE" --tunnel-through-iap --ssh-key-expire-after=30m --quiet)
          gcloud compute ssh "$VM" "${ssh_flags[@]}" --command "mkdir -p ~/coinpilot-deploy"
          gcloud compute scp deploy/compose.yml deploy/compose.sh deploy/deploy.sh \
            "$VM:~/coinpilot-deploy/" --zone "$ZONE" --tunnel-through-iap --quiet
          gcloud compute ssh "$VM" "${ssh_flags[@]}" --command \
            "sudo install -m 0644 ~/coinpilot-deploy/compose.yml /opt/coinpilot/ && sudo install -m 0755 ~/coinpilot-deploy/compose.sh ~/coinpilot-deploy/deploy.sh /opt/coinpilot/"

      - name: Run it on the host
        run: |
          if [[ "$ACTION" == deploy ]]; then command="sudo /opt/coinpilot/deploy.sh deploy $TAG"; else command="sudo /opt/coinpilot/deploy.sh rollback"; fi
          gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap --ssh-key-expire-after=30m --quiet --command "$command"
```

The `vX.Y.Z` above is the one value the implementer fills in, from the releases page; it
is not left in the committed file. `$TAG` reaches the remote command only after the
first step proved it is 40 hex characters.

The `scp` and `install` steps copy `main`'s deploy files even for a rollback. That is
deliberate: the deploy files change rarely, and `compose.yml` must stay compatible with
the previous image anyway (it names no version-specific setting).

- [ ] **Step 3: Validate the YAML**

```bash
.venv/Scripts/pre-commit run check-yaml --files .github/workflows/release.yml .github/workflows/deploy.yml
```

Expected: Passed. The workflows run for real in the manual check: Release after the
merge, Deploy once the VM exists.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/deploy.yml
git commit -m "ci: release an image for every green commit on main, and deploy one by hand"
```

---

### Task 7: The host, and the runbook

**Files:**
- Create: `deploy/bootstrap.sh`, `deploy/env.production.example`, `docs/operations.md`

**Interfaces:**
- Consumes: everything in `deploy/` (Task 5), the workflows (Task 6), the rotation
  script (Task 3).
- Produces: the runbook every later operation follows; the GitHub environment variables
  Task 6 reads.

- [ ] **Step 1: Write `deploy/bootstrap.sh`**

```bash
#!/usr/bin/env bash
# Prepares a fresh Debian 13 VM for the platform. Run once, as root:
#
#   sudo bash bootstrap.sh
#
# Installs Docker from Docker's own repository (Debian's lags behind, and deploy.sh needs
# Compose v2's `up --wait`), turns on unattended security upgrades, rotates container logs,
# and creates /opt/coinpilot. It opens no port.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "bootstrap: run as root" >&2; exit 1; }

apt-get update
apt-get install -y ca-certificates curl unattended-upgrades

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck source=/dev/null
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Every container's log is kept, but bounded: 5 files of 10 MB.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "local",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
systemctl restart docker
systemctl enable --now docker unattended-upgrades

install -d -m 0750 /opt/coinpilot /opt/coinpilot/backups
echo "bootstrap: done. Next: write /opt/coinpilot/.env (docs/operations.md, section 3)."
```

```bash
git add deploy/bootstrap.sh
git update-index --chmod=+x deploy/bootstrap.sh
```

- [ ] **Step 2: Write `deploy/env.production.example`**

```bash
# The production .env: /opt/coinpilot/.env, mode 0600, owned by root.
# Generate every secret ON THE HOST with the command beside it. None of them is ever
# typed into a chat, a ticket or this repository.

# python3 -c "import secrets; print(secrets.token_hex(24))"
POSTGRES_PASSWORD=

# python3 -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=
JWT_TTL_MINUTES=15
REFRESH_TTL_DAYS=30
# The API is reached as http://localhost:8000 through the tunnel. Browsers treat
# localhost as a secure origin, so secure cookies work there.
COOKIE_SECURE=true

# The same Google OAuth client as development: its redirect URI is already this one.
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback/google

# python3 -c "import os, base64; print('1:' + base64.b64encode(os.urandom(32)).decode())"
# Back it up in your password manager BEFORE the first credential is stored.
CREDENTIAL_KEYS=
CREDENTIAL_KEY_VERSION=1

SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=60
SCHEDULER_BATCH=50
SCHEDULER_WORKERS=4
SCHEDULER_MIN_CADENCE_MINUTES=15
SCHEDULER_WINDOW_SECONDS=3600
SCHEDULER_ALERT_STREAK=3
SESSIONS_RETENTION_DAYS=90
```

Its name does not match `.gitignore`'s `.env.*`; check with
`git check-ignore deploy/env.production.example` (expected: no output).

- [ ] **Step 3: Write `docs/operations.md`**

Write the runbook with exactly these sections and commands. Shell variables stand for
everything the repository must not hold; the operator sets them once per shell:

```bash
PROJECT=...   # the Google Cloud project id
REGION=...    # e.g. europe-southwest1
ZONE=...      # e.g. europe-southwest1-a
VM=coinpilot
```

**1. What runs where.** One `e2-small` Debian 13 VM in Google Cloud. Docker runs
`postgres` and `platform` from `/opt/coinpilot/compose.yml`. No port is open to the
internet: SSH arrives through IAP, and the API listens on the VM's loopback. Images are
`ghcr.io/jajiz/coinpilot:<sha>`. Files in `/opt/coinpilot`: `.env` (secrets),
`release.env` (current tag), `releases` (history), `backups/`, and the three files from
`deploy/`.

**2. Provisioning (once).**

```bash
gcloud config set project "$PROJECT"
gcloud services enable compute.googleapis.com iap.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

# A static address, so the Kraken key can be restricted to it. Skip if it is reserved
# already; it must be in $REGION.
gcloud compute addresses create "$VM" --region "$REGION"

gcloud compute instances create "$VM" --zone "$ZONE" \
  --machine-type e2-small \
  --image-family debian-13 --image-project debian-cloud \
  --boot-disk-size 20GB --boot-disk-type pd-balanced   --address "$VM" \
\
  --metadata enable-oslogin=TRUE \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --no-service-account --no-scopes

# SSH from IAP only. The default network admits SSH and RDP from anywhere.
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --quiet
gcloud compute firewall-rules create allow-ssh-from-iap --network default \
  --direction INGRESS --allow tcp:22 --source-ranges 35.235.240.0/20
gcloud compute firewall-rules list   # expect: allow-ssh-from-iap, default-allow-icmp, default-allow-internal

# 14 daily snapshots of the disk, kept off the VM.
gcloud compute resource-policies create snapshot-schedule "$VM-daily" --region "$REGION" \
  --daily-schedule --start-time 03:00 --max-retention-days 14 \
  --on-source-disk-delete keep-auto-snapshots
gcloud compute disks add-resource-policies "$VM" --zone "$ZONE" --resource-policies "$VM-daily"

# Then, on the VM:
gcloud compute scp deploy/bootstrap.sh "$VM:~/" --zone "$ZONE" --tunnel-through-iap
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap --command "sudo bash ~/bootstrap.sh"
```

The pipeline's identity (Workload Identity Federation; no key file exists):

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
SA="coinpilot-deploy@$PROJECT.iam.gserviceaccount.com"

gcloud iam service-accounts create coinpilot-deploy --display-name "CoinPilot deploy"
gcloud iam workload-identity-pools create github --location global
gcloud iam workload-identity-pools providers create-oidc coinpilot --location global \
  --workload-identity-pool github \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" \
  --attribute-condition "assertion.repository == 'jAjiz/coinpilot' && assertion.environment == 'production'"
gcloud iam service-accounts add-iam-policy-binding "$SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/jAjiz/coinpilot"

gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/iap.tunnelResourceAccessor
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/compute.viewer
gcloud compute instances add-iam-policy-binding "$VM" --zone "$ZONE" --member "serviceAccount:$SA" --role roles/compute.osAdminLogin
```

In GitHub: Settings → Environments → New environment `production`; "Deployment
branches": `main` only. Add the variables `GCP_PROJECT`, `GCP_ZONE`, `GCP_VM`,
`GCP_DEPLOY_SA` (`$SA`) and `GCP_WIF_PROVIDER`:
`projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/coinpilot`.

After the first Release run: GitHub → Packages → `coinpilot` → Package settings →
Change visibility → Public. Check from any machine, with no login:
`docker pull ghcr.io/jajiz/coinpilot:<sha>`.

**3. Secrets.** On the VM: `sudo install -m 0600 /dev/null /opt/coinpilot/.env`, then
fill it from `deploy/env.production.example` with `sudo nano /opt/coinpilot/.env`,
generating each secret on the VM with the command beside it. Copy `CREDENTIAL_KEYS`
into your password manager before any credential is stored: if it is lost, every stored
Kraken key is unreadable, and the only remedy is for each user to register theirs again.

**4. Reaching the API.**

```bash
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap -- -N -L 8000:localhost:8000
```

Leave it open; the API is at `http://localhost:8000` (`/docs`, and sign in at
`/auth/login/google`). Stop the local development API first: it would hold port 8000,
and two schedulers on the same Kraken account would both invest.

**5. Deploy.** GitHub → Actions → Deploy → Run workflow → `deploy`, with the full SHA
of a commit on `main` whose Release run succeeded. On the VM, by hand:
`sudo /opt/coinpilot/deploy.sh deploy <sha>`. It dumps the database to `backups/`,
migrates with the new image, recreates the platform and waits up to four minutes for it
to report healthy. If it does not, the step fails with the platform's last 100 log lines,
and nothing else changes: roll back.

Sections 6 to 9 run on the VM in a root shell, because `.env` and `backups/` are
root's: `sudo -i`, then `cd /opt/coinpilot`. The runbook says this once, before
section 6.

**6. Rollback.** Actions → Deploy → `rollback`, or `./deploy.sh
rollback`. It starts the release before the current one, with no migration. Rolling back
twice returns to where you started. It is safe because every migration is additive (a
new column is nullable or has a default; nothing is renamed or dropped in the release
that stops using it). A release that broke that rule is undone with the dump taken
before it:

```bash
cd /opt/coinpilot
./compose.sh stop platform
./compose.sh exec -T postgres pg_restore -U coinpilot -d coinpilot --clean --if-exists < backups/<dump>
./deploy.sh rollback
```

**7. Rotating the master key.** Rotate when the key may have been exposed, and when
someone who knew it no longer should.

1. On the VM, generate the new key (command in `env.production.example`) with the next
   version number, and save it in your password manager.
2. In `.env`: `CREDENTIAL_KEYS=1:<old>,2:<new>` and `CREDENTIAL_KEY_VERSION=2`.
3. `./compose.sh up -d --wait --force-recreate platform` — new credentials are
   now sealed with version 2, and the old ones still open.
4. `./compose.sh run --rm platform python scripts/rotate_master_key.py` — expect
   `unreadable : 0`, exit 0.
5. `./compose.sh run --rm platform python scripts/rotate_master_key.py --check` —
   expect `not under it : 0`.
6. Remove `1:<old>,` from `CREDENTIAL_KEYS`, and recreate the platform again as in 3.
7. `GET /portfolio` through the tunnel reads your balance: the record opens with the new
   key alone. Only now delete the old key from your password manager. Dumps taken before
   step 4 still need it; keep it while `backups/` and the snapshots hold one.

**8. Backups and restore.** Each deploy leaves a dump in `/opt/coinpilot/backups/`
(newest ten). The disk is snapshotted daily, 14 kept. To take a dump by hand:
`./compose.sh exec -T postgres pg_dump -U coinpilot -Fc coinpilot > backups/manual.dump`.
To restore one, see section 6. To restore a whole snapshot, create a disk from it and a
new VM on it (Compute Engine → Snapshots → Create disk).

**9. Logs.** `./compose.sh logs -f --since 1h platform`. A user whose scheduled
operations keep failing appears once, as
`WARNING coinpilot.scheduler: user <id>: 3 scheduled operations in a row have failed`:
`./compose.sh logs platform | grep WARNING`.

**10. Restricting the Kraken key to the VM.** In Kraken → API → the key → "IP address
allowlist": the static address (`gcloud compute addresses describe "$VM" --region
"$REGION" --format 'value(address)'`). The key then works from the VM alone; your local
`scripts/check_key.py` will be refused, which is the point.

- [ ] **Step 4: Run shellcheck**

If `shellcheck` is installed locally, `shellcheck deploy/*.sh`; otherwise push and read
the CI `image` job, which runs it on every file in `deploy/`.
Expected: no warnings.

- [ ] **Step 5: Commit**

```bash
git add deploy/bootstrap.sh deploy/env.production.example docs/operations.md
git commit -m "docs(operations): the runbook, the production env template and the VM bootstrap"
```

---

### Task 8: The spec and the README describe what was built

**Files:**
- Modify: `docs/specs/2026-09-17-platform-design.md`, `README.md`

- [ ] **Step 1: Spec status line**

Replace `**Status:** approved; phases 1 to 4 implemented` with
`**Status:** approved; phases 1 to 8 implemented`.

- [ ] **Step 2: Rewrite §13**

Replace the whole body of `## 13. Deployment and operations` with:

```markdown
One Google Cloud VM, `e2-small`, Debian 13, running two containers from one compose
file: `postgres` and `platform`. No port is open to the internet. SSH arrives only
through Identity-Aware Proxy, with OS Login, and the API is published on the VM's
loopback; the operator reaches it through an SSH tunnel, so the OAuth callback stays
`http://localhost:8000`. How the API is exposed beyond that is project 2 (§16). The
runbook is [`docs/operations.md`](../operations.md).

**Releases.** Every commit on `main` whose CI passed is built into
`ghcr.io/jajiz/coinpilot:<sha>`. Tags never move. A deploy is dispatched by hand: the
workflow authenticates to Google Cloud with Workload Identity Federation, so no key file
exists, and runs `deploy.sh` on the VM. It dumps the database, migrates with the new
image, recreates the platform and waits for its health check. A rollback starts the
previous image and runs no migration, which is safe because **every migration leaves the
previous release working**: additive only.

**Stopping waits for the tick.** The platform's stop grace period is longer than a tick,
so a deploy never cuts an evaluation between an order and its answer (§9.2).

**The master encryption key** lives in the VM's `.env` and in the operator's password
manager, outside Google Cloud. If it is lost, every stored credential is unrecoverable.
Rotation re-seals every record under the new key, one transaction and one row lock each,
and only then is the old key removed.

**Backups.** A dump before every deploy, on the VM, and 14 daily disk snapshots off it.

**Logs** stay in Docker, bounded per container. The failure-streak warning is read there
until project 2 brings notifications.
```

- [ ] **Step 3: §15, one accepted risk**

Append to the list in `## 15. Accepted risks and deferred decisions`:

```markdown
- **Nothing watches the service.** Docker restarts a platform that dies, but no uptime
  check or notification tells anyone that it stopped, or that a user's operations keep
  failing. The log holds both. Project 2 brings notifications.
```

- [ ] **Step 4: README**

Replace the status block with:

```markdown
> **Status:** project 1 complete. The platform runs in production: free cash is invested,
> and drift is looked for, on each user's cadence; a rebalance is proposed, or executed
> when the user turned automatic rebalancing on. Everything also runs on request through
> the REST API. The application that consumes it is project 2.
```

Add, after "Running it locally":

```markdown
## Production

One Google Cloud VM with no port open to the internet, two containers, and a deploy that
is dispatched by hand. Provisioning, secrets, deploy, rollback, master-key rotation and
backups are in [`docs/operations.md`](docs/operations.md).
```

- [ ] **Step 5: Run the whole gate**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests --cov-fail-under=80
```

Expected: each passes.

- [ ] **Step 6: Commit**

```bash
git add docs/specs/2026-09-17-platform-design.md README.md
git commit -m "docs: the spec and the README describe the deployment"
```

---

## What you verify before calling project 1 done

The roadmap's check: deploy, roll back, and rotate the master key. Production starts
from an empty database; the development database stays where it is.

### 1. Merge, and let Release build

Merge the PR. Actions → Release runs after CI and pushes
`ghcr.io/jajiz/coinpilot:<merge sha>`. Make the package public (runbook §2) and pull it
from your machine with no login.

### 2. Provision

Runbook §2 and §3. Then, from outside Google Cloud (your own machine is fine):

```bash
nc -vz -w 5 <static ip> 22
nc -vz -w 5 <static ip> 8000
```

Both must time out. `gcloud compute ssh … --tunnel-through-iap` must work.

### 3. First deploy, from zero

1. **Stop the local API** and leave it stopped while production runs. Two schedulers on
   one Kraken account would both invest.
2. Actions → Deploy → `deploy`, with the merge SHA. The migration builds the schema in
   the empty database.
3. Open the tunnel (runbook §4), sign in at `/auth/login/google`, and set yourself up as
   you did in development: `POST /credentials` with your Kraken key, `PUT /assets/…` for
   each target, `PATCH /config`. Start with `invest_cash_enabled` and
   `auto_rebalance_enabled` off, as in phase 7.
4. `GET /portfolio` reads your balance. Within 15 minutes `GET /sessions` shows a
   `PROPOSE` / `SCHEDULER` row.

### 4. Rotate the master key

Runbook §7 in full, from version 1 to version 2. After step 4 the script reports
`resealed : 1`; after step 6 `GET /portfolio` still reads your balance with version 1
gone from `.env`.

### 5. Deploy, and roll back

1. Merge anything small (this plan's departures, for example) so Release builds a second
   image. Deploy it.
2. On the VM: `cat /opt/coinpilot/releases` lists both SHAs; `ls backups/` holds a dump
   for each deploy.
3. Actions → Deploy → `rollback`. `releases` ends with the first SHA, `/health` answers,
   and `GET /sessions` keeps gaining rows.
4. Deploy the second SHA again.

### 6. Survive a reboot

`sudo reboot` on the VM. After a minute, through a new tunnel, `/health` answers and
the scheduler's next row arrives on time.

### 7. Close the remaining doors

- Restrict the Kraken key to the static IP (runbook §10). `GET /portfolio` still works
  from production.
- Delete the real key from the development database, so it lives only in production:
  `docker compose -f docker-compose.dev.yml exec postgres psql -U coinpilot -c "delete from user_credentials"`.
- The production master key (version 2) is in your password manager. Delete version 1
  from it once no dump in `backups/` and no snapshot was taken before the rotation
  (14 days at most).

### 8. Report

Report what each step showed. Anything that differs goes into the departures below and,
where it is a fact about the platform, into the spec.

---

## Departures taken during execution

The code blocks above are the plan as written. Where the repository differs, trust the
repository.

| Where | What changed | Why |
|---|---|---|
