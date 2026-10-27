# Phase 13 — History and settings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** History lists what CoinPilot did, each run with its messages and the orders it
placed. Settings edits every block of the configuration on its own, holds the key, pauses
everything and signs out. Four items parked in phases 11 and 12 are closed: a lost
answer to a confirmation, an outcome lost by leaving the screen, a dismissal of a version
not seen, and a custom cadence that could not be edited.

**Architecture:** Three platform changes come first, each with its tests and the
regenerated client. Orders record the session that placed them. `GET /api/sessions`
hides the runs that did nothing when asked to, and pages with a cursor.
`DELETE /api/proposal` takes the version it withdraws. The application then adds
`features/history/` and `features/settings/`. Settings reuses phase 11's step forms
through their `onSaved`. The copy for runs and orders is pure functions in
`web/src/lib/history.ts`. The confirmations of invest and approve are held in TanStack
Query's mutation cache, keyed, so they outlive the component that started them.

**Tech Stack:** As phase 12. One Alembic migration. No new dependency.

**Spec:** [`docs/specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md). This
phase covers §5.3 ("Custom"), §6.3, §6.4, §7 (states, the two-tap rule, offline) and §8
(unit tests for the new `lib/` functions, component tests, one journey end to end). The
platform spec is [`2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md).

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md), phase 13.

## Global Constraints

- **No amount is a JavaScript `number`** (spec §4.5). They stay decimal strings, with
  arithmetic through `lib/decimal.ts`. The integers of a custom cadence (days, months)
  are the one exception: the platform types them as `int`.
- **No new dependency.** If a new shadcn component is needed, add it with
  `npx shadcn@latest add <name>`.
- **Every button that sends is disabled while its request is in flight and while
  `useOnline()` is false** (spec §7).
- **Actions that move money show what they will do first and take a second tap.**
  Deleting the key does not move money, but it stops the automation, so it also takes
  a second tap (Decision 7).
- **Times are the browser's time zone**, told with `formatRun` (`lib/summary.ts`). Tests
  run in `Europe/Madrid`.
- **English copy. Copy quoted in this plan is exact.** Page headings stay "History" and
  "Settings": phase 10's tests read them.
- **Every platform change regenerates the client in the same commit:**
  `PYTHONPATH=. python scripts/export_openapi.py`, then `npm run generate` in `web/`.
  `npm run check:generated` and the platform's stale-document test must pass.
- **Every query is scoped to the user** (platform spec, tenant isolation). A session id
  or a cursor that belongs to another user answers as if it did not exist.
- Phase 10's rules hold: no inline `<script>`, no resource from another origin, LF in
  `web/**`, no `/api` response cached by the service worker.
- **No secret, host name or IP address in the repository.**
- Commit messages follow Conventional Commits and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Commands:

```bash
# platform, from the repository root
ruff check . && ruff format --check . && pytest
# application, from web/
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build && npm run check:build && npm run check:generated
npm run e2e
```

## What the platform answers today

Read from `api/routes/{history,credentials,config,proposal,auth}.py`, `core/execution.py`,
`core/db/{orders,telemetry,proposals}.py` and `core/scheduler.py`.

| Call | Answer |
|---|---|
| `GET /api/sessions?limit=` | `EvaluationOut[]`, newest first, limit 1–200 (default 50). No `id` |
| `GET /api/orders?limit=` | `OrderOut[]`, newest first. No link to a session |
| `GET /api/credentials/status` | `{registered, validated_at, key_version}` |
| `POST /api/credentials` | Validates and **replaces** any stored key; `KeyAcceptedOut` |
| `DELETE /api/credentials` | `204`; `404` "no key is registered" |
| `PATCH /api/config` | Any subset; changing a cadence moves `next_invest_at` / `next_rebalance_at` (`rescheduled`) |
| `POST /api/auth/logout` | `204`; revokes the refresh family, clears both cookies |
| `DELETE /api/proposal` | `204`; `404` "there is no live proposal"; withdraws whatever version is live |

Facts that shape the screens:

- **A session is written for each evaluation, not for each tick.** The scheduler
  evaluates only the users whose next run has come (`due_users`). With the "As soon as
  possible" invest cadence, that is up to 96 runs a day, most of them `NOTHING_TO_DO`.
  Previews write none.
