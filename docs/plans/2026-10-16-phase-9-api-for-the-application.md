# Phase 9 — The platform, ready for the application

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The platform answers under `/api`, ends a Google sign-in on a page instead of a
JSON body, records when onboarding finished, returns typed holdings, and serves the
application's files from the same origin when a build is present.

**Architecture:** Every router is mounted under the `/api` prefix in `create_app`, and
the OpenAPI document and docs move with it. The OAuth callback sets the same cookies as
today and answers `302`. `onboarded_at` is one nullable column, set through
`PATCH /api/config` with `"onboarded": true`. `PortfolioOut` flattens the snapshot's
JSON into a list of `HoldingOut`. A new module, `api/web.py`, mounts the application's
build (`web/dist/`) behind every route of the API; `create_app` takes the directory as a
parameter, so tests point it at a temporary build and production at `/app/web/dist`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic. No new dependency.

**Spec:** [`docs/specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md) — §2.1, §3 (and §2.5 for the
development redirect URI, which phase 10 changes)

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md) — phase 9, the first of project 2

## Global Constraints

- **Python 3.13**, no new dependency.
- **A migration must leave the previous release working.** The new column is nullable.
- **No test reads configuration from the environment**, touches the network, or places a
  real order. Integration tests run inside a rolled-back transaction.
- **Coverage gate is 80 %**; **`ruff check` and `ruff format --check` pass**; lines are 110
  characters.
- **No secret, host name or IP address in the repository.**
- Commit messages follow Conventional Commits and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Test command (PostgreSQL from `docker-compose.dev.yml` running):

```bash
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests
```

## Review Focus

1. **An unknown `/api` path is a JSON `404`, never the application's `index.html`.** A
   client that calls a removed route must see an error, not HTML it cannot parse. That
   holds for `/api` itself, without the slash, and for every method, not only `GET`.
   → Task 5.
2. **No file outside the build is ever served.** `/../alembic.ini` and its encoded forms
   resolve outside `web/dist/` and get `index.html`, not the file. → Task 5.
3. **A failed sign-in never leaves a half-signed-in browser.** Every refusal of the
   callback, a disabled account included, removes the login cookie and sets no session
   cookie. → Task 2.
4. **`"onboarded": true` never moves a time already set**, and never reschedules the
   scheduler's next runs. → Task 3.
5. **A snapshot written before this phase still reads.** A `holdings` JSON with no
   `cash_target_pct` gives `null`, not a 500. → Task 4.
6. **The order of `holdings` is the API's, not the database's.** The column is JSONB,
   which keeps no key order, so `_out` sorts the list itself. → Task 4.

**Rolling back past this release** needs `GOOGLE_REDIRECT_URI` set back to the path
without `/api`: the previous image has no `/api` route. The Google client keeps both URIs
registered, so only `.env` changes. Task 6 writes this into the runbook.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/app.py` | `create_app(context, web_dist=None)`: routers under `/api`, docs under `/api` |
| `api/routes/auth.py` | Cookie paths under `/api/auth`; the callback redirects |
| `api/web.py` | `mount_application(app, dist)`: the `/api` 404, static files, `index.html` fallback, headers |
| `api/main.py` | Passes `web/dist` when it holds an `index.html` |
| `api/schemas.py` | `HoldingOut`; `PortfolioOut` typed; `ConfigOut.onboarded_at`; `ConfigPatch.onboarded` |
| `api/routes/config.py` | Applies `onboarded` |
| `api/routes/portfolio.py` | Builds `PortfolioOut` from a snapshot's JSON |
| `core/db/models.py`, `core/db/settings.py` | `UserSettings.onboarded_at`, updatable |
| `scripts/migrations/versions/<rev>_onboarded_at.py` | The column, after `c7a4e2d91f3b` |
| `Dockerfile`, `.github/workflows/ci.yml` | The health check at `/api/health`; CI's redirect URI |
| `.env.example`, `deploy/env.production.example`, `README.md`, `docs/operations.md`, `docs/specs/2026-09-17-platform-design.md` | Paths under `/api` |
| `tests/…` | Every request path gains `/api` |

---

### Task 1: Everything under `/api`

**Files:**
- Modify: `api/app.py`, `api/routes/auth.py:31-35`, `Dockerfile` (`HEALTHCHECK`), `.github/workflows/ci.yml` (lines 94, 99, 104, 113)
- Modify: every request path in `tests/integration/test_api_*.py` and `tests/unit/api/test_database_errors.py`
- Modify: the error messages that name a route: `api/routes/assets.py:60`,
  `api/routes/config.py:46,60`, `api/routes/portfolio.py:36,44,47`, `core/execution.py:275,278`
- Create: `tests/integration/test_api_prefix.py`

**Interfaces:**
- Produces: `API_PREFIX = "/api"` in `api/app.py`. Every route of project 1 at `/api/<its path>`;
  `/api/docs`, `/api/openapi.json`, no ReDoc. `LOGIN_COOKIE_PATH = "/api/auth/callback"`,
  `REFRESH_COOKIE_PATH = "/api/auth"`.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_api_prefix.py`:

```python
def test_health_answers_under_the_prefix(api):
    assert api.get("/api/health").json() == {"status": "ok"}

def test_nothing_answers_at_the_old_paths(api):
    assert api.get("/health").status_code == 404
    assert api.get("/auth/login/google", follow_redirects=False).status_code == 404

def test_the_openapi_document_moves_with_the_api(api):
    paths = api.get("/api/openapi.json").json()["paths"]
    assert "/api/portfolio" in paths and "/portfolio" not in paths
    assert api.get("/api/docs").status_code == 200

def test_the_login_cookie_is_scoped_to_the_callback(api):
    response = api.get("/api/auth/login/google", follow_redirects=False)
    assert "Path=/api/auth/callback" in response.headers["set-cookie"]
```

- [ ] **Step 2: Run them**: `… -m pytest tests/integration/test_api_prefix.py -v`. Expected: 4 FAIL.

- [ ] **Step 3: Implement.** `FastAPI(..., docs_url="/api/docs", openapi_url="/api/openapi.json",
  redoc_url=None)`; `app.include_router(router, prefix=API_PREFIX)` for each router. Change the
  two cookie-path constants. `HEALTHCHECK` and CI's three `curl`s call `/api/health`; CI's
  `GOOGLE_REDIRECT_URI` becomes `http://localhost:8000/api/auth/callback/google`. The error
  messages listed above name the route with its prefix (`"choose a fiat with PATCH /api/config
  first"`): the application shows a refusal verbatim (application spec §5.1), and a path
  without `/api` is one that answers `404`. No test asserts these messages today.

- [ ] **Step 4: Rewrite the existing tests' paths.** Prefix every request path string with
  `/api` in the files listed (`api.get("/config"` → `api.get("/api/config"`, and so on for
  `get`, `post`, `put`, `patch`, `delete`). The `redirect_uri` in `tests/integration/conftest.py`
  becomes `http://testserver/api/auth/callback/google`. No assertion changes in this step.

- [ ] **Step 5: Run the whole suite.** Expected: all pass, the four new tests included.

- [ ] **Step 6: Commit** — `feat(api): every route answers under /api`

### Task 2: The callback ends on a page

**Files:**
- Modify: `api/routes/auth.py` (`_signed_in`, `callback`)
- Modify: `tests/integration/test_api_auth.py`

**Interfaces:**
- Produces: `GET /api/auth/callback/google` answers `302`. Success: `Location: /`, the access
  and refresh cookies set exactly as today, the login cookie removed. Refusal:
  `Location: /login?error=<reason, URL-encoded>`, where `reason` is the message the route raises
  today (`START_AGAIN`, `"google did not grant the login"`, Google's refusal,
  `"this account is disabled"`, …); the login cookie removed, no session cookie set.
  `POST /api/auth/refresh` is unchanged and still returns `TokenPairOut`.
- Produces: `_set_session(response, context, user_id, refresh) -> None` in `auth.py`, used by
  the callback (on a `RedirectResponse`) and by `refresh` (on its `JSONResponse`).

- [ ] **Step 1: Change the tests.** `_sign_in` asserts the redirect and returns the cookies:

```python
def _sign_in(api):
    response = _finish_login(api, _start_login(api))  # with follow_redirects=False
    assert response.status_code == 302 and response.headers["location"] == "/"
    return {"access_token": api.cookies["coinpilot_token"], "refresh_token": api.cookies["coinpilot_refresh"]}
```

  `test_a_completed_login_creates_the_user_and_returns_both_tokens` becomes
  `…_and_sets_both_cookies` and drops its body assertions. Each refusal test asserts
  `status_code == 302`, `location.startswith("/login?error=")`, the decoded reason, and that
  `api.cookies` holds neither `coinpilot_token` nor `coinpilot_refresh` nor `coinpilot_login`.
  `test_a_disabled_user_cannot_sign_in_again` asserts
  `location == "/login?error=this%20account%20is%20disabled"`.

- [ ] **Step 2: Run** `tests/integration/test_api_auth.py`. Expected: the changed tests FAIL.

- [ ] **Step 3: Implement.** Split `_signed_in` into `_set_session` plus the JSON body
  `refresh` keeps. In `callback`, each refusal returns `_login_refused(reason)`: a
  `RedirectResponse(f"/login?error={quote(reason)}", 302)` that deletes the login cookie.
  The `403` for a disabled account becomes the same redirect. Remove `response_model` from the
  callback's decorator. Every refusal happens before a row is written (the user is created
  only after Google answers, and a disabled user already exists), so returning a redirect
  instead of raising commits nothing new.

