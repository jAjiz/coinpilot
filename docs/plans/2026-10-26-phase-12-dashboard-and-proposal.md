# Phase 12 — Dashboard and proposal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Home shows what the account is worth and how far each managed asset is from
its target, and lets the user read Kraken again, invest free cash now, and request a
rebalance; a pending proposal is reviewed, approved or dismissed on its own page.

**Architecture:** The arithmetic Home adds to the API (totals, drift, a proposal's order
count and total) and the copy for legs and outcomes are pure functions in
`web/src/lib/`. Home is `features/dashboard/`, one component per block, reading
`usePortfolio` and `useProposal` and writing through TanStack Query mutations. The
proposal is `features/proposal/ProposalPage.tsx` at `/proposal`, inside the shell, with no
tab. Component tests run against `fakePlatform`, which gains the snapshot, the
operations and the proposal. The phase changes no platform code.

**Tech Stack:** As phase 11. No new dependency.

**Spec:** [`docs/specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md). This
phase covers §4.1 (`/proposal`), §4.5 (account totals), §6.1, §6.2, §7 (the states, the
`409`s, the `503`, offline, and the two-tap rule for money) and §8 (unit tests for the new
`lib/` functions; component tests for the version conflict and the double-tap guard; the
dashboard journey end to end).

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md), phase 12.

## Global Constraints

- **No amount or percentage is a JavaScript `number`** (spec §4.5). They stay decimal
  strings; arithmetic goes through `lib/decimal.ts` (`big.js`). A bar's width is the
  string itself in a CSS `%`, never `Number(...)`.
- **No new dependency.** No new shadcn component is needed; if one is, it is added with
  `npx shadcn@latest add <name>`.
- **Actions that move money (invest, approve) show what they will do first and take a
  second tap to confirm** (spec §7).
- **Every button that sends is disabled while its request is in flight and while
  `useOnline()` is false** (spec §7). A double tap never sends twice.
- **No `/api` response is cached by the service worker** (spec §7); phase 10's
  configuration already does this and must stay unchanged.
- **Times are the browser's time zone**, told with `formatRun` (`lib/summary.ts`). Tests
  run in `Europe/Madrid`.
- **English copy. Copy quoted in this plan is exact.** The page heading stays "Home":
  phase 10's and 11's tests read it.
- Phase 10's rules hold: no inline `<script>`, no resource from another origin, LF in
  `web/**`, the generated client unchanged (`npm run check:generated`).
- **No secret, host name or IP address in the repository.**
- Commit messages follow Conventional Commits and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Commands, from `web/`:

```bash
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build && npm run check:build && npm run check:generated
npm run e2e
```

## What the platform answers

Read from `api/routes/{portfolio,invest,proposal}.py`, `api/evaluation.py` and
`api/schemas.py`. The types are `components["schemas"][…]` in `web/src/api/schema.d.ts`.

| Call | Answer |
|---|---|
| `GET /api/portfolio` | `PortfolioOut`, the last snapshot; `404` when none was taken |
| `POST /api/portfolio/refresh` | `PortfolioOut`, read now; `503` "kraken did not return …; nothing was recorded" |
| `POST /api/invest?preview=true` | `InvestOut`, `status` `PREVIEW` or `NOTHING_TO_DO`; legs `VALIDATED`, `REJECTED`, `SKIPPED` or `UNCHECKED` |
| `POST /api/invest` | `InvestOut`, `status` `DONE`, `PARTIAL`, `STOPPED`, `ERROR` or `NOTHING_TO_DO`; legs `FILLED`, `FAILED`, `PENDING` or `SKIPPED` |
| `POST /api/rebalance` | `RebalanceOut`, `status` `PROPOSED` (with `proposal`) or `NOTHING_TO_DO` (`messages` say why); never sends |
| `GET /api/proposal` | `ProposalOut` (the live one); `404` "there is no live proposal" |
| `POST /api/proposal/approve` `{version}` | `RebalanceOut` with the legs sent; `409` with `{detail, proposal}` (and `messages` when superseded) when the version is not the live one or the plan changed; `404` without a proposal |
| `DELETE /api/proposal` | `204`; `404` without a proposal |
| any evaluation | `409` "an evaluation of this account is already running; try again shortly"; `409` "an earlier order is still unresolved; try again in a few minutes"; `503` "kraken could not be read; nothing was sent" |

Two facts shape the screens:

- `PortfolioOut.total_value` is **managed assets plus cash**, the denominator of every
  weight. Unmanaged holdings carry a `value` when priced; locked ones never do.
- **Every evaluation keeps a snapshot of the account before it trades** (`core/execution.py`,
  `keep_snapshot`). After orders were sent, `GET /api/portfolio` still shows the account
  as it was before them.

A proposal leg with a `note` is skipped (below Kraken's minimum, for example); one with
`note: null` is an order that approval sends.

## Decisions this plan takes

The spec leaves these open. Each is settled here so that no task has to guess.

1. **Home shows the last snapshot and reads Kraken only on request.** Opening Home calls
   `GET /api/portfolio`; the time of the read is on screen, and "Refresh" calls
   `POST /api/portfolio/refresh`. Opening the application never calls Kraken.
2. **"Managed" includes cash.** It is `total_value` as the platform computes it;
   "unmanaged" is the sum of the priced unmanaged holdings; the total is both. Locked
   balances have no value and are counted in neither, which the screen says.
3. **A row is highlighted when the engine would act on it:** its drift is not zero and
   its absolute value is **at least** `min_drift_pct` (`engine/reconcile.py`, `>=`). The
   spec says "above"; the screen follows the engine so that the highlighted rows are the
   ones a rebalance would trade. The cash row is never highlighted: cash is what is left,
   not an asset the engine orders.
4. **After an operation that sent anything** (a leg `FILLED` or `PENDING`), the
   application refreshes the portfolio itself, through the same mutation as the Refresh
   button. Otherwise Home would show the pre-trade snapshot as the current account.
5. **The busy `409` gets the spec's sentence; every other refusal is the platform's
   detail.** "An earlier order is still unresolved" is a different condition and keeps its
   own words. A `503` from any operation, the refresh included, gets the spec's sentence.
6. **"Rebalance now" opens the proposal when one is proposed**, and stays on Home with the
   platform's `messages` when there is nothing to rebalance.
7. **An outcome stays on screen until the user leaves it.** After an approval the
   proposal no longer exists, and after an invest the preview is gone; the result is held
   in the component's state, not read from a query, so a refetch cannot replace it.
8. **Dismiss takes one tap.** It sends nothing and a rebalance can be requested again.

## Review Focus

1. **A double tap on a confirmation sends one request.** The second tap lands while the
   first request is in flight. → Task 4 and Task 6, the double-tap tests count the
   requests in `fakePlatform`.
2. **A version conflict must not leave the old legs on screen with Approve armed.** The
   `409` carries the live proposal; the page shows it, the confirmation closes, and the
   notice says to review it again. A conflict whose `proposal` is `null` (the drift is
   gone) ends on the empty state, with the notice. → Task 6.
3. **An old snapshot or an unpriced asset must render.** `cash_target_pct` and
   `cash_weight_pct` are `null` on a snapshot from before phase 9; a managed asset whose
   pair has no price has `value` and `weight_pct` `null`. Neither is a crash or `NaN`. →
   Task 1 (`allocationRows`), Task 2 (the rendering tests).
4. **"Already running" and "unresolved" are different `409`s.** Telling a user with an
   unresolved order to "try again in a moment" sends them into a loop. → Task 1
   (`operationError`).
5. **After money moved, Home must not show the old balances as current.** → Task 4 and
   Task 6, which assert the refresh `POST` after a send and none after a preview.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/account.ts` | `accountTotals`, `allocationRows`, `drift`, `isDrifted`, `formatDrift`, `proposalTotals`: pure |
| `web/src/lib/operations.ts` | `legLine`, `legStatus`, `outcomeSentence`, `countOrders`, `sentAnything`: pure copy |
| `web/src/api/client.ts` | gains `operationError` |
| `web/src/api/queries.ts` | gains `portfolioKey`/`usePortfolio`, `proposalKey`/`useProposal`, `useRefreshPortfolio` |
| `web/src/components/LegList.tsx` | The legs of an operation, each with its line and status |
| `web/src/features/dashboard/` | `DashboardPage.tsx`, `AccountValue.tsx`, `Allocation.tsx`, `ProposalCard.tsx`, `InvestNow.tsx`, `RebalanceNow.tsx`, a test per block |
| `web/src/features/proposal/` | `ProposalPage.tsx`, `ProposalPage.test.tsx` |
| `web/src/routes.tsx` | `/proposal` inside the shell |
| `web/src/test/fakePlatform.ts` | The snapshot, the operations and the proposal |
| `web/e2e/dashboard.spec.ts` | The journey Home → rebalance → approve, and invest now |

---

### Task 1: Totals, drift and the words for operations

**Files:**
- Create: `web/src/lib/account.ts`, `account.test.ts`, `web/src/lib/operations.ts`,
  `operations.test.ts`
- Modify: `web/src/api/client.ts` (`operationError`), `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: `sum`, `subtract`, `compare`, `formatMoney`, `formatPercent` (`lib/decimal.ts`);
  `ApiError`, `describeError` (`api/client.ts`).
- Produces, in `lib/account.ts`:

```ts
type Portfolio = components["schemas"]["PortfolioOut"];
type ProposalLeg = components["schemas"]["ProposalLegOut"];
export type Totals = { managed: string; unmanaged: string; total: string };
export function accountTotals(portfolio: Portfolio): Totals;
  // Decision 2: managed = total_value; unmanaged = Σ value of holdings with
  // managed false and a value; total = managed + unmanaged
export type AllocationRow = {
  kind: "asset" | "cash";
  asset: string;               // the code; "Cash" for the cash row
  weight: string | null;
  target: string | null;
  drift: string | null;        // weight − target; null when either is null
  drifted: boolean;            // Decision 3; always false for cash
};
export function allocationRows(portfolio: Portfolio, minDrift: string): AllocationRow[];
  // the managed holdings in the API's order, then the cash row
  // (cash_weight_pct, cash_target_pct)
export function drift(weight: string, target: string): string;   // canonical, signed
export function isDrifted(drift: string, minDrift: string): boolean;
  // drift ≠ 0 and |drift| ≥ minDrift
export function formatDrift(drift: string): string;
  // "+2.5 pts", "-0.25 pts", "0 pts"
export function proposalTotals(legs: ProposalLeg[]): { orders: number; skipped: number; total: string };
  // orders: legs with note null; total: Σ their amount_fiat; skipped: the rest
```

- Produces, in `lib/operations.ts`:

```ts
type Leg = { side: string; asset: string; amount_fiat: string };
export function legLine(leg: Leg, fiat: string): string;
  // "Buy BTC for €50.00", "Sell ETH for €20.00" (side BUY/SELL, any case)
export function legStatus(leg: { status: string; error: string | null; note: string | null }): string;
export function outcomeSentence(status: string): string;
export function countOrders(n: number): string;        // "1 order", "0 orders", "3 orders"
export function sentAnything(legs: { status: string }[]): boolean;  // any FILLED or PENDING
```

- **`legStatus` copy**, `{x}` dropped with its colon when `null`:
  `VALIDATED` "Kraken accepts it"; `REJECTED` "Kraken refuses it: {error}";
  `SKIPPED` "Skipped: {note}"; `UNCHECKED` "Not checked by Kraken"; `FILLED` "Filled";
  `FAILED` "Failed: {error}"; `PENDING` "Sent; the result is not known yet"; any other
  status, the status itself.
- **`outcomeSentence` copy:** `DONE` "Every order was filled."; `PARTIAL` "Kraken refused
  some orders; the others were filled."; `STOPPED` "The result of an order is not known
  yet. CoinPilot checks it before the next operation."; `ERROR` "The operation failed.
  Nothing more was sent."; `NOTHING_TO_DO` "Nothing to do."; `PROPOSED` "A rebalance is
  waiting for your approval."; any other, the status itself.
- Produces, in `api/client.ts`:

```ts
export function operationError(error: unknown): string;
  // Decision 5: ApiError 409 whose detail is exactly
  //   "an evaluation of this account is already running; try again shortly"
  //   → "An operation is already running; try again in a moment."
  // ApiError 503 → "Kraken didn't answer; nothing was changed."
  // otherwise describeError(error)
```

  The busy detail is a named constant with a comment pointing at `api/evaluation.py`.

- [ ] **Step 1: Write the failing tests.** `account.test.ts`:

```ts
test("managed includes cash, unmanaged is the priced rest", ...)
  // total_value "1000", cash "100"; holdings BTC managed value "600",
  // XRP unmanaged value "50", DOGE unmanaged value null, "DOT.S" locked value null
  // → { managed: "1000", unmanaged: "50", total: "1050" }
test("rows are the managed assets in the API's order, then cash", ...)
  // BTC weight "32.5" target "30", ETH weight "57.5" target "60", XRP unmanaged;
  // cash weight "10" target "10" → kinds/assets [asset BTC, asset ETH, cash "Cash"],
  // drifts "2.5", "-2.5", "0"
test("a drift at the threshold is highlighted, below it is not", ...)
  // min "2.5": BTC +2.5 → drifted; min "2.6" → not drifted
test("no threshold highlights every asset off its target, not one on it", ...)
  // min "0": drift "0.01" → true; drift "0" → false
test("cash is never highlighted", ...)        // cash drift "-15", min "1" → false
test("an old snapshot and an unpriced asset give no drift", ...)
  // cash_weight_pct null, cash_target_pct null; managed SOL weight null target "5"
  // → cash row weight null, drift null, drifted false; SOL drift null, drifted false
test("drift is told in signed points", ...)  // "2.5" "+2.5 pts"; "-0.25" "-0.25 pts"; "0" "0 pts"
test("a proposal counts its orders and leaves the skipped out of the total", ...)
  // legs BTC buy "50" note null, ETH sell "20.5" note null, SOL buy "3" note "below kraken's minimum"
  // → { orders: 2, skipped: 1, total: "70.5" }
```

  `operations.test.ts`: every `legStatus` and `outcomeSentence` row above, `null` error
  and note included; `legLine({ side: "BUY", asset: "BTC", amount_fiat: "50" }, "EUR")`
  is "Buy BTC for €50.00"; `countOrders` 0, 1, 2; `sentAnything` true for
  `FILLED`, true for `PENDING`, false for `[FAILED, SKIPPED]` and `[]`.
  `client.test.ts`: the busy `409`; the unresolved `409` keeps
  "an earlier order is still unresolved; try again in a few minutes"; a `503`; a
  `TypeError` → "The connection failed.".

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, `npm run typecheck`, `npm run lint`. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): account totals, drift and the words for operations`

### Task 2: Home reads the account

**Files:**
- Create: `web/src/features/dashboard/AccountValue.tsx`, `Allocation.tsx`,
  `DashboardPage.test.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`, `web/src/api/queries.ts`,
  `web/src/test/fakePlatform.ts`, `web/src/test/fakePlatform.test.ts`;
  `web/src/features/shell/AppShell.test.tsx` and `web/src/features/auth/guards.test.tsx`
  (handlers only)

**Interfaces:**
- Consumes: Task 1 (`accountTotals`, `allocationRows`, `formatDrift`, `operationError`);
  `formatMoney`, `formatPercent`, `formatRun`; `useConfig`, `useOnline`.
- Produces, in `api/queries.ts`:

```ts
export const portfolioKey = ["portfolio"] as const;
export const proposalKey = ["proposal"] as const;
export type Portfolio = components["schemas"]["PortfolioOut"];
export type Proposal = components["schemas"]["ProposalOut"];
export function usePortfolio();          // Portfolio | null: a 404 resolves to null
export function useProposal();           // Proposal | null: a 404 resolves to null
export function useRefreshPortfolio();   // useMutation over POST /api/portfolio/refresh;
                                         // on success, setQueryData(portfolioKey, data)
```

  `useConfig`'s 404-to-null becomes a shared helper the three queries use.
- Produces, in `test/fakePlatform.ts`, new `FakeState` fields with these defaults:

```ts
snapshot: Portfolio | null;      // GET /api/portfolio; null → 404
                                 // "no snapshot yet; POST /api/portfolio/refresh to take one"
proposal: Proposal | null;       // GET /api/proposal; null → 404 "there is no live proposal"
```

  The existing refresh handler also stores its answer in `state.snapshot`. Tasks 4–6 add
  their own fields.
- Tests that render `/` with hand-written handlers (`AppShell.test.tsx`,
  `guards.test.tsx`) add `GET /api/portfolio` and `GET /api/proposal` answering `404`, so
  no request goes unhandled. No assertion of theirs changes.

- **`DashboardPage`:** the `h1` "Home", then `AccountValue`, `Allocation`, and (Tasks 3–5)
  `ProposalCard`, `InvestNow`, `RebalanceNow`. The heading renders in every state.
- **`AccountValue`.** Label "Account value", then `formatMoney(total)` large. Below it
  "Managed {managed} · unmanaged {unmanaged}". When a holding is locked: "Locked
  balances (staked or reserved) are not valued." Then "Read {formatRun(as_of)}" and a
  "Refresh" button; while it runs, "Reading Kraken…". A failed refresh shows
  `operationError` in a `FormError` and keeps the last snapshot on screen.
  - Loading: skeleton blocks in the shape of the value and three rows.
  - Empty (`null`): "Your account has not been read yet." and the "Refresh" button.
  - Error: `describeError` and "Try again", which refetches.
- **`Allocation`.** Heading "Allocation". A list; each row is an `li` with
  `aria-label` its asset (or "Cash"), showing the asset, "{formatPercent(weight)} ·
  target {formatPercent(target)}", and `formatDrift(drift)`. A bar: a track, a fill of
  `width: {weight}%` (clamped to 0–100 with `compare`), and a mark at `left: {target}%`.
  A drifted row has `data-drifted="true"` and its drift in the warning colour. A row with
  no weight says "No price in {fiat}" (asset) or "Not recorded in this reading" (cash)
  and has no bar. `min_drift_pct` comes from `useConfig`. Nothing is listed while the
  portfolio is loading, empty or failed: `AccountValue` carries those states.

- [ ] **Step 1: Write the failing tests** in `DashboardPage.test.tsx`, with a
  `fakePlatform` whose config is onboarded (`onboarded_at` set, `fiat` "EUR",
  `min_drift_pct` "2") and a snapshot built by a local helper:

```ts
test("the account's value, split into managed and unmanaged", ...)
  // total_value "1000", XRP unmanaged value "50" → "€1,050.00",
  // "Managed €1,000.00 · unmanaged €50.00", "Read Tuesday 20 October at 12:00"
test("locked balances are said to be unvalued", ...)
test("each managed asset and cash have a row with weight, target and drift", ...)
  // BTC 32.5/30, ETH 57.5/60, cash 10/10 → within the BTC row "32.5 % · target 30 %", "+2.5 pts"
test("rows drifted past the threshold are highlighted", ...)
  // BTC and ETH data-drifted "true"; cash has none; with min "3", none
test("an asset with no price and a snapshot without cash percentages still render", ...)
test("an account never read offers a refresh", ...)
  // snapshot null → "Your account has not been read yet." → "Refresh" →
  // POST /api/portfolio/refresh → "€…" shown
test("refresh reads Kraken and shows the new reading", ...)
test("an unreachable Kraken on refresh keeps the last reading", ...)
  // refresh 503 → "Kraken didn't answer; nothing was changed." and the old value still shown
test("a failed load offers a retry", ...)                // GET /api/portfolio 500
test("refresh is disabled while offline", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass, phase 10's and 11's tests
  included.
- [ ] **Step 5: Commit** `feat(web): Home shows the account and its allocation`

### Task 3: The proposal card and the proposal page

**Files:**
- Create: `web/src/features/dashboard/ProposalCard.tsx`, `ProposalCard.test.tsx`,
  `web/src/features/proposal/ProposalPage.tsx`, `ProposalPage.test.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`, `web/src/routes.tsx`,
  `web/src/test/fakePlatform.ts`

**Interfaces:**
- Consumes: `useProposal`, `proposalKey` (Task 2); `proposalTotals`, `countOrders`,
  `legLine` (Task 1); `formatMoney`, `formatRun`.
- Produces: the route `/proposal` → `ProposalPage`, a child of `AppShell` beside `/`
  (no tab is active on it). `fakePlatform` answers `DELETE /api/proposal` (`204` and
  `state.proposal = null`; `404` without one).
- **`ProposalCard`**, only when `useProposal` holds a proposal: heading "Rebalance
  proposal", "{countOrders(orders)} for {formatMoney(total)}", "Proposed
  {formatRun(updated_at)}", and a "Review" link to `/proposal`. Nothing while loading,
  empty or failed: Home stays usable without it.
- **`ProposalPage`.** Heading "Proposal".
  - Loading: skeleton rows. Error: `describeError` and "Try again". Empty: "There is no
    proposal to review." and a "Back to Home" link.
  - Otherwise: "Proposed {formatRun(updated_at)}, {by your schedule | on request}" for
    `trigger` `SCHEDULED` | `MANUAL`. Under "Orders", one `li` per leg with `note` null:
    `legLine(leg, fiat)`. Then "Total {formatMoney(total)}". When a leg has a note, under
    "Skipped", `legLine` and the note. When there is no order: "Every order is below
    Kraken's minimum, so nothing can be sent."
  - "Dismiss" → `DELETE /api/proposal`, then the proposal query is invalidated and the
    page navigates to `/`. A `404` is treated the same: the proposal is already gone. While
    it runs, "Dismissing…". Other errors: `operationError` in a `FormError`.
  - Task 6 adds Approve.

- [ ] **Step 1: Write the failing tests:**

```ts
// ProposalCard.test.tsx, at "/"
test("a live proposal is announced on Home", ...)
  // legs BTC buy "50", ETH sell "20.5", SOL buy "3" with a note →
  // "2 orders for €70.50", "Review" → /proposal, heading "Proposal"
test("without a proposal there is no card", ...)
// ProposalPage.test.tsx, at "/proposal"
test("every order is listed with its side, asset and amount", ...)
  // "Buy BTC for €50.00", "Sell ETH for €20.50", "Total €70.50"
test("a skipped leg is shown with its note", ...)      // "Skipped", "below kraken's minimum"
test("a proposal from the schedule says so", ...)      // trigger SCHEDULED → "by your schedule"
test("without a proposal the page says so", ...)
test("dismiss withdraws the proposal and goes Home", ...)
  // requests DELETE /api/proposal; → "/"; no "Rebalance proposal" card
test("a proposal already gone is dismissed all the same", ...)   // DELETE 404 → "/"
test("dismiss is disabled while offline", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): the proposal, announced on Home and shown on its page`

### Task 4: Invest now

**Files:**
- Create: `web/src/components/LegList.tsx`, `web/src/features/dashboard/InvestNow.tsx`,
  `InvestNow.test.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`, `web/src/test/fakePlatform.ts`

**Interfaces:**
- Consumes: `legLine`, `legStatus`, `outcomeSentence`, `sentAnything`, `operationError`
  (Task 1); `useRefreshPortfolio`, `useConfig` (Task 2); `sum`, `formatMoney`; `useOnline`;
  `FormError`.
- Produces: `<LegList legs fiat />` — a list, one `li` per leg: `legLine` and
  `legStatus`. Task 6 uses it for an approval's outcome.
- Produces, in `fakePlatform`:

```ts
investPreview: InvestOut;   // POST /api/invest?preview=true
investResult: InvestOut;    // POST /api/invest
```

  Both recorded in `requests` with the path's query kept (`/api/invest?preview=true`), so
  a test can tell the two apart. Defaults: a `NOTHING_TO_DO` with no legs and the message
  "there is no free cash to invest".

- **Copy.** Heading "Invest now". "Invest the free {fiat} toward your targets. You see
  the orders before anything is sent." Button "Invest now" → `POST /api/invest?preview=true`;
  while it runs, "Asking Kraken…".
  - Preview with legs: `LegList`, then, when at least one leg is `VALIDATED`, "Total
    {formatMoney(Σ VALIDATED amount_fiat)}", "Prices move: the orders are computed again
    when you confirm.", and the buttons "Confirm: invest {total}" and "Cancel". When none
    is `VALIDATED`: "Kraken would accept none of these orders." and "Close".
  - Preview `NOTHING_TO_DO`: "Nothing to invest." and each of `messages` as a line, and
    "Close".
  - Confirm → `POST /api/invest`; while it runs, "Investing…". Then the outcome (Decision
    7): `outcomeSentence(status)`, `LegList`, each message, and "Close". When
    `sentAnything(legs)`, the portfolio is refreshed (Decision 4).
  - Cancel and Close return to the first state.
  - Any error: `operationError` in a `FormError`; the step that failed stays, so the user
    can try again.

- [ ] **Step 1: Write the failing tests:**

```ts
test("invest now previews before it sends", ...)
  // preview: legs BTC buy "60" VALIDATED, ETH buy "40" VALIDATED →
  // "Buy BTC for €60.00", "Kraken accepts it", "Confirm: invest €100.00";
  // requests hold POST /api/invest?preview=true and no POST /api/invest
test("confirming sends, shows the outcome and refreshes the account", ...)
  // result DONE, both FILLED → "Every order was filled."; requests, in order:
  // POST /api/invest?preview=true, POST /api/invest, POST /api/portfolio/refresh
test("a double tap on confirm sends once", ...)
  // the invest handler delayed; two clicks → one POST /api/invest
test("a rejected leg is not counted, and with none accepted there is no confirm", ...)
test("nothing to invest says why", ...)       // messages ["there is no free cash to invest"]
test("cancel sends nothing", ...)
test("an operation already running is explained", ...)
  // preview 409 busy → "An operation is already running; try again in a moment."
test("an unreachable Kraken is explained", ...)
  // confirm 503 → "Kraken didn't answer; nothing was changed."; Confirm still offered
test("an outcome that sent nothing does not refresh", ...)   // result ERROR, legs FAILED
test("invest now is disabled while offline", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): invest now, previewed and confirmed`

### Task 5: Rebalance now

**Files:**
- Create: `web/src/features/dashboard/RebalanceNow.tsx`, `RebalanceNow.test.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`, `web/src/test/fakePlatform.ts`

**Interfaces:**
- Consumes: `proposalKey` (Task 2); `operationError`, `outcomeSentence` (Task 1);
  `useOnline`; `FormError`.
- Produces, in `fakePlatform`: `rebalanceResult: RebalanceOut` for `POST /api/rebalance`;
  the handler sets `state.proposal` to its `proposal`. Default: `NOTHING_TO_DO`, no
  proposal, message "the drift is below the threshold".

- **Copy.** Heading "Rebalance now". "Compare the account with your targets. A rebalance
  is proposed for you to review; nothing is sent until you approve it." Button "Rebalance
  now"; while it runs, "Checking…".
  - `PROPOSED`: the proposal query is set from the answer's `proposal`, and the page
    navigates to `/proposal` (Decision 6).
  - `NOTHING_TO_DO`: "Nothing to rebalance." and each of `messages` as a line. The
    proposal query is invalidated: an evaluation that finds nothing may have withdrawn a
    proposal.
  - Error: `operationError` in a `FormError`.

- [ ] **Step 1: Write the failing tests:**

```ts
test("a rebalance found opens the proposal", ...)
  // rebalanceResult PROPOSED with a proposal of 2 orders → /proposal, "Buy BTC for €50.00"
test("nothing to rebalance says why and stays on Home", ...)
  // "Nothing to rebalance.", "the drift is below the threshold"; still "/"
test("an evaluation that finds nothing removes the old card", ...)
  // state.proposal set; rebalanceResult NOTHING_TO_DO clears it in the handler →
  // the "Rebalance proposal" card disappears
test("an operation already running is explained", ...)
test("an unresolved order keeps the platform's words", ...)
  // 409 "an earlier order is still unresolved; try again in a few minutes" → that text
test("rebalance now is disabled while it runs and while offline", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): rebalance now opens the proposal`

### Task 6: Approve

**Files:**
- Modify: `web/src/features/proposal/ProposalPage.tsx`, `ProposalPage.test.tsx`,
  `web/src/test/fakePlatform.ts`

**Interfaces:**
- Consumes: `LegList` (Task 4); `outcomeSentence`, `sentAnything`, `operationError`,
  `countOrders` (Task 1); `useRefreshPortfolio`, `proposalKey` (Task 2).
- Produces, in `fakePlatform`: `approveResult: RebalanceOut` for
  `POST /api/proposal/approve`. The handler answers `404` without a proposal; `409`
  `{ detail: "that is not the live version; read the proposal again", proposal: state.proposal }`
  when the body's `version` is not `state.proposal.version`; otherwise `approveResult`,
  and `state.proposal = null`. Default: `DONE` with every order `FILLED`.

- **Copy.** Below the orders, when there is at least one: "Approve". It opens the
  confirmation in place: "Send {countOrders(orders)} for {formatMoney(total)}?",
  "Confirm" and "Cancel". Confirm → `POST /api/proposal/approve` with the `version` on
  screen; while it runs, "Sending…".
  - `200`: the outcome replaces the proposal (Decision 7): `outcomeSentence(status)`,
    `LegList`, each message, and "Back to Home". The proposal query is invalidated; when
    `sentAnything(legs)`, the portfolio is refreshed.
  - `409` whose body has a `proposal` key: the proposal query is set to it (`null`
    included), the confirmation closes, and the notice "The proposal changed; review it
    again." stays above the page with each of the body's `messages`, until the next
    Approve or Dismiss. With `null`, the page shows its empty state under the notice.
  - `404`: the proposal query is set to `null`; the page shows its empty state.
  - Other errors: `operationError` in a `FormError`; the confirmation stays open.

- [ ] **Step 1: Write the failing tests:**

```ts
test("approving asks first, then sends the version on screen", ...)
  // proposal version 3: "Approve" → "Send 2 orders for €70.50?" → no request yet →
  // "Confirm" → request body { version: 3 }
test("an approval shows what was sent and refreshes the account", ...)
  // → "Every order was filled.", "Buy BTC for €50.00" "Filled"; requests end with
  // POST /api/portfolio/refresh; "Back to Home" → "/" with no proposal card
test("a double tap on confirm sends once", ...)
test("a new version is shown for a new review", ...)
  // the page read version 3; state.proposal becomes version 4 with other legs before
  // Confirm → 409 → "The proposal changed; review it again.", version 4's legs shown,
  // the confirmation closed; Approve → Confirm sends { version: 4 }
test("a proposal withdrawn under the user ends on the empty page with the notice", ...)
  // 409 { detail, proposal: null, messages: ["the drift is below the threshold"] } →
  // the notice, that message, "There is no proposal to review."
test("a partial approval says so", ...)
  // PARTIAL, one FILLED, one FAILED "EOrder:Insufficient funds" →
  // "Kraken refused some orders; the others were filled.", "Failed: EOrder:Insufficient funds"
test("cancel sends nothing", ...)
test("approve is disabled while offline", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): approve a proposal, with its version`

### Task 7: The dashboard journey end to end

**Files:**
- Create: `web/e2e/dashboard.spec.ts`
- Modify: `docs/plans/ROADMAP.md` (phase 12's status: "In review"; it becomes "Done (#N)"
  when the pull request is merged)

**Interfaces:**
- Consumes: `mockApi` (`e2e/mockApi.ts`), unchanged. The test keeps its own state (the
  proposal, then none), as phase 11's journey does. Nothing reaches a platform.

- [ ] **Step 1: Write the journey:**

```ts
test("an onboarded user reads the account, requests a rebalance and approves it", ...)
  // config onboarded, EUR, min_drift_pct "2"; GET /api/portfolio a snapshot with BTC
  // 32.5/30 and ETH 57.5/60; GET /api/proposal 404 until the rebalance.
  // / "Home": "€1,000.00", the BTC row "+2.5 pts"; "Rebalance now" → /proposal
  // "Sell BTC for €25.00", "Buy ETH for €25.00"; "Approve", "Confirm" →
  // "Every order was filled."; the calls include, in order, POST /api/rebalance,
  // POST /api/proposal/approve, POST /api/portfolio/refresh
test("invest now shows the orders before it sends them", ...)
  // "Invest now" → "Confirm: invest €100.00" → "Every order was filled.";
  // POST /api/invest?preview=true comes before POST /api/invest
```

- [ ] **Step 2: Run** `npm run e2e`. Expected: phase 10's and 11's tests and these 2 pass.
- [ ] **Step 3: Update** the roadmap's status for phase 12.
- [ ] **Step 4: Commit** `test(web): the dashboard journey end to end`

---

## What you verify before phase 13

A rebalance only proposes; nothing is sold until you confirm an approval. Invest now
shows its orders before it sends them.

1. Deploy. On the phone, open Home: the account value, the managed and unmanaged split,
   and the time of the last reading.
2. Tap Refresh. The time changes and the values match Kraken's within a few cents.
3. Check the allocation: each managed asset's weight and target match `GET /api/portfolio`
   in `/api/docs`, and only the rows at or past your drift threshold are highlighted.
4. Tap "Rebalance now". With no drift past the threshold: "Nothing to rebalance." and
   why. Otherwise the proposal opens; read it, then Dismiss and see the card gone from
   Home.
5. When there is free cash worth investing, tap "Invest now", read the preview, and either
   cancel or confirm a small amount. After a confirm, Home shows the new reading.
6. When a proposal is worth approving, request it again, approve it from the phone, and
   check the orders in Kraken.