- **Session statuses** (`EvaluationStatus`, plus `RUNNING` while open): `DONE`,
  `NOTHING_TO_DO`, `STOPPED`, `UNRESOLVED`, `KRAKEN_UNAVAILABLE`, `ERROR`, `PARTIAL`,
  `PROPOSED`, `SUPERSEDED`. Operations: `INVEST`, `PROPOSE`, `APPROVE`, `REBALANCE`, or
  `null` on old rows. Triggers: `API`, `SCHEDULER`, or `null`.
- **`log_messages`** is one string with one message per line, or `null`.
- **Sessions are deleted after 90 days** (`sessions_retention`). Orders are never deleted.
- **A paused user is never chosen by the scheduler.** Manual operations still work.
  After a resume, a run whose time passed during the pause happens once, on the next
  tick (platform spec §10.2).

## Decisions this plan takes

1. **`orders.session_id`**, nullable, `ON DELETE SET NULL`. Orders placed before the
   migration have none. So does an order whose session retention deleted.
   `record_attempt` takes it, and `_run` passes the evaluation's id down to `_attempt`.
2. **`GET /api/sessions` gains `idle` and `before`.** `idle=false` leaves out
   `NOTHING_TO_DO`. The default stays `true`, so existing callers see no change.
   `before` is the `id` of the last session already shown. The page continues strictly
   after it, ordered by `(started_at, id)` descending. An unknown `before`, or one that
   belongs to another user, is a `404` "that session no longer exists".
3. **The application hides the idle runs by default.** History has a switch, "Show runs
   with nothing to do", off at first and not remembered. Pages are 20 long. "Load more"
   shows while the last page came back full.
4. **`GET /api/orders` gains `session`.** It takes a session id and returns that
   session's orders, oldest first: the order they were sent in. Without it, the call
   answers as today.
5. **`DELETE /api/proposal?version=N`**, with `version` required. When it is not the
   live version, the answer is `409` with `{detail, proposal}`, like approve. The
   check and the withdrawal run in one transaction, with the slot locked
   (`SELECT … FOR UPDATE`). The application is the API's only client, so making the
   parameter required breaks nobody.
6. **A lost answer is not an error.** A confirmed invest or approval that ends in a
   network failure, or in a `500`, `502` or `504`, may have placed orders. The screen
   says so and links to History, instead of showing an error that invites another tap.
   A `503` keeps the spec's sentence: the platform answered it, and nothing was
   recorded.
7. **Deleting the key takes a second tap and says what it stops.** Replacing it uses the
   same form as onboarding. A replacement is validated before it is stored, so a key
   Kraken refuses never replaces the working one.
8. **Settings shows each block as a summary with "Edit".** Edit opens phase 11's form.
   The portfolio form reads Kraken (`POST /api/portfolio/refresh`) only when it opens.
   After a save, the summary returns, showing the new values and the next runs.
9. **Home says when automation is paused**, so a pause is never forgotten.
10. **Settings reads a stored configuration as it is.** `settingsValues` is
    `wizardValues` without the wizard's defaults. A rebalance cadence at `MIN`, which only
    the API can set, shows as "Custom", not as quarterly.
11. **A custom cadence is edited through its own fields:** mode, days, months and the
    anchor as a local date and time. It is sent only when one of them changed. Each
    field is validated before sending, with the bounds `ConfigPatch` enforces.
12. **Sign out clears every query** before it opens `/login`. Data from one user must
    never be shown to the next user. A failed logout request stays on Settings with the
    error, because the cookies were not cleared.

## Review Focus

1. **Leaving the screen while a confirmation is in flight must not lose its outcome or
   the refresh after it.** The user taps "Confirm", switches to History, then comes back
   to Home. → Task 5, the component test that unmounts mid-request.
2. **A network failure after "Confirm" must not read as "nothing happened".** → Task 5
   (`isLostAnswer`, and the screen test).
3. **Paging must neither repeat nor skip runs that share a `started_at`.** Every leg of
   a rebalance shares the transaction's timestamp; sessions can too. → Task 2, the test
   with three sessions at one instant across a page boundary.
4. **A user must never read another user's sessions or orders** through `before` or
   `session`. → Tasks 1 and 2, the tenant tests.