- [ ] **Step 4: Run the suite.** Expected: all pass.

- [ ] **Step 5: Commit** — `feat(auth): the Google callback redirects to the application`

### Task 3: `onboarded_at`

**Files:**
- Create: `scripts/migrations/versions/<rev>_onboarded_at.py` (`down_revision = "c7a4e2d91f3b"`)
- Modify: `core/db/models.py` (`UserSettings`), `core/db/settings.py` (`_UPDATABLE`),
  `api/schemas.py` (`ConfigOut`, `ConfigPatch`), `api/routes/config.py`
- Test: `tests/integration/test_api_config.py`, `tests/integration/test_schema.py`

**Interfaces:**
- Produces: `UserSettings.onboarded_at: Mapped[datetime | None]` (`DateTime(timezone=True)`,
  nullable, no default). `ConfigOut.onboarded_at: datetime | None`.
  `ConfigPatch.onboarded: Literal[True] | None = None`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_onboarding_is_not_finished_on_a_new_user(api, make_user, login):
    body = api.patch("/api/config", json={"fiat": "EUR"}, headers=login(make_user())).json()
    assert body["onboarded_at"] is None

def test_onboarded_records_the_time_once(api, make_user, login):
    headers = login(make_user())
    api.patch("/api/config", json={"fiat": "EUR"}, headers=headers)
    first = api.patch("/api/config", json={"onboarded": True}, headers=headers).json()
    assert first["onboarded_at"].startswith("2026-09-29T12:00:00")  # FIXED_NOW in conftest
    again = api.patch("/api/config", json={"onboarded": True}, headers=headers).json()
    assert again["onboarded_at"] == first["onboarded_at"]

