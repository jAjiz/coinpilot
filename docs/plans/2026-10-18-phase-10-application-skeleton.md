# Phase 10 — The application's skeleton

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `web/` holds a React application that signs in, keeps the session alive with a
single refresh, routes every user to where they belong (login, onboarding step, shell),
installs as an app on a phone, and ships inside the platform's image, built and checked
by CI.

**Architecture:** The platform writes its OpenAPI document to `web/openapi.json`, and a
platform test fails when the committed copy is stale. `openapi-typescript` turns it into
`web/src/api/schema.d.ts`, and the `web` CI job fails when that copy is stale. The two
checks together keep the application tied to the API. Every call goes through one
`openapi-fetch` client whose `fetch` handles a `401`: one refresh shared by every request
waiting on it, then one retry. Guards are React Router layout routes that read two
TanStack Query queries, the session and the onboarding state. The screens are
placeholders here; phases 11 to 13 fill them in. The `Dockerfile` gains a `node` stage
that builds `web/dist`, and the final image copies only that.

**Tech Stack:** Node 24, TypeScript, React, Vite, React Router, TanStack Query,
`openapi-typescript`, `openapi-fetch`, Tailwind CSS, shadcn/ui, `vite-plugin-pwa`,
Vitest, Testing Library, MSW, Playwright. The platform side is Python 3.13 with no new
dependency.