5. **Signing out, then signing in as someone else, must show nothing of the first
   user.** → Task 6, the test that the query cache is empty after sign-out.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/migrations/versions/<rev>_order_session.py` | `orders.session_id`, FK, index |
| `core/db/models.py`, `core/db/orders.py`, `core/execution.py` | The order records its session |
| `core/db/telemetry.py` | `list_evaluations` with `idle` and `before` |
| `core/db/proposals.py`, `core/rebalance.py` | `withdraw` with a version |
| `api/routes/history.py`, `api/routes/proposal.py`, `api/schemas.py` | The new parameters and fields |
| `web/openapi.json`, `web/src/api/schema.d.ts` | Regenerated |
| `web/src/lib/history.ts` | The words for a run and an order: pure |
| `web/src/lib/cadence.ts` | Custom cadence fields: the anchor's local form, validation |
| `web/src/api/queries.ts` | `useSessions`, `useSessionOrders`, `useSignOut` |
| `web/src/api/operations.ts` | Keys for the held confirmations, `useHeldOperation`, `isLostAnswer` |
| `web/src/features/history/` | `HistoryPage.tsx`, `SessionRow.tsx`, tests |
| `web/src/features/settings/` | `SettingsPage.tsx`, `KeyBlock.tsx`, `PortfolioBlock.tsx`, `AutomationBlock.tsx`, `PauseBlock.tsx`, tests |
| `web/src/features/onboarding/KeyForm.tsx` | The key form, extracted from `KeyStep` |
| `web/src/features/onboarding/automationValues.ts` | gains `settingsValues` |
| `web/src/test/fakePlatform.ts` | Sessions, orders, logout, the key's deletion, the dismissal's version |
| `web/e2e/settings.spec.ts` | The journey: change a cadence, see the next run move; History |

---

### Task 1: Orders belong to their session

**Files:**
- Create: `scripts/migrations/versions/<rev>_order_session.py`. Its `down_revision` is
  the current head (`alembic heads`).
- Modify: `core/db/models.py` (`Order`), `core/db/orders.py` (`record_attempt`,
  `list_orders`), `core/execution.py` (`_run`, `_evaluate`, `_send_all`, `_attempt`),
  `api/schemas.py` (`OrderOut`, `EvaluationOut`), `api/routes/history.py`
- Test: `tests/integration/test_orders.py`, `test_execution.py`, `test_schema.py`,
  `test_api_invest.py`, `test_api_tenant_isolation.py`

**Interfaces:**
- Produces:

```python
# core/db/models.py, Order
session_id: Mapped[uuid.UUID | None]  # FK sessions.id ON DELETE SET NULL; Index("ix_orders_session_id")
# core/db/orders.py
def record_attempt(..., attempted_at: datetime | None = None, session_id: uuid.UUID | None = None) -> Order
def list_orders(session, user_id, limit: int = 50, *, session_id: uuid.UUID | None = None) -> list[Order]
    # with session_id: that session's orders of this user, oldest first (created_at, cl_ord_id)
# api/schemas.py
class EvaluationOut: id: uuid.UUID  # added first
class OrderOut: session_id: uuid.UUID | None  # added after cl_ord_id
# GET /api/orders?session=<uuid>&limit=
```

- [ ] **Step 1: Write the failing tests.**

```python
def test_migration_adds_order_session_id(...)        # test_schema: column nullable, FK ondelete SET NULL
def test_an_invest_records_its_session_on_each_order(...)
    # test_execution: invest with two filled legs → both orders' session_id == the session row's id
def test_deleting_a_session_keeps_its_orders(...)     # delete_evaluations_before → order.session_id is None
def test_orders_of_a_session_are_oldest_first(...)    # test_api_invest: ?session=<id> lists the legs in send order
def test_sessions_carry_their_id(...)                 # GET /api/sessions rows have "id"
def test_another_users_session_lists_no_orders(...)   # tenant: user B ?session=<A's id> → []
```

- [ ] **Step 2: Run** `pytest tests/integration -k "session"`. Expected: FAIL.
- [ ] **Step 3: Implement.** Write the migration by hand: an additive column, an FK and
  an index. `_run` already holds `evaluation_id`. Pass it through `_evaluate` →
  `_send_all` → `_attempt` → `db.record_attempt(session_id=…)`.
- [ ] **Step 4: Regenerate the client** (Global Constraints). Run `pytest`, `ruff`, and
  `npm run check:generated` in `web/`. Expected: pass.
- [ ] **Step 5: Commit** `feat(api): an order records the session that placed it`

---

### Task 2: Sessions without the idle runs, a page at a time

**Files:**
- Modify: `core/db/telemetry.py` (`list_evaluations`), `api/routes/history.py`
- Test: `tests/integration/test_telemetry.py`, `test_api_invest.py`,
  `test_api_tenant_isolation.py`

**Interfaces:**
- Produces:

```python
def list_evaluations(session, user_id, limit: int = 50, *, idle: bool = True,
                     before: uuid.UUID | None = None) -> list[EvaluationSession]
    # order (started_at DESC, id DESC); idle=False drops status NOTHING_TO_DO;
    # before: rows strictly after that row in this order. Raises LookupError when
    # `before` is not one of this user's sessions.