def test_onboarded_false_is_refused(api, make_user, login): ...  # 422

def test_onboarded_does_not_move_the_next_runs(api, make_user, login): ...
    # an INTERVAL cadence set first; next_invest_at and next_rebalance_at equal before and after

def test_the_onboarded_at_column_exists(db_session): ...  # in test_schema.py
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** The migration adds `user_settings.onboarded_at`
  (`sa.DateTime(timezone=True)`, nullable) and drops it on downgrade. Add `"onboarded_at"`
  to `_UPDATABLE`. In `patch_config`, `onboarded = changes.pop("onboarded", None)` before
  `_merged`, so it reaches neither the cadence check nor `rescheduled`; after the update,
  when `onboarded` and `settings.onboarded_at is None`, set it to `context.now()`.

- [ ] **Step 4: Run the suite.** Expected: all pass.

- [ ] **Step 5: Commit** — `feat(config): record when onboarding finished`

### Task 4: Typed holdings

**Files:**
- Modify: `api/schemas.py` (`HoldingOut`, `PortfolioOut`), `api/routes/portfolio.py` (`_out`)
- Test: `tests/integration/test_api_portfolio.py`

**Interfaces:**
- Produces:

```python
class HoldingOut(BaseModel):
    asset: str
    amount: str | None
    price: str | None
    value: str | None
    managed: bool
    locked: bool
    target_pct: str | None
    weight_pct: str | None

class PortfolioOut(BaseModel):
    as_of: datetime
    fiat: str
    total_value: str          # managed assets + cash, as today
    cash: str
    cash_target_pct: str | None
    cash_weight_pct: str | None
    holdings: list[HoldingOut]  # managed first, then unmanaged, then locked; by asset within each
```

  The snapshot's stored JSON is unchanged; only the response is reshaped. The order is
  set by `_out`, not read from the snapshot: `holdings` is JSONB, and PostgreSQL stores an
  object's keys in its own order (shorter keys first), not in the order they were written.