**Spec:** [`docs/specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md). This
phase covers §2.2–§2.5, §4, §7 (the states, the offline notice, the shell-only service
worker) and §8 (the CI job).

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md), phase 10.

## Global Constraints

- **Node 24** everywhere: `web/.nvmrc` holds `24`, CI uses `node-version-file`, and the
  image's build stage is `node:24-trixie-slim`.
- **Dependencies:** the current major of each library in the stack above, installed when
  the task runs. `package-lock.json` is committed. CI and the image use `npm ci`.
  **No other runtime dependency.** `big.js` waits for phase 11, the first code that adds
  amounts.
- **No inline `<script>` in the build.** The platform serves the application with
  `script-src 'self'` (`api/web.py`). Inline styles are allowed. **No resource from
  another origin**: no web fonts or CDN; the system font stack only.
- **No amount is a JavaScript `number`** (spec §4.5). This phase handles no amount.
- **English copy.** Copy quoted in this plan is exact.
- **The service worker caches the application shell only**, never an `/api` response,
  and never answers a navigation under `/api` (spec §7).
- **`web/**` is checked out with LF line endings** (`.gitattributes`). The repository
  uses `core.autocrlf=true` on Windows, and Prettier and the generated-client check would
  see every CRLF file as changed.
- Platform rules still hold: `ruff check` and `ruff format --check` pass, the coverage
  gate is 80 %, and no test touches the network.
- **No secret, host name or IP address in the repository.**
- Commit messages follow Conventional Commits and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Commands:

```bash
# Platform (PostgreSQL from docker-compose.dev.yml running)
RUN_DB_INTEGRATION=true PYTHONPATH=. DATABASE_URL=postgresql+psycopg://coinpilot:coinpilot@localhost:5432/coinpilot .venv/Scripts/python.exe -m pytest tests
# Application, from web/
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build && npm run check:build
```

## Review Focus

1. **The installed app can still sign in.** The sign-in link (`/api/auth/login/google`)
   and Google's return (`/api/auth/callback/google`) are navigations. If the service
   worker answered them with the cached `index.html`, a phone could never sign in again.
   → Task 5, the denylist test.
2. **The production build renders under the platform's CSP.** Development has no CSP, so
   an inline script would only show up as a blank page in production. → Task 5's
   `check:build` and Task 7's `curl` of the header.
3. **A platform that is down is not a sign-out.** If `/api/auth/me` answers `503` or the
   network fails, the user sees an error with "Try again", not `/login`. → Task 4.
4. **A retried request keeps its body.** A `PATCH` that meets a `401` is sent again with
   the same JSON after the refresh. Without that, a settings change would be lost
   without any error. → Task 3.
5. **A deep link cannot skip onboarding, and an onboarded user cannot re-enter it.**
   `/onboarding/summary` without a key goes to `/onboarding/key`. `/onboarding/key` for an
   onboarded user goes to `/`. → Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/app.py` | `openapi_document()`: the API's document without a context |
| `scripts/export_openapi.py` | Writes `web/openapi.json` |
| `web/openapi.json`, `web/src/api/schema.d.ts` | The contract, both committed, both checked |
| `web/src/api/client.ts` | `api` (the `openapi-fetch` client), `fetchWithRefresh`, `onSessionEnded`, `ApiError`, `unwrap` |
| `web/src/lib/onboarding.ts` | `onboardingStep`, `reachableSteps`: pure |
| `web/src/features/auth/` | `session.ts` (queries), `guards.tsx`, `LoginPage.tsx` |
| `web/src/features/shell/` | `AppShell.tsx` (bottom bar), `OfflineNotice.tsx`, `useOnline.ts` |
| `web/src/features/{onboarding,dashboard,history,settings}/` | Placeholder pages |
| `web/src/components/` | `FullPageSkeleton.tsx`, `LoadFailed.tsx`; `ui/` from shadcn/ui |
| `web/src/routes.tsx`, `web/src/providers.tsx`, `web/src/main.tsx` | The route tree, the query client and session wiring, the entry |
| `web/pwa.config.ts` | Manifest and Workbox options, imported by `vite.config.ts` |
| `web/scripts/check-build.mjs` | Fails on an inline script or a manifest without its icons |
| `web/e2e/journey.spec.ts` | Playwright, against `vite preview` with the API mocked |
| `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml` | The `node` stage; the `web` job; image checks |
| `.gitattributes`, `.gitignore`, `.env.example`, `README.md` | LF in `web/`; Node artefacts; the development redirect URI; how to develop |

---

### Task 1: The OpenAPI document as a file

**Files:**
- Modify: `api/app.py`
- Create: `scripts/export_openapi.py`, `web/openapi.json` (generated), `tests/unit/api/test_openapi_document.py`

**Interfaces:**
- Produces: `openapi_document() -> dict[str, Any]` in `api/app.py`. It builds the same
  FastAPI object as `create_app`, with the same title, version, docs URLs and routers
  under `API_PREFIX`, but with no context, no lifespan and no application build, and
  returns `.openapi()`. To get that, extract `_api() -> FastAPI` (the constructor call and
  the router loop) from `create_app`. `create_app` calls `_api()` and then sets
  `app.router.lifespan_context = _lifespan`, the state, the exception handlers and the
  build.
- Produces: `OPENAPI_FILE = <repo>/web/openapi.json` in `scripts/export_openapi.py`.
  `main()` writes `json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n"`
  with `newline="\n"`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_the_committed_document_is_the_apis():
    committed = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert committed == openapi_document(), "stale: run python scripts/export_openapi.py"

def test_the_document_holds_only_the_api():
    assert all(path.startswith("/api/") for path in openapi_document()["paths"])

def test_the_document_matches_the_running_app(make_context):
    assert openapi_document() == create_app(make_context(nullcontext)).openapi()
```

- [ ] **Step 2: Run** `… -m pytest tests/unit/api/test_openapi_document.py -v`. Expected: FAIL (import).
- [ ] **Step 3: Implement** `_api`, `openapi_document` and the script. Then run
  `PYTHONPATH=. .venv/Scripts/python.exe scripts/export_openapi.py`.
- [ ] **Step 4: Run the whole platform suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(api): the OpenAPI document as a committed file`

### Task 2: The scaffold and the generated client

**Files:**
- Create: `web/` from `npm create vite@latest web -- --template react-ts`, then remove the
  template's demo (`App.css`, `assets/react.svg`, the counter).
- Create: `web/.nvmrc`, `web/.prettierrc.json` (`{}`), `web/.prettierignore`
  (`dist`, `coverage`, `src/api/schema.d.ts`, `openapi.json`, `src/components/ui`,
  `playwright-report`, `test-results`), `web/src/test/setup.ts`, `web/src/test/server.ts`,
  `web/src/api/schema.d.ts` (generated)
- Modify: `.gitattributes` (`web/** text eol=lf`), `.gitignore` (`node_modules/`,
  `web/coverage/`, `web/playwright-report/`, `web/test-results/`; `dist/` is already there)

**Interfaces:**
- Produces, the `package.json` scripts: `dev` (`vite`), `build` (`tsc -b && vite build`),
  `preview`, `typecheck` (`tsc -b`), `lint` (`eslint .`), `format:check`
  (`prettier --check .`), `test` (`vitest run`), `generate`
  (`openapi-typescript openapi.json -o src/api/schema.d.ts`), and `check:generated`
  (`npm run generate && git diff --exit-code -- src/api/schema.d.ts`).
- Produces: `vite.config.ts` with `@vitejs/plugin-react` and `@tailwindcss/vite`, the alias
  `@` → `src`, `server: { port: 5173, strictPort: true, proxy: { "/api": "http://localhost:8000" } }`
  (no `changeOrigin`: the platform must see the browser's host), and
  `test: { environment: "jsdom", setupFiles: ["src/test/setup.ts"], exclude: [...configDefaults.exclude, "e2e/**"] }`.
- Produces: `src/test/server.ts` exports `server = setupServer()` (MSW, `msw/node`).
  `setup.ts` imports `@testing-library/jest-dom/vitest` and runs `server.listen({ onUnhandledRequest: "error" })`,
  `server.resetHandlers()` and `cleanup()` after each test, and `server.close()`.
- Produces: Tailwind v4 (`@import "tailwindcss"` in `src/index.css`) and shadcn/ui
  initialised (`npx shadcn@latest init`, then `add button skeleton`). This writes
  `components.json`, `src/lib/utils.ts` (`cn`) and `src/components/ui/`.

- [ ] **Step 1: Scaffold** and install the dependencies of the stack. Runtime:
  `react-router`, `@tanstack/react-query`, `openapi-fetch`. Development:
  `openapi-typescript`, `vitest`, `jsdom`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/user-event`, `msw`, `prettier`,
  `tailwindcss`, `@tailwindcss/vite`. Vite, TypeScript and ESLint come with the template.
- [ ] **Step 2: Generate the client:** `npm run generate`. Check that `schema.d.ts` names
  `"/api/auth/me"`.
- [ ] **Step 3: Write `src/main.tsx`** to render a heading `CoinPilot`. Task 4 replaces it.
- [ ] **Step 4: Verify.** Every script passes: `lint`, `format:check`, `typecheck`,
  `build`, `check:generated` (no diff). `npm test` passes with no tests
  (`passWithNoTests: true` until Task 3). With the API running, `npm run dev` and a
  request to `http://localhost:5173/api/health` returns `{"status":"ok"}`.
- [ ] **Step 5: Commit** `feat(web): the application's scaffold and its generated client`.
  If the `check-added-large-files` hook refuses `package-lock.json`, raise its limit in
  `.pre-commit-config.yaml` with `args: [--maxkb=2048]` in the same commit.

### Task 3: One refresh for every expired request

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/client.test.ts`

**Interfaces:**
- Produces:

```ts
export const api: Client<paths>;   // createClient<paths>({ baseUrl: window.location.origin, fetch: fetchWithRefresh })
export function fetchWithRefresh(request: Request): Promise<Response>;
export function onSessionEnded(listener: () => void): () => void;  // returns the unsubscribe
export class ApiError extends Error { readonly status: number; readonly detail: string; readonly body: unknown }
export function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T>;
```

- `fetchWithRefresh` keeps a `request.clone()` before it sends. On a `401` from any path
  except `/api/auth/refresh`, it awaits the **one** refresh in flight (a module-level
  promise, created by the first request that needs it and cleared when it settles):
  `POST /api/auth/refresh`, sent with the browser's `fetch` directly and with no body. The
  cookie carries the token. If the refresh succeeds, it sends the clone once and returns
  that answer, whatever it is. If the refresh is refused or fails, it calls every
  `onSessionEnded` listener and returns the original `401`.
- `unwrap` resolves to `data` when `response.ok` is true. Otherwise it throws an
  `ApiError`. Its `detail` is the body's `detail` when that is a string, the first `msg`
  when it is a list (a `422`), and `response.statusText` otherwise.

- [ ] **Step 1: Write the failing tests** (MSW; one handler counts the calls to
  `/api/auth/refresh`):

```ts
test("three requests that meet a 401 share one refresh and all succeed", ...)
  // /api/auth/me, /api/config and /api/credentials/status answer 401 until the refresh;
  // Promise.all of the three → every one resolves, refreshCalls === 1
test("a refused refresh ends the session once and returns the 401", ...)
  // the refresh answers 401 → each request's response.status === 401, the listener is called 1 time
test("a retried request is sent again with its body", ...)
  // PATCH /api/config {"paused": true} → 401, refresh, retry; the handler sees the same JSON both times
test("a second 401 after the retry is returned, not refreshed again", ...)
  // refreshCalls === 1 and the 401 comes back
test("other errors pass through without a refresh", ...)
  // 503 → refreshCalls === 0
test("unwrap throws the platform's detail", ...)
  // {"detail": "no key is registered"} with 404 → ApiError status 404, detail verbatim;
  // 422 with [{"msg": "Input should be greater than 0", ...}] → that msg
```

- [ ] **Step 2: Run** `npx vitest run src/api`. Expected: FAIL.
- [ ] **Step 3: Implement** `client.ts`.
- [ ] **Step 4: Run** `npm test`, `npm run typecheck`, `npm run lint`. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): one refresh for every expired request`

### Task 4: Sign-in, guards and the empty shell

**Files:**
- Create: `web/src/lib/onboarding.ts` and its test; `web/src/features/auth/session.ts`,
  `guards.tsx`, `LoginPage.tsx`; `web/src/features/shell/AppShell.tsx`,
  `OfflineNotice.tsx`, `useOnline.ts`; the placeholders
  `features/onboarding/OnboardingPage.tsx`, `features/dashboard/DashboardPage.tsx`,
  `features/history/HistoryPage.tsx`, `features/settings/SettingsPage.tsx`;
  `web/src/components/FullPageSkeleton.tsx`, `LoadFailed.tsx`; `web/src/routes.tsx`,
  `web/src/providers.tsx`; `web/src/test/render.tsx`; `web/src/features/auth/guards.test.tsx`,
  `web/src/features/shell/AppShell.test.tsx`
- Modify: `web/src/main.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap`, `ApiError`, `onSessionEnded` (Task 3).
- Produces, in `lib/onboarding.ts`:

```ts
export const ONBOARDING_STEPS = ["key", "portfolio", "automation", "summary"] as const;
export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];
export function onboardingStep(state: { keyRegistered: boolean; fiat: string | null; assetCount: number }): OnboardingStep;
  // no key → "key"; no fiat or no asset → "portfolio"; otherwise "automation" (spec §4.2)
export function reachableSteps(first: OnboardingStep): OnboardingStep[];
  // every step up to `first`; "automation" also reaches "summary"
```

- Produces, in `features/auth/session.ts`: `meKey = ["me"]`, `onboardingKey = ["onboarding"]`,
  `type Me = components["schemas"]["MeOut"]`,
  `type Onboarding = { onboarded: true } | { onboarded: false; step: OnboardingStep }`,
  `fetchMe(): Promise<Me | null>` (a `401` resolves to `null`), and
  `fetchOnboarding(): Promise<Onboarding>`. `fetchOnboarding` reads `GET /api/config`
  first: a `404` means no settings, and a set `onboarded_at` means onboarded. When not
  onboarded, it reads `GET /api/credentials/status` and `GET /api/assets` in parallel.
  Also `useMe()` and `useOnboarding()`; the second is enabled only when `useMe()` has a
  user.
- Produces, in `providers.tsx`: `createQueryClient()` (queries `retry: false`;
  `staleTime: 30_000`), and `<Providers client>`. `Providers` subscribes to
  `onSessionEnded` and then removes every query and sets `meKey` to `null`.
- Produces, in `routes.tsx`: `routes: RouteObject[]`:

```
/login                         LoginPage
RequireSession
  /onboarding, /onboarding/:step   OnboardingGate → OnboardingPage
  RequireOnboarded → AppShell
    /            DashboardPage
    /history     HistoryPage
    /settings    SettingsPage
*                              <Navigate to="/" replace />
```

- **Guards** (`guards.tsx`): while loading, each one renders `FullPageSkeleton`. On an
  error, it renders `LoadFailed`: the `ApiError` detail (or "The connection failed.") and
  a **Try again** button that refetches.
  - `RequireSession`: `null` → `/login`.
  - `RequireOnboarded`: not onboarded → `/onboarding/<step>`.
  - `OnboardingGate`: onboarded → `/`. A `:step` missing from `reachableSteps(step)` →
    `/onboarding/<step>`.
  - Every redirect uses `replace`.
- **Copy.**
  - `LoginPage`: heading "CoinPilot", the line "Keeps your Kraken portfolio on its
    targets.", and a link styled as a button, "Sign in with Google". It is a plain
    `<a href="/api/auth/login/google">`, a full navigation and not a router link. When
    `?error=` is set, an alert shows it verbatim. A signed-in user who opens it goes to
    `/`.
  - `OnboardingPage`: a heading per step ("Kraken key", "Portfolio", "Automation",
    "Summary") and "This step is not built yet.".
  - `DashboardPage`: heading "Home". `HistoryPage`: heading "History". `SettingsPage`:
    heading "Settings". Each says "Signed in as {email}.".
  - `AppShell`: a bottom navigation with `NavLink`s "Home" (`/`), "History", "Settings".
  - `OfflineNotice`: shown by both layouts while `useOnline()` is false, with the copy
    "You're offline. Nothing can be sent until the connection is back." `useOnline()`
    (`navigator.onLine` and the `online` and `offline` events) is what phases 11 to 13
    use to disable the buttons that send (spec §7).
- Produces, in `test/render.tsx`: `renderAt(path: string, handlers?: HttpHandler[])`, which
  renders `routes` in a `createMemoryRouter` inside `Providers` and returns the router, so
  that tests can read `router.state.location`.

- [ ] **Step 1: Write the failing tests.** In `lib/onboarding.test.ts`, the table of
  `onboardingStep` (no key, a key with no fiat, a fiat with no asset, all three) and of
  `reachableSteps` (`"key"` → `["key"]`; `"automation"` → all four). Then `guards.test.tsx`:

```ts
test("a signed-out user is sent to /login", ...)            // /settings, me 401, refresh 401
test("a user without a key starts onboarding at the key", ...)  // config 404, status registered:false
test("a deep link cannot skip a step", ...)                 // /onboarding/summary → /onboarding/key
test("an onboarded user cannot re-enter onboarding", ...)   // /onboarding/key → /
test("an onboarded user reaches the page asked for", ...)   // /settings: "Settings", "Signed in as a@b.c"
test("a platform that is down is not a sign-out", ...)      // me 503 → detail and "Try again"; the
                                                            // next answer 200 → the page; still not /login
test("the login page shows the refusal", ...)               // /login?error=this%20account%20is%20disabled
test("the sign-in link leaves the application", ...)        // href === "/api/auth/login/google"
test("an unknown path goes home", ...)
```

  In `AppShell.test.tsx`: the three tabs, and the offline notice. Set `navigator.onLine`
  to false and dispatch `offline`: the notice appears. Dispatch `online`: it goes away.
- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**, then `main.tsx`: `createBrowserRouter(routes)` inside
  `Providers`.
- [ ] **Step 4: Run** `npm test`, `typecheck`, `lint`, `format:check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): sign-in, guards and the empty shell`

### Task 5: Installable, with the shell cached

**Files:**
- Create: `web/pwa.config.ts`, `web/pwa.config.test.ts`, `web/pwa-assets.config.ts`,
  `web/public/icon.svg`, `web/scripts/check-build.mjs`
- Modify: `web/vite.config.ts`, `web/index.html`, `web/package.json` (`check:build`)

**Interfaces:**
- Produces, in `pwa.config.ts`, the options `vite.config.ts` passes to `VitePWA`:

```ts
export const pwaOptions: Partial<VitePWAOptions> = {
  registerType: "autoUpdate",
  injectRegister: "script-defer",        // registerSW.js, an external file: no inline script
  pwaAssets: { config: true },           // icons from pwa-assets.config.ts (minimal2023Preset, public/icon.svg)
  manifest: {
    name: "CoinPilot", short_name: "CoinPilot",
    description: "Keeps your Kraken portfolio on its targets.",
    start_url: "/", scope: "/", display: "standalone",
    theme_color: "#0f172a", background_color: "#0f172a",
  },
  workbox: {
    globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}"],
    navigateFallback: "/index.html",
    navigateFallbackDenylist: [API_NAVIGATION],
    runtimeCaching: [],                  // nothing fetched at run time is cached: no /api answer
  },
  devOptions: { enabled: false },
};
export const API_NAVIGATION = /^\/api(\/|$)/;
```

- Dependencies: `vite-plugin-pwa` and `@vite-pwa/assets-generator`, both development.
- `public/icon.svg`: a simple glyph on a `#0f172a` square, no text, safe inside the
  maskable margin.
- `index.html`: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
  and `<meta name="theme-color" content="#0f172a">`.
- `check-build.mjs` exits non-zero, naming the problem, when any of these is true:
  - `dist/index.html` has a `<script` with no `src=`;
  - `dist/manifest.webmanifest` lacks a `192x192` or a `512x512` icon;
  - `dist/sw.js` is missing.

- [ ] **Step 1: Write the failing tests** in `pwa.config.test.ts`:

```ts
test.each(["/api", "/api/auth/login/google", "/api/auth/callback/google?code=x&state=y"])(
  "the service worker leaves %s to the network", (path) => expect(API_NAVIGATION.test(path)).toBe(true));
test.each(["/", "/settings", "/onboarding/key", "/apiary"])(
  "the service worker answers %s with the shell", (path) => expect(API_NAVIGATION.test(path)).toBe(false));
test("nothing is cached at run time", () => expect(pwaOptions.workbox?.runtimeCaching).toEqual([]));
test("no inline registration script", () => expect(pwaOptions.injectRegister).toBe("script-defer"));
```

- [ ] **Step 2: Run** `npm test`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Wire `VitePWA(pwaOptions)` into `vite.config.ts`. Add
  `pwa.config.ts`, `pwa.config.test.ts` and `pwa-assets.config.ts` to `include` in
  `tsconfig.node.json`, so that `typecheck` covers them.
- [ ] **Step 4: Verify.** `npm run build && npm run check:build` passes, and
  `dist/` holds `sw.js`, `manifest.webmanifest`, `registerSW.js` and the generated icons.
  Then add `<script>alert(1)</script>` to `index.html`, run the build again, and check
  that `check:build` fails. Revert.
- [ ] **Step 5: Commit** `feat(web): installable, with only the shell cached`

### Task 6: The sign-in journey end to end

**Files:**
- Create: `web/playwright.config.ts`, `web/e2e/journey.spec.ts`
- Modify: `web/package.json` (`e2e`: `npm run build && playwright test`),
  `web/tsconfig.node.json` (`include` gains `playwright.config.ts` and `e2e`)

**Interfaces:**
- `playwright.config.ts`: `webServer` runs `npm run preview -- --port 4173 --strictPort`
  on a build that already exists (`reuseExistingServer: !process.env.CI`). `use: { baseURL: "http://localhost:4173", serviceWorkers: "block" }`.
  The service worker is blocked so that `page.route` sees every request. One project,
  `devices["Pixel 7"]`.
- Every `/api/**` request is answered with `page.route`. Nothing reaches a platform.

- [ ] **Step 1: Write the journey** in `e2e/journey.spec.ts`:

```ts
test("signed out, the application asks for a sign-in", ...)
  // /settings → /login; the link's href is /api/auth/login/google
test("a refused sign-in is explained", ...)
  // /login?error=google%20did%20not%20grant%20the%20login → the reason visible
test("a new user lands on the first onboarding step", ...)
  // me 200, config 404, status registered:false → /onboarding/key, "Kraken key"
test("an onboarded user moves between the tabs", ...)
  // / "Home" → tap "History" → /history → tap "Settings" → /settings
test("an expired session is renewed without leaving the page", ...)
  // me 401 the first time, refresh 200, me 200 → "Home", refresh called once
```

- [ ] **Step 2: Run** `npx playwright install chromium` once, then `npm run e2e`. Expected: 5 pass.
- [ ] **Step 3: Commit** `test(web): the sign-in journey end to end`

### Task 7: The image and CI

**Files:**
- Modify: `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`

**Interfaces:**
- `Dockerfile`, before today's stage:

```dockerfile
FROM node:24-trixie-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build && npm run check:build
```

  The final stage gains `COPY --from=web /web/dist web/dist` after `COPY scripts scripts`.
  `api/main.py` already serves `/app/web/dist` when it holds an `index.html`.
- `.dockerignore` gains `web/node_modules`, `web/dist`, `web/coverage`,
  `web/playwright-report`, `web/test-results`.
- `ci.yml` gains a job `web` ("Application"), with `defaults.run.working-directory: web`:
  - checkout;
  - `actions/setup-node`, pinned to an exact release tag like the other actions, with
    `node-version-file: web/.nvmrc`, `cache: npm` and
    `cache-dependency-path: web/package-lock.json`;
  - `npm ci`, `lint`, `format:check`, `typecheck`, `test`, `check:generated`, `build`,
    `check:build`;
  - `npx playwright install --with-deps chromium`, then `npx playwright test` (the build
    from the step before; `npm run e2e` would build again).
- The `image` job gains, after **Build**:
  - `docker run --rm <image> test -f web/dist/index.html`
  - `docker run --rm <image> sh -c 'test ! -e web/node_modules && test ! -e web/src'`
- After the first `deploy ci-1` and its health check:
  - `curl -fsS http://127.0.0.1:8000/settings | grep -q 'id="root"'` (a deep link is the application)
  - `curl -fsSI http://127.0.0.1:8000/ | grep -qi '^content-security-policy:'`
  - `curl -fsS http://127.0.0.1:8000/api/nothing -o /dev/null -w '%{http_code}' | grep -qx 404`
    (`-f` fails on a 404, so this last command uses `-sS` and the status code only)

- [ ] **Step 1: Change the `Dockerfile` and `.dockerignore`.** Run `docker build -t coinpilot:local .`.
  Expected: it builds. `docker run --rm coinpilot:local ls web/dist` lists `index.html`
  and `sw.js`.
- [ ] **Step 2: Change `ci.yml`.** Validate it with `check-yaml` (pre-commit).
- [ ] **Step 3: Commit** `build: the application in the image, and a CI job for web/`.
  CI on the PR is the verification: both jobs green.

### Task 8: Developing the application

**Files:**
- Modify: `.env.example` (`GOOGLE_REDIRECT_URI=http://localhost:5173/api/auth/callback/google`),
  `README.md` (development section)

- [ ] **Step 1: Write the README section.** Development:
  1. Run the API as today.
  2. `cd web && npm ci && npm run dev`, then open `http://localhost:5173`. Sign-in goes
     through the proxy, so the Google client needs the `5173` redirect URI.
  3. After a change to the API's routes or schemas, run
     `python scripts/export_openapi.py` and then `npm run generate` in `web/`. Commit
     both files. Two checks refuse a stale copy: a platform test and `check:generated`
     in CI.
  4. Tests: `npm test` and `npm run e2e`.
- [ ] **Step 2: Commit** `docs: developing the application`

## What you verify before phase 11

1. In the Google OAuth client, add `http://localhost:5173/api/auth/callback/google`. Set it
   as `GOOGLE_REDIRECT_URI` in your local `.env`.
2. Locally: run the API and `npm run dev`, open `http://localhost:5173` and sign in. You
   land on the onboarding step your development account is at: it holds the Kraken key
   from phase 4. Reload on a deep link (`/settings`): the guards send you to the same
   place.
3. Deploy. On the phone, open the address and sign in. You see "Kraken key" and "This
   step is not built yet.". Production has no key. The page is not blank, so the CSP
   lets the build run.
4. Install it: "Add to Home screen" or "Install app". Open it from the icon. It starts
   standalone, without the browser bar, and goes back to the same step. Close it, wait
   more than 15 minutes and open it again: you are still signed in (the single refresh).