# GET /api/sessions?limit=&idle=&before=   404 "that session no longer exists" on LookupError
```

- [ ] **Step 1: Write the failing tests.**

```python
def test_idle_false_leaves_out_nothing_to_do(...)      # DONE, NOTHING_TO_DO, PARTIAL → DONE, PARTIAL
def test_idle_defaults_to_every_run(...)               # no parameter → all three
def test_pages_neither_repeat_nor_skip_one_instant(...)
    # five sessions, three sharing started_at; limit=2, follow `before` → all five ids once, in order
def test_unknown_cursor_is_404(...)                    # before=<random uuid> → 404, detail exact
def test_another_users_cursor_is_404(...)              # tenant
```

- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Compare the cursor as a row value:
  `tuple_(started_at, id) < tuple_(cursor.started_at, cursor.id)`.
- [ ] **Step 4: Regenerate the client.** Run `pytest`, `ruff`, `npm run check:generated`.
- [ ] **Step 5: Commit** `feat(api): sessions without the idle runs, a page at a time`

---

### Task 3: A dismissal names the version it withdraws

**Files:**
- Modify: `core/db/proposals.py` (`get_proposal` gains `for_update`), `core/rebalance.py`
  (`withdraw`), `api/routes/proposal.py`, `web/src/features/proposal/ProposalPage.tsx`,
  `web/src/test/fakePlatform.ts`
- Test: `tests/integration/test_rebalance.py`, `test_api_rebalance.py`,
  `web/src/features/proposal/ProposalPage.test.tsx`

**Interfaces:**
- Produces:

```python
def get_proposal(session, user_id, *, for_update: bool = False) -> Proposal | None
def withdraw(context, user_id, version: int) -> bool
    # False: no live proposal. Raises StaleVersion(_state(slot)) when the live version differs.
# DELETE /api/proposal?version=N  → 204 | 404 | 409 {detail: "that is not the live version; read the proposal again", proposal}
#                                  | 422 without version
```

- In the application, Dismiss sends the version on screen. A `409` is handled as on
  approve. The page shows the live proposal from the body, with the notice "The
  proposal changed; review it again". A `404` stays "already gone" (phase 12).

- [ ] **Step 1: Write the failing tests.**

```python
def test_withdraw_with_the_live_version_withdraws(...)
def test_withdraw_with_an_old_version_is_409_and_keeps_it(...)  # body.proposal.version == live
def test_withdraw_without_a_version_is_422(...)
```

```ts
test("dismissing a proposal that changed shows the new one", ...)
  // fakePlatform proposal version 2, page rendered with version 1 → "Dismiss"
  // → "The proposal changed; review it again"; the legs of version 2; the proposal still live