- [ ] **Step 1: Change the tests.** Assertions that read `body["holdings"]["assets"][name]`
  read the element of `body["holdings"]` whose `asset == name`; `cash_target_pct` and
  `cash_weight_pct` move to the top level. Add:

```python
def test_a_snapshot_without_cash_percentages_still_reads(api, db_session, make_user, login):
    # keep_snapshot(...) with holdings={"assets": {"BTC": {...}}} and no cash keys
    body = api.get("/api/portfolio", headers=login(user)).json()
    assert body["cash_target_pct"] is None and body["holdings"][0]["asset"] == "BTC"

def test_holdings_are_listed_managed_then_unmanaged_then_locked(api, db_session, make_user, login):
    # keep_snapshot(...) with assets written in the order DOT.S (locked), XRP (unmanaged),
    # SOL (managed), BTC (managed): the order JSONB would not keep
    body = api.get("/api/portfolio", headers=login(user)).json()
    assert [h["asset"] for h in body["holdings"]] == ["BTC", "SOL", "XRP", "DOT.S"]
```

- [ ] **Step 2: Run** `tests/integration/test_api_portfolio.py`. Expected: FAIL.

- [ ] **Step 3: Implement `_out`** with `.get()` on the two cash keys and on `assets`. Sort the
  list by `(locked, not managed, asset)`.

- [ ] **Step 4: Run the suite.** Expected: all pass.

- [ ] **Step 5: Commit** — `feat(portfolio): holdings are a typed list`

### Task 5: Serve the application

**Files:**
- Create: `api/web.py`, `tests/unit/api/test_web.py`
- Modify: `api/app.py` (`create_app`), `api/main.py` (`build`)

**Interfaces:**
- Produces: `mount_application(app: FastAPI, dist: Path) -> None` and
  `file_in_build(dist: Path, path: str) -> Path | None` in `api/web.py`, and
  `create_app(context: AppContext, web_dist: Path | None = None) -> FastAPI`, which calls it
  after every router when `web_dist` is given. `build()` passes
  `Path(__file__).resolve().parents[1] / "web" / "dist"` when that directory holds an
  `index.html`, and `None` otherwise.
- Produces, the headers: `CACHE_IMMUTABLE = "public, max-age=31536000, immutable"` for files
  under `dist/assets/`; `CACHE_NONE = "no-cache"` for every other file and for `index.html`;
  and on every response of the application (not of the API):

```python
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
```

  Scripts stay same-origin only. Styles allow `'unsafe-inline'` because shadcn/ui's Radix
  primitives (the scroll lock of a dialog or a sheet) and its toasts insert `<style>`
  elements at run time, which `style-src 'self'` would refuse. A nonce would need the
  platform to rewrite `index.html` on every request; an injected style cannot run code, so
  the gain does not pay for it.

- [ ] **Step 1: Write the failing tests** in `tests/unit/api/test_web.py`, with a fixture that
  writes `index.html` (`<html>app</html>`), `assets/index-abc.js` and `sw.js` into
  `tmp_path` and builds the app with a context like `test_database_errors._api` uses
  (extract that builder into `tests/unit/api/conftest.py` as `make_context()` and use it in
  both files):