test("dismiss sends the version on screen", ...)   // the DELETE's URL has ?version=1
```

- [ ] **Step 2: Run** `pytest -k withdraw` and `npm test -- ProposalPage`. Expected: FAIL.
- [ ] **Step 3: Implement** the platform side, then regenerate the client, then the page
  and `fakePlatform` (its `DELETE` reads `version` and answers `409` as approve does).
- [ ] **Step 4: Run** every platform and application command. Expected: pass.
- [ ] **Step 5: Commit** `feat: a dismissal names the version it withdraws`

---

### Task 4: History

**Files:**
- Create: `web/src/lib/history.ts`, `history.test.ts`,
  `web/src/features/history/SessionRow.tsx`, `HistoryPage.test.tsx`
- Modify: `web/src/features/history/HistoryPage.tsx`, `web/src/api/queries.ts`,
  `web/src/test/fakePlatform.ts` (`sessions: EvaluationOut[]`, `orders: OrderOut[]`,
  honouring `idle`, `before`, `limit`, `session`)

**Interfaces:**
- Consumes: `formatRun` (`lib/summary.ts`), `formatMoney`, `legLine`
  (`lib/operations.ts`), `LoadFailed`, `Skeleton`.
- Produces:

```ts
// lib/history.ts
type Session = components["schemas"]["EvaluationOut"];
type Order = components["schemas"]["OrderOut"];
export function runTitle(s: Pick<Session, "operation" | "trigger">): string;
export function runStatus(status: string): string;
export function messagesOf(log: string | null): string[];   // split on "\n", empty lines dropped
export function orderStatus(o: Pick<Order, "status" | "error">): string;
export function orderLine(o: Order, fiat: string): string;   // legLine of side, asset, requested_fiat
// api/queries.ts
export const SESSIONS_PAGE = 20;
export function useSessions(idle: boolean);       // useInfiniteQuery, key ["sessions", { idle }]
export function useSessionOrders(sessionId: string, enabled: boolean); // key ["orders", sessionId]
```

- **`runTitle` copy.** The operation: `INVEST` "Invest", `PROPOSE` "Rebalance check",
  `APPROVE` "Approved rebalance", `REBALANCE` "Automatic rebalance", `null` "Run". Then
  " · " and the trigger: `API` "by you", `SCHEDULER` "scheduled". A `null` trigger
  drops the separator. Example: "Invest · scheduled".
- **`runStatus` copy.** `DONE` "Done"; `NOTHING_TO_DO` "Nothing to do"; `PARTIAL`
  "Kraken refused some orders"; `STOPPED` "Stopped: an order's result was not known";
  `UNRESOLVED` "Waited for an earlier order"; `KRAKEN_UNAVAILABLE` "Kraken didn't
  answer"; `ERROR` "Failed"; `PROPOSED` "Proposal ready"; `SUPERSEDED` "The plan changed;
  nothing was sent"; `RUNNING` "Running". Any other status: the status itself.
- **`orderStatus` copy.** `FILLED` "Filled"; `PENDING` "Result not known yet"; `FAILED`
  with an error: "Refused by Kraken: {error}"; `FAILED` without one: "Not found on
  Kraken". Any other: the status itself.
- **The page.** Heading "History". The switch "Show runs with nothing to do" (Decision
  3). Each row shows `formatRun(started_at)`, `runTitle` and `runStatus`. A row is a
  button that expands it: its messages, then its orders. Each order shows `orderLine`,
  `orderStatus` and, when filled, "Cost {cost} · fee {fee}". The orders query starts only
  when the row expands. A session with no orders says "No orders are linked to this run."
  Below the list: "Load more" (Decision 3).
- **States.** Loading: three row skeletons. Error: `LoadFailed` with retry. Empty with
  the switch off: "No run has done anything yet. Turn on “Show runs with nothing to do”
  to see every run." Empty with it on: "Nothing has run yet."
- The fiat for amounts comes from `useConfig`.

- [ ] **Step 1: Write the failing tests.** `history.test.ts`: every copy row above,
  `null` operation and trigger included. `messagesOf(null)` is `[]`, and
  `messagesOf("a\n\nb")` is `["a", "b"]`. `HistoryPage.test.tsx`:

```ts
test("idle runs are hidden until asked for", ...)
  // fakePlatform: DONE invest, NOTHING_TO_DO invest → one row; switch on → two rows
test("a run expands into its messages and its orders", ...)
  // tap the row → its log lines; "Buy BTC for €50.00", "Filled", "Cost €50.00 · fee €0.13"
test("orders are read only when a run expands", ...)   // no GET /api/orders before the tap
test("load more continues after the last run", ...)
  // 25 sessions → 20 rows, "Load more" → 25 rows, the button gone; the second GET has before=<20th id>
test("no runs says why", ...)                           // both empty sentences
test("a failed read offers a retry", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the application commands. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): history`

---

### Task 5: A confirmation outlives its screen, and a lost answer says so

**Files:**
- Create: `web/src/api/operations.ts`, `operations.test.ts`
- Modify: `web/src/features/dashboard/InvestNow.tsx`, `InvestNow.test.tsx`,
  `web/src/features/proposal/ProposalPage.tsx`, `ProposalPage.test.tsx`,
  `web/src/components/OperationOutcome.tsx`

**Interfaces:**
- Produces:

```ts
export const investKey = ["operation", "invest"] as const;
export const approveKey = ["operation", "approve"] as const;
export const refreshAfterKey = ["operation", "refresh"] as const;
export function isLostAnswer(error: unknown): boolean;
  // true: not an ApiError (fetch failed), or ApiError 500 | 502 | 504
export function useHeldOperation<T>(key: readonly unknown[]): {
  state: "idle" | "pending" | "success" | "error";
  data: T | undefined;
  error: unknown;
  release: () => void;   // removes the mutation from the cache: the user closed it
};
  // the latest mutation in the cache with that key, read with useMutationState
```

- **How it is held.** The confirm mutations (`POST /api/invest`,
  `POST /api/proposal/approve`) take `investKey` and `approveKey`. The screen reads its
  step from `useHeldOperation`, not only from its own state. A screen that mounts while
  its operation is pending shows the pending button. One that mounts after the
  operation succeeded shows the outcome. "Close" calls `release`.
- **The refresh after a send** must run even when the screen is gone. The mutation's own
  `onSuccess` starts it through the `QueryClient`, as a mutation keyed `refreshAfterKey`:
  `client.getMutationCache().build(client, {mutationKey, mutationFn, onSuccess}).execute(undefined)`.
  On success it writes `portfolioKey`. `OperationOutcome` reads its error with
  `useHeldOperation(refreshAfterKey)`.
- **The lost answer** (Decision 6), in place of the error on the confirm step: "We don't
  know whether the orders were sent: the answer was lost. Check History before trying
  again." The message carries a link "Open History" to `/history`. The confirm button
  stays disabled until "Close".

- [ ] **Step 1: Write the failing tests.**

```ts
// operations.test.ts
test("a failed fetch and a 500, 502 or 504 are lost answers; a 503, 409 or 422 are not", ...)
// InvestNow.test.tsx
test("leaving while the invest is in flight keeps its outcome", ...)
  // fakePlatform delays POST /api/invest; tap Confirm; unmount Home; let it answer;
  // mount Home → "Every order was filled."; one POST /api/portfolio/refresh happened
test("a lost answer after confirm sends you to History", ...)
  // POST /api/invest → network error → the lost-answer sentence, a link to /history,
  // no "Confirm" enabled