```python
def test_a_deep_link_gets_the_application(web):
    response = web.get("/settings")
    assert response.text == "<html>app</html>" and response.headers["cache-control"] == "no-cache"

def test_a_hashed_asset_is_cached_for_a_year(web):
    assert web.get("/assets/index-abc.js").headers["cache-control"] == CACHE_IMMUTABLE

def test_an_unhashed_file_is_not_cached(web):
    assert web.get("/sw.js").headers["cache-control"] == "no-cache"

def test_the_application_carries_the_security_policy(web):
    assert web.get("/").headers["content-security-policy"] == CONTENT_SECURITY_POLICY

@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/api", "/api/", "/api/nothing-here"])
def test_an_unknown_api_path_is_a_json_404(web, method, path):
    response = web.request(method, path)
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}

def test_the_api_keeps_answering(web):
    assert web.get("/api/health").json() == {"status": "ok"}

# The client normalises `..` before it sends a request, so the guard is tested on the
# function that applies it, not through HTTP.
@pytest.mark.parametrize("path", ["../secret.txt", "assets/../../secret.txt", "/etc/passwd", ""])
def test_nothing_outside_the_build_is_resolved(tmp_path, path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    assert file_in_build(dist, path) is None

def test_a_file_of_the_build_is_resolved(tmp_path):
    (tmp_path / "sw.js").write_text("")
    assert file_in_build(tmp_path, "sw.js") == (tmp_path / "sw.js").resolve()

def test_without_a_build_nothing_but_the_api_answers(api_without_web):
    assert api_without_web.get("/settings").status_code == 404
```

- [ ] **Step 2: Run** `tests/unit/api/test_web.py`. Expected: FAIL (`api.web` missing).

- [ ] **Step 3: Implement `mount_application`.** First the API's 404: one
  `api_route` on `/api` and on `/api/{path:path}`, for `GET`, `HEAD`, `POST`, `PUT`,
  `PATCH`, `DELETE` and `OPTIONS`, raising `HTTPException(404)`. Without it `/api` falls
  through to the application, and a `POST` to an unknown `/api` path meets the
  application's `GET` route and answers `405`. Then `GET /{path:path}`: serve
  `file_in_build(dist, path)` with `FileResponse` when it is not `None`, otherwise
  `index.html`. `file_in_build(dist: Path, path: str) -> Path | None` resolves `dist / path`
  and returns it only when it is a file and `resolved.is_relative_to(dist.resolve())`. None
  of these routes appears in the OpenAPI document (`include_in_schema=False`).

- [ ] **Step 4: Wire `create_app` and `build`.** Run the whole suite. Expected: all pass.

- [ ] **Step 5: Commit** — `feat(api): serve the application's build from the same origin`

### Task 6: The paths in the documents

**Files:**
- Modify: `.env.example:24`, `deploy/env.production.example:20`, `README.md:53-54`,
  `docs/operations.md` (sections 4 and 6), `docs/specs/2026-09-17-platform-design.md` (§11)

- [ ] **Step 1: Update.** The redirect URIs end in `/api/auth/callback/google`. The README signs
  in at `http://localhost:8000/api/auth/login/google` and points at
  `http://localhost:8000/api/docs`. Runbook §4 says `/api/docs` and `/api/auth/login/google`.
  Runbook §6 gains: *"Rolling back to a release before the `/api` prefix needs
  `GOOGLE_REDIRECT_URI` without `/api`: keep both URIs in the OAuth client and change
  `.env` only."* Platform spec §11 gains one line above its table: *"Every path is under the
  `/api` prefix (application spec §2.1)."*

- [ ] **Step 2: Verify** `grep -rn "localhost:8000/auth\|/auth/callback/google" --include=*.md --include=*.example --exclude-dir=plans --exclude-dir=.venv .`
  prints only lines that contain `/api/auth`. `docs/plans/` is left out: the plans of
  earlier phases record the paths of their time and are not rewritten. Then
  `grep -rnE "(GET|POST|PUT|PATCH|DELETE) /[a-z]" api core` prints, without `/api`, only
  docstrings and comments (`api/routes/proposal.py:3`, `core/catalog.py:4`,
  `core/reading.py:3`), never an error message.

- [ ] **Step 3: Commit** — `docs: the API's paths under /api`

## What you verify before phase 10

1. In the Google OAuth client, add `…/api/auth/callback/google` for development
   (`http://localhost:8000`) and for production, keeping the old URIs.
2. Locally: `alembic upgrade head`, run the API, open `http://localhost:8000/api/docs`,
   sign in at `/api/auth/login/google`. The browser ends on `/` with a JSON 404 (no build yet)
   and `GET /api/auth/me` answers.
3. Deploy. Change `GOOGLE_REDIRECT_URI` in the host's `.env` and recreate the platform. Sign
   in through your way in; `POST /api/portfolio/refresh` returns `holdings` as a list.