test("closing an outcome forgets it", ...)   // Close, unmount, mount → the idle step
// ProposalPage.test.tsx
test("leaving while the approval is in flight keeps its outcome", ...)
test("a lost answer after approve sends you to History", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL; phase 12's still pass.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the application commands. Expected: pass, phase 12's double-tap
  tests included.
- [ ] **Step 5: Commit** `feat(web): a confirmation outlives its screen, and a lost answer says so`

---

### Task 6: The key, pause and sign out

**Files:**
- Create: `web/src/features/onboarding/KeyForm.tsx`,
  `web/src/features/settings/KeyBlock.tsx`, `PauseBlock.tsx`, `SettingsPage.test.tsx`
- Modify: `web/src/features/onboarding/KeyStep.tsx` (uses `KeyForm`),
  `web/src/features/settings/SettingsPage.tsx`, `web/src/api/queries.ts` (`useSignOut`),
  `web/src/features/dashboard/DashboardPage.tsx` (Decision 9),
  `web/src/test/fakePlatform.ts` (`DELETE /api/credentials`, `POST /api/auth/logout`,
  `paused`)

**Interfaces:**
- Produces:

```ts
export function KeyForm({ onAccepted }: { onAccepted: (reply: KeyAccepted) => void }): JSX.Element;
  // the two fields, "Verify & save", the refusal copy: moved from KeyStep unchanged
export function useSignOut(): { signOut: () => Promise<void>; pending: boolean; error: unknown };
  // POST /api/auth/logout → queryClient.clear() → navigate("/login", { replace: true })
```

- **Settings, top to bottom:** Portfolio, Automation (Task 7), Kraken key, Pause, then
  the signed-in email and "Sign out".
- **Kraken key.** "A key is saved, verified on {date}." uses phase 11's date format.
  Then "Replace key", which opens `KeyForm` and, once the key is accepted, phase 11's
  accepted view. Then "Delete key". The first tap shows "Without a key, CoinPilot stops
  investing and rebalancing until you save a new one." and "Confirm: delete key". With
  no key: "No key is saved. CoinPilot cannot trade until you save one.", and `KeyForm`
  is open.
- **Pause.** A switch, "Pause everything", with the sentence "While paused, nothing runs
  on schedule. Invest now and Rebalance now still work. On resume, a run whose time
  passed runs once." Each change sends `PATCH /api/config` `{paused}`.
- **Home**, when `paused` is true, shows "Automation is paused." above the account value,
  with a link "Resume in Settings" to `/settings`.

- [ ] **Step 1: Write the failing tests.**

```ts
test("the key is replaced only by one Kraken accepts", ...)
  // replace → fakePlatform refuses → the refusal; status still registered
test("deleting the key takes a second tap", ...)
  // "Delete key" → no DELETE yet → "Confirm: delete key" → one DELETE → "No key is saved…"
test("pause is saved and shown on Home", ...)
  // switch → PATCH {paused: true}; Home shows "Automation is paused."
test("sign out forgets everything", ...)
  // tap "Sign out" → POST /api/auth/logout → at /login; queryClient.getQueryCache().getAll() is empty
test("a failed sign out stays on Settings", ...)   // logout 500 → still on Settings, an error shown
```

  Phase 11's `KeyStep` tests pass unchanged.
- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the application commands. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): settings hold the key, pause and sign out`

---

### Task 7: Portfolio and automation in settings

**Files:**
- Create: `web/src/features/settings/PortfolioBlock.tsx`, `AutomationBlock.tsx`, a test
  for each
- Modify: `web/src/features/onboarding/automationValues.ts` (`settingsValues`),
  `automationValues.test.ts`, `web/src/features/settings/SettingsPage.tsx`

**Interfaces:**
- Consumes: `PortfolioForm`, `AutomationForm` (`onSaved`), `summarize`, `formatRun`
  (`lib/summary.ts`), `useAssets`, `useConfig`, `invalidateAccount`.
- Produces:

```ts
export function settingsValues(config: Config, today: string): AutomationValues;
  // Decision 10: readInvest / readRebalance of the stored fields; switches and thresholds as stored
```

- **Portfolio summary.** One line per managed asset, "{asset} {target} %", then
  "Cash {cash_target_pct} %", all from `GET /api/assets`. Then "Edit targets". It opens
  `PortfolioForm`. Its `onSaved` invalidates the account and closes the form. The fiat is
  shown with "Currency: {fiat}. It cannot be changed." With no managed asset: "No asset
  is managed yet."
- **Automation summary.** `summarize(config)` (phase 11's sentences). Then "Next invest:
  {formatRun(next_invest_at)}" and "Next rebalance: {formatRun(next_rebalance_at)}". A
  `null` time drops its line. Then "Edit automation", which opens `AutomationForm` with
  `settingsValues`. Its `onSaved` invalidates `configKey`, waits for the refetch and
  closes the form, so the moved next runs are shown.
- "Cancel" closes either form without sending.

- [ ] **Step 1: Write the failing tests.**

```ts
test("settings values keep a stored MIN rebalance as custom", ...)   // automationValues.test.ts
test("settings values keep switches and thresholds as stored", ...)
test("changing a cadence moves the next run", ...)
  // fakePlatform: PATCH with an invest cadence sets next_invest_at; weekly → monthly →
  // save → "Next invest: Sunday 1 November at 12:00" (fixed clock)
test("editing targets reads Kraken only when opened", ...)  // no POST /api/portfolio/refresh before "Edit targets"
test("a saved target shows in the summary", ...)            // BTC 30 → 35 → save → "BTC 35 %"
test("cancel sends nothing", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the application commands. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): portfolio and automation in settings`

---

### Task 8: A custom cadence is editable

**Files:**
- Modify: `web/src/lib/cadence.ts`, `cadence.test.ts`,
  `web/src/features/onboarding/AutomationForm.tsx`, `AutomationStep.test.tsx`,
  `web/src/features/settings/AutomationBlock.test.tsx`

**Interfaces:**
- Changes: `CadenceForm<C> = { kind: "choice"; choice: C; date: string } | { kind: "custom"; fields: CadenceFields }`.
  `readInvest` and `readRebalance` return the fields they could not express.
- Produces, in `lib/cadence.ts`:

```ts
export function anchorInput(iso: string | null): string;          // UTC ISO → "YYYY-MM-DDTHH:mm" local; null → ""
export function anchorFromInput(text: string): string | null;     // local → UTC ISO; null when not a usable date-time
export type CustomErrors = { days: string | null; months: string | null; anchor: string | null };
export function checkCustom(fields: CadenceFields): CustomErrors;
export function sameFields(a: CadenceFields, b: CadenceFields): boolean;
```

- **`checkCustom` copy.** Days outside 0–3650 or not whole: "Enter whole days from 0 to
  3650." Months outside 0–120 or not whole: "Enter whole months from 0 to 120." An
  `INTERVAL` with days and months both 0, on `days`: "Choose at least one day or one
  month." An `INTERVAL` without an anchor: "Choose when it starts." `MIN` checks nothing.
- **The form** (Decision 11). Under a cadence select showing "Custom", the fields appear:
  a select "Repeats", with "Every 15 minutes" (`MIN`) and "On an interval" (`INTERVAL`).
  With an interval, "Days", "Months" and "Starts" (`datetime-local`) follow. Each error
  shows next to its field (spec §7). The custom cadence is sent when `!sameFields(edited,
  initial)`, through `cadencePatch`. The hint "Set through the API; kept unless you
  choose another option." becomes "Set through the API. Edit its fields, or choose
  another option."

- [ ] **Step 1: Write the failing tests.** `cadence.test.ts`:

```ts
test("the anchor round-trips through the local input", ...)
  // "2026-10-27T11:00:00.000Z" ↔ "2026-10-27T12:00" (Madrid, CET)
test("the anchor input crosses daylight saving", ...)
  // "2026-07-01T10:00:00.000Z" ↔ "2026-07-01T12:00" (CEST)
test("custom checks name the field at fault", ...)  // every copy row; MIN with days -1 → no errors
test("a cadence read that the select cannot express keeps its fields", ...)
```

  `AutomationBlock.test.tsx`:

```ts
test("a custom cadence's fields are edited and sent", ...)
  // INTERVAL 10 days → 14 → save → PATCH has invest_interval_days 14, mode, months, anchor
test("an untouched custom cadence is not sent", ...)   // phase 11's rule, kept
test("an interval of nothing is refused before sending", ...)  // days 0 months 0 → the error, no PATCH
```

  Phase 11's `"a custom cadence is kept unless changed"` passes.
- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the application commands. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): a custom cadence is editable`

---

### Task 9: History and settings end to end

**Files:**
- Create: `web/e2e/settings.spec.ts`
- Modify: `web/e2e/mockApi.ts` (sessions, orders, logout, the config's next runs),
  `docs/plans/ROADMAP.md`

- [ ] **Step 1: Write the journeys.**

```ts
test("a cadence changed in settings moves the next run", ...)
  // Settings → "Edit automation" → invest Weekly → Monthly → save → the "Next invest" line changes
test("history shows a run and its orders", ...)
  // History → the invest row → its order "Filled"; the switch reveals a "Nothing to do" row
test("sign out lands on the sign-in page", ...)
```

- [ ] **Step 2: Run** `npm run e2e`. Expected: phases 10 to 12's tests and these 3 pass.
- [ ] **Step 3: Update** the roadmap's status for phase 13 to "In review".
- [ ] **Step 4: Commit** `test(web): history and settings end to end`

---

## What you verify after the deploy

The migration only adds a column, so a rollback to phase 12's image still works against
the migrated database.

1. Deploy. Open History on the phone. Your runs are listed without the idle ones. The
   switch shows them, and "Load more" goes back further.
2. Expand an invest run that placed orders after the deploy. Its orders are listed. A
   run from before the deploy shows "No orders are linked to this run.": its orders have no session.
3. In Settings, change the invest cadence. "Next invest" moves to the new date.
   `GET /api/config` in `/api/docs` agrees.
4. Pause. Home says so, and no scheduled run appears in History while paused. Resume.
5. Replace the key with the same key: it is accepted and the status date changes. Do
   not delete it unless you mean to.
6. Sign out, sign in again, and land on Home.
