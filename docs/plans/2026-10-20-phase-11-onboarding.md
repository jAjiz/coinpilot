# Phase 11 — Onboarding

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new user goes from sign-in to a working configuration in four steps: a
verified Kraken key, a fiat and targets prefilled from what the account holds, the two
cadences and their switches, and a summary in sentences that finishes onboarding and
opens Home.

**Architecture:** The logic the application adds to the API is pure functions in
`web/src/lib/`: decimal parsing and formatting with `big.js`, prefill weights, cadence
translation both ways, and the summary sentences. Each step is a component under
`web/src/features/onboarding/` that reads TanStack Query queries, writes through the
`openapi-fetch` client, and moves on only after the onboarding state has been read again,
so the guards never send the user back. Component tests run every step against
`fakePlatform`, an in-memory MSW model of the endpoints onboarding touches. The phase
changes no platform code.

**Tech Stack:** As phase 10, plus `big.js`. shadcn/ui gains `input`, `label` and `switch`.

**Spec:** [`docs/specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md). This
phase covers §4.5, §5, §7 (the states, the `422`/`503` messages and the offline-disabled
buttons on the steps) and §8 (the unit and component tests for onboarding, and the
end-to-end journey through it).

**Roadmap:** [`docs/plans/ROADMAP.md`](ROADMAP.md), phase 11.

## Global Constraints

- **No amount or percentage is a JavaScript `number`** (spec §4.5). Values from the API
  and from inputs stay decimal strings; arithmetic goes through `big.js`. The only
  `number`s are counts, interval lengths and calendar fields.
- **Dependencies:** `big.js` (runtime) and `@types/big.js` (dev), current major. No other
  new dependency. shadcn/ui components are added with `npx shadcn@latest add input label switch`.
- **Precision the platform accepts:** a target has at most 2 decimals and lies in 0–100;
  `min_drift_pct` at most 1 decimal, 0–100; `min_order_fiat` at most 1 decimal, ≥ 0.
- **Decimal inputs accept `.` or `,` as the separator** and use `inputMode="decimal"`.
- **Every button that sends is disabled while its request is in flight and while
  `useOnline()` is false** (spec §7).
- **The key and secret are never kept after the request:** not in a query, not in
  `localStorage`, not logged. The fields are emptied once the key is accepted.
- **Times are the browser's time zone.** The anchor is the chosen date at 12:00 local,
  sent as UTC (`Date.prototype.toISOString`). A calendar date is `YYYY-MM-DD` read in the
  local zone, never `toISOString().slice(0, 10)`.
- **Unit and component tests run in `Europe/Madrid`:** `web/src/test/setup.ts` sets
  `process.env.TZ = "Europe/Madrid"` on its first line, and Playwright uses
  `timezoneId: "Europe/Madrid"`.
- **English copy. Copy quoted in this plan is exact.** The step headings stay "Kraken
  key", "Portfolio", "Automation", "Summary": phase 10's guard tests and journey read them.
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

## Decisions this plan takes

The spec leaves these open. Each is settled here so that no task has to guess.

1. **The wizard's cadence defaults** are invest **Monthly** and rebalance **Quarterly**,
   both starting today. The platform's own default for rebalancing (`MIN`) is not an
   option of the select (spec §5.3), so a fresh configuration is never read back into the
   form: the automation form starts from the wizard defaults while the saved rebalance
   cadence is `MIN`, and from the saved configuration once it is `INTERVAL`. Only the
   wizard or the API writes `INTERVAL`, so "already saved" needs no extra field.
2. **The wizard writes `min_drift_pct` 1.0.** The platform's default is 0; the spec's
   wizard default is 1.0 (§5.3).
3. **The fiat has no preselection.** It cannot be changed later, so the user picks it.
   The list is the platform's `SUPPORTED_FIATS` (`core/markets.py`), copied into
   `lib/fiats.ts`.
4. **Re-entering the portfolio step** (Back from automation) shows stored targets for the
   assets already configured and prefill weights for the rest. Saving deletes a stored
   asset whose Manage switch was turned off.
5. **Saving targets is ordered** so the platform's per-write "sum ≤ 100" check never
   fails on the way: every `DELETE` first, then the `PUT`s from the largest decrease to
   the largest increase (a new asset counts as an increase from 0). Writes are
   sequential.
6. **At least one managed asset** is required: the guards send a user with none back to
   the portfolio step (spec §4.2).
7. **The step forms take `onSaved`**, so phase 13's Settings can reuse
   `PortfolioForm` and `AutomationForm` without the wizard around them.

## Review Focus

1. **A phone in a Spanish locale types `12,5`.** The comma is a decimal separator, not
   an error, and the request carries `"12.5"`. → Task 1 (`parseDecimal`), Task 5 (the
   comma test).
2. **Moving to the next step must not race the cached onboarding state.** If the step
   navigates before the onboarding query is read again, the gate still sees the old step
   and sends the user back. → Task 4 (`useAdvance`); every step's "moves on" test asserts
   the final URL.
3. **Rebalancing targets between two assets must not trip the platform's sum check.**
   60/40 → 40/60 written in the wrong order is a `422` on the second `PUT`. → Task 5, the
   ordering test against `fakePlatform`, which enforces the sum.
4. **"Today" near midnight.** At 00:30 in Madrid it is still yesterday in UTC; the date
   input's default and the anchor must use the local date. → Task 2 (`localDate`), Task 6
   (the default date under a fake clock at 00:30).
5. **A refused key's reason is an object, not a string.** The platform's `422` for a key
   carries `{rejection, missing, forbidden, unnecessary}`; showing "Unprocessable Entity"
   would leave the user with no way to fix the key. → Task 4, the refusal tests.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/decimal.ts` | `parseDecimal`, `sum`, `subtract`, `compare`, `formatMoney`, `formatPercent`: pure, `big.js` |
| `web/src/lib/portfolio.ts` | `prefillWeights`, `cashTarget`, `saveOrder`: pure |
| `web/src/lib/fiats.ts` | `FIATS` |
| `web/src/lib/cadence.ts` | Cadence form ↔ platform fields; `localDate`, `localNoon` |
| `web/src/lib/summary.ts` | `summarize`, `ordinal`, `formatRun`, `startsLater` |
| `web/src/lib/keys.ts` | `REQUIRED_PERMISSIONS`, `refusalMessage` |
| `web/src/api/queries.ts` | `configKey`/`useConfig`, `assetsKey`/`useAssets`, `credentialStatusKey`/`useCredentialStatus`, `invalidateAccount` |
| `web/src/api/client.ts` | gains `describeError` |
| `web/src/components/FormError.tsx` | An inline `role="alert"` message |
| `web/src/features/onboarding/` | `OnboardingPage.tsx` (dispatch), `WizardLayout.tsx`, `useAdvance.ts`, `KeyStep.tsx`, `PortfolioStep.tsx` + `PortfolioForm.tsx`, `AutomationStep.tsx` + `AutomationForm.tsx`, `SummaryStep.tsx`, a test per step |
| `web/src/test/fakePlatform.ts` | The in-memory platform for component tests |
| `web/e2e/onboarding.spec.ts` | The journey sign-in → onboarding → Home |

---

### Task 1: Decimals, amounts and prefill weights

**Files:**
- Create: `web/src/lib/decimal.ts`, `web/src/lib/decimal.test.ts`,
  `web/src/lib/portfolio.ts`, `web/src/lib/portfolio.test.ts`, `web/src/lib/fiats.ts`
- Modify: `web/package.json`, `web/package-lock.json` (`big.js`, `@types/big.js`)

**Interfaces:**
- Produces, in `lib/decimal.ts`:

```ts
export function parseDecimal(text: string, places: number): string | null;
  // trimmed; "," or "." as the separator; digits with at most `places` decimals, nothing
  // else (no sign, no exponent, no thousands separator); canonical form without trailing
  // zeros ("12,50" → "12.5", "007" → "7", "0.0" → "0"); otherwise null
export function sum(values: string[]): string;            // canonical; [] → "0"
export function subtract(a: string, b: string): string;   // canonical, may be negative
export function compare(a: string, b: string): -1 | 0 | 1;
export function formatMoney(value: string, fiat: string): string;
  // Intl.NumberFormat("en-GB", { style: "currency", currency: fiat,
  //   currencyDisplay: "narrowSymbol" }), the string passed as is (never Number(value))
export function formatPercent(value: string): string;     // canonical + " %": "1.0" → "1 %"
```

- Produces, in `lib/portfolio.ts`:

```ts
export type PricedHolding = { asset: string; value: string | null; locked: boolean };
export function prefillWeights(cash: string, holdings: PricedHolding[]): Map<string, string>;
  // spec §5.2: for each holding that is not locked and has a value, value × 100 over
  // (cash + Σ those values), rounded down to 1 decimal; a zero denominator gives "0"
export function cashTarget(targets: string[]): string;    // "100" − Σ targets
export function saveOrder(
  stored: Map<string, string>, wanted: Map<string, string>,
): { deletes: string[]; puts: { asset: string; target: string }[] };
  // Decision 5: stored assets missing from `wanted` are deleted; puts sorted by
  // wanted − stored (stored absent = "0") ascending, then by asset; an unchanged target
  // is still put (idempotent, and it validates the pair)
```

- Produces, in `lib/fiats.ts`: `export const FIATS = ["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD"] as const;`
  with a comment naming `core/markets.py` `SUPPORTED_FIATS` as the source.

- [ ] **Step 1: Write the failing tests.** `decimal.test.ts`, tables:

```ts
// parseDecimal(text, 2)
["12.5", "12.5"], ["12,5", "12.5"], [" 12,50 ", "12.5"], ["007", "7"], ["0", "0"],
["100", "100"], ["1.234", null], ["", null], ["-1", null], ["1e2", null],
["1.000,5", null], ["12.", null], [",5", null], ["abc", null]
// parseDecimal("1.25", 1) → null; parseDecimal("1.2", 1) → "1.2"
sum(["33.3", "66.6"]) === "99.9"; sum([]) === "0"; subtract("100", "100.5") === "-0.5"
compare("10", "9.99") === 1
formatMoney("1234.5", "EUR") === "€1,234.50"; formatMoney("0.1", "USD") === "$0.10"
formatMoney("12345678901234567.89", "EUR") === "€12,345,678,901,234,567.89" // no float loss
formatPercent("1.0") === "1 %"; formatPercent("12.50") === "12.5 %"
```

  `portfolio.test.ts`:

```ts
test("weights are each value over priced assets plus cash, rounded down", ...)
  // cash "100", BTC "300", ETH "600" → BTC "30", ETH "60"
test("thirds round down and never sum above 100", ...)
  // cash "0", A "1", B "1", C "1" → each "33.3"; sum "99.9"
test("an unpriced or locked holding gets no weight and is not counted", ...)
  // cash "50", BTC "50", DOT value null, "ETH.S" locked value null → BTC "50", no DOT, no ETH.S
test("an empty account gives zero weights", ...)          // cash "0", BTC "0" → BTC "0"
test("cash is 100 minus the targets", ...)                 // ["30", "60.5"] → "9.5"; ["60", "50"] → "-10"
test("saving deletes first, then lowers, then raises", ...)
  // stored {BTC: "60", ETH: "40", DOT: "5"}, wanted {BTC: "40", ETH: "55", SOL: "5"}
  // → deletes ["DOT"], puts [BTC 40, SOL 5, ETH 55]
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL (modules missing).
- [ ] **Step 3: Install** `npm install big.js` and `npm install -D @types/big.js`, then
  implement both modules. `prefillWeights` rounds with `Big.roundDown` (`round(1, 0)`).
- [ ] **Step 4: Run** `npm test`, `npm run typecheck`, `npm run lint`. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): decimal amounts and prefill weights`

### Task 2: Cadence translation

**Files:**
- Create: `web/src/lib/cadence.ts`, `web/src/lib/cadence.test.ts`
- Modify: `web/src/test/setup.ts` (first line: `process.env.TZ = "Europe/Madrid";`)

**Interfaces:**
- Produces:

```ts
export type InvestChoice = "asap" | "daily" | "weekly" | "monthly";
export type RebalanceChoice = "monthly" | "quarterly" | "half-yearly" | "yearly";
export type CadenceFields = {
  mode: "MIN" | "INTERVAL";
  interval_days: number | null;
  interval_months: number | null;
  cadence_anchor: string | null;               // ISO instant
};
export type CadenceForm<C> = { kind: "choice"; choice: C; date: string } | { kind: "custom" };

export function localDate(at: Date): string;   // "YYYY-MM-DD" in the local zone
export function localNoon(date: string): string;  // that date at 12:00 local, as toISOString()
export function investFields(choice: InvestChoice, date: string): CadenceFields;
export function rebalanceFields(choice: RebalanceChoice, date: string): CadenceFields;
export function readInvest(fields: CadenceFields, today: string): CadenceForm<InvestChoice>;
export function readRebalance(fields: CadenceFields, today: string): CadenceForm<RebalanceChoice>;
export function cadenceOf(config: ConfigOut, prefix: "invest" | "rebalance"): CadenceFields;
export function cadencePatch(prefix: "invest" | "rebalance", fields: CadenceFields): ConfigPatch;
  // { <prefix>_cadence_mode, <prefix>_interval_days, <prefix>_interval_months, <prefix>_cadence_anchor }
```

  `ConfigOut` and `ConfigPatch` are `components["schemas"][…]` from `@/api/schema`.
- The tables (spec §5.3): `asap` → `MIN`, `null`, `null`, `null`. `daily` → `INTERVAL`,
  days 1. `weekly` → days 7. Invest `monthly` and rebalance `monthly` → months 1;
  `quarterly` 3; `half-yearly` 6; `yearly` 12. The unused length is `null`; the anchor is
  `localNoon(date)` for every `INTERVAL`.
- Reading back: `MIN` is `asap` for invest (date `today`) and `custom` for rebalance. An
  `INTERVAL` is a choice only when its lengths (`null` read as 0) match one row exactly
  and its anchor is 12:00:00.000 local; the date is the anchor's `localDate`. Anything
  else is `custom`.

- [ ] **Step 1: Write the failing tests:**

```ts
test("the test zone is Madrid", ...)  // new Date("2026-07-01T10:00:00Z").getHours() === 12
test("noon in summer time is 10:00 UTC", ...)
  // investFields("weekly", "2026-10-19") → { mode: "INTERVAL", interval_days: 7,
  //   interval_months: null, cadence_anchor: "2026-10-19T10:00:00.000Z" }
test("noon in winter time is 11:00 UTC", ...)
  // investFields("monthly", "2026-12-01").cadence_anchor === "2026-12-01T11:00:00.000Z"
test("the day the clocks change keeps noon local", ...)
  // investFields("daily", "2026-10-25").cadence_anchor === "2026-10-25T11:00:00.000Z"
test("the 31st is sent as the 31st", ...)
  // rebalanceFields("monthly", "2026-01-31") → months 1, anchor "2026-01-31T11:00:00.000Z"
test("a date in the past is kept", ...)
  // investFields("daily", "2020-02-29").cadence_anchor === "2020-02-29T11:00:00.000Z"
test("as soon as possible has no anchor", ...)              // asap → MIN, null, null, null
test("every choice reads back as itself", ...)              // all 4 + 4, date "2026-03-29"
test("a cadence the select cannot express is custom", ...)
  // rebalance MIN; invest days 2; days 1 + months 1; anchor at 09:00 local;
  // INTERVAL with anchor null
test("today is the local date", ...)
  // localDate(new Date("2026-10-19T22:30:00Z")) === "2026-10-20"
test("the patch names the prefix's fields", ...)
  // cadencePatch("rebalance", rebalanceFields("quarterly", "2026-10-01")) has
  // rebalance_cadence_mode "INTERVAL", rebalance_interval_months 3, rebalance_interval_days null
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `localNoon` builds `new Date(y, m - 1, d, 12)`.
- [ ] **Step 4: Run** `npm test`, `typecheck`, `lint`. Expected: pass, phase 10's tests
  included (the zone change must not break them).
- [ ] **Step 5: Commit** `feat(web): cadence translation both ways`

### Task 3: The summary sentences

**Files:**
- Create: `web/src/lib/summary.ts`, `web/src/lib/summary.test.ts`

**Interfaces:**
- Consumes: `CadenceForm`, `InvestChoice`, `RebalanceChoice`, `localDate` (Task 2);
  `formatMoney`, `formatPercent`, `compare` (Task 1).
- Produces:

```ts
export type SummaryInput = {
  fiat: string;
  invest: CadenceForm<InvestChoice>;
  rebalance: CadenceForm<RebalanceChoice>;
  invest_cash_enabled: boolean;
  cash_rebalance_enabled: boolean;
  auto_rebalance_enabled: boolean;
  min_drift_pct: string;
  min_order_fiat: string;
};
export function summarize(input: SummaryInput): string[];  // 2 or 3 sentences, in this order
export function ordinal(day: number): string;              // 1st 2nd 3rd 4th 11th 12th 13th 21st 22nd 23rd 31st
export function formatRun(at: string): string;             // "Monday 26 October at 12:37", local
export function startsLater(form: CadenceForm<string>, nextAt: string | null): boolean;
  // a choice other than "asap" whose date is not localDate(nextAt); false for custom or null
```

- **The copy.** `{d}` is `ordinal(day of the date)`, `{weekday}` and `{month}` English
  names of the date (`en-GB`), `{fiat}` the code. `{late}` is
  ` (or the last day of a shorter month)` when the day is 29–31, otherwise empty.
  - Invest, enabled: `{When}, free {fiat} is invested {how}.`, with `{how}` =
    `toward your targets`, or `in the most underweight assets first` when
    `cash_rebalance_enabled`. `{When}`: asap `Every 15 minutes`; daily
    `Every day at 12:00`; weekly `Every {weekday} at 12:00`; monthly
    `On the {d} of every month at 12:00{late}`; custom `On a custom schedule`.
  - Invest, disabled: `Free {fiat} is not invested automatically; you can invest it from Home.`
  - Rebalance: `{When}, {if}, {then}.` `{When}`: monthly `On the {d} of every month{late}`;
    quarterly `On the {d} of every quarter{late}`; half-yearly
    `On the {d} every six months{late}`; yearly `Every year on {day} {month}`; custom
    `On a custom schedule`. `{if}`: `if any asset has drifted more than {formatPercent(min_drift_pct)}`,
    or `if any asset is off its target` when it is 0. `{then}`:
    `a rebalance is proposed for you to approve`, or
    `the portfolio is rebalanced without asking` when `auto_rebalance_enabled`.
  - When `min_order_fiat` > 0, a third: `Orders smaller than {formatMoney(min_order_fiat, fiat)} are skipped.`
- `formatRun` composes `{weekday} {day} {month} at {HH}:{mm}` from the date's local
  fields and `en-GB` names, so the output does not depend on the ICU version.

- [ ] **Step 1: Write the failing tests:**

```ts
test("the spec's example, word for word", ...)
  // fiat EUR; invest weekly "2026-10-19" enabled; rebalance quarterly "2026-10-01";
  // min_drift_pct "1.0"; min_order_fiat "0"; other switches off →
  // ["Every Monday at 12:00, free EUR is invested toward your targets.",
  //  "On the 1st of every quarter, if any asset has drifted more than 1 %, a rebalance is proposed for you to approve."]
test("invest disabled says so", ...)
test("as soon as possible, daily, monthly on the 31st", ...)
  // "On the 31st of every month at 12:00 (or the last day of a shorter month), free EUR is invested toward your targets."
test("buying the most underweight first", ...)
test("yearly, half-yearly, automatic, no drift threshold", ...)
  // "Every year on 15 January, if any asset is off its target, the portfolio is rebalanced without asking."
test("a minimum order adds a sentence", ...)   // "Orders smaller than €10.00 are skipped."
test("custom cadences", ...)
test("ordinals", ...)                          // 1 2 3 4 11 12 13 21 22 23 31
test("a run is told in local time", ...)       // formatRun("2026-10-26T11:37:00Z") === "Monday 26 October at 12:37"
test("a start date that has passed begins later", ...)
  // weekly "2026-10-19", next "2026-10-26T10:20:00Z" → true; next "2026-10-19T10:20:00Z" → false;
  // asap → false; custom → false; null → false
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, `typecheck`, `lint`. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): the configuration told in sentences`

### Task 4: The wizard frame and the key step

**Files:**
- Create: `web/src/api/queries.ts`, `web/src/components/FormError.tsx`,
  `web/src/lib/keys.ts`, `web/src/lib/keys.test.ts`, `web/src/test/fakePlatform.ts`,
  `web/src/features/onboarding/WizardLayout.tsx`, `useAdvance.ts`, `KeyStep.tsx`,
  `KeyStep.test.tsx`; `web/src/components/ui/{input,label,switch}.tsx` (shadcn)
- Modify: `web/src/api/client.ts` (`describeError`), `web/src/components/LoadFailed.tsx`
  (uses it), `web/src/features/onboarding/OnboardingPage.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap`, `ApiError` (phase 10); `onboardingKey`, `useOnboarding`
  (`features/auth/session.ts`); `useOnline` (`features/shell/useOnline.ts`); `OfflineNotice`.
- Produces, in `api/client.ts`: `describeError(error: unknown): string` — an
  `ApiError`'s `detail`, otherwise "The connection failed.". `LoadFailed` shows it.
- Produces, in `api/queries.ts`:

```ts
export const configKey = ["config"] as const;
export const assetsKey = ["assets"] as const;
export const credentialStatusKey = ["credentials", "status"] as const;
export type Config = components["schemas"]["ConfigOut"];
export function useConfig();            // Config | null: a 404 resolves to null
export function useAssets();            // AssetsOut
export function useCredentialStatus();  // CredentialStatusOut
export function invalidateAccount(client: QueryClient): Promise<void>;
  // awaits invalidateQueries for config, assets, credentials and onboardingKey
```

- Produces, in `features/onboarding/useAdvance.ts`:
  `useAdvance(): (to: OnboardingStep | "/") => Promise<void>` — `await invalidateAccount`,
  then `navigate(to === "/" ? "/" : "/onboarding/" + to)`. Every step moves on through it.
- Produces, in `WizardLayout.tsx`: `<WizardLayout step title>{children}</WizardLayout>` —
  the phase 10 page frame (`OfflineNotice`, `max-w-md`), then "Step {n} of 4", the `h1`
  title, the children, and a "Back" link to the previous step (none on `key`).
- `OnboardingPage` renders `KeyStep` for `key`; the other steps keep phase 10's
  placeholder inside `WizardLayout` until their task replaces it.
- **Every step's loading and error states** (spec §7): while a query it needs is pending,
  `FullPageSkeleton`-style skeleton rows inside `WizardLayout`; when one fails,
  `describeError` and a "Try again" button that refetches it.
- Produces, in `components/FormError.tsx`: `<FormError message />` — a `role="alert"`
  paragraph, nothing when `message` is null.
- Produces, in `lib/keys.ts`:

```ts
export const REQUIRED_PERMISSIONS: { code: string; label: string }[];
  // query-funds "Query Funds"; query-open-trades "Query Open Orders & Trades";
  // query-closed-trades "Query Closed Orders & Trades"; modify-trades "Create & Modify Orders"
export function refusalMessage(detail: unknown): string | null;
  // the 422 body's `detail`, { rejection, missing, forbidden, unnecessary }:
  // invalid_key → "Kraken did not accept this key. Check that both fields were copied in full."
  // missing_permissions → "The key is missing these permissions: {missing, ", "}."
  // forbidden_permissions → "The key can move funds out of the account ({forbidden, ", "}). Create a new key without them."
  // any other detail → null (the caller shows describeError)
```

- Produces, in `test/fakePlatform.ts`, for this task and Tasks 5–7:

```ts
export type FakeState = {
  config: Config | null;                       // null: no settings yet (GET → 404)
  registered: boolean;
  assets: { asset: string; pair: string; target_pct: string }[];
  portfolio: { cash: string; holdings: HoldingOut[] };  // what a refresh returns
  untradable: string[];                        // PUT → 422 "kraken has no tradable {X}/{fiat} pair"
  keyReply: { status: number; body: unknown }; // POST /api/credentials; default 201, accepted
  nextInvestAt: string; nextRebalanceAt: string;
};
export function fakePlatform(initial?: Partial<FakeState>): {
  handlers: HttpHandler[];
  state: FakeState;                            // mutated by the handlers
  requests: { method: string; path: string; body: unknown }[];  // every write, in order
};
```

  It answers `GET /api/auth/me` (signed in), `GET`/`PATCH /api/config` (the first PATCH
  needs a fiat, else 409; `onboarded: true` sets `onboarded_at`; `next_invest_at` is
  `nextInvestAt` when `invest_cash_enabled`, else null; `next_rebalance_at` is
  `nextRebalanceAt`), `GET /api/credentials/status`, `POST /api/credentials`,
  `GET /api/assets`, `PUT`/`DELETE /api/assets/:asset` (the PUT refuses with 422 when the
  other targets plus this one exceed 100, as the platform does), and
  `POST /api/portfolio/refresh` (409 without settings; managed holdings follow
  `state.assets`). Defaults: no config, no key, no assets, an empty portfolio. A test
  that needs an error passes its own handler before `handlers` in `renderAt`'s list.

- **Key step copy.** Intro: "CoinPilot trades on your Kraken account through an API
  key. In Kraken, open Settings → API and create a key with exactly these permissions:"
  then the four labels, each with its code. Then, emphasised: "Never enable withdrawal
  permissions. CoinPilot refuses a key that can move funds out." Fields "API key" and
  "Private key", both `type="password"`, `autoComplete="off"`, required. Button
  "Verify & save"; while sending, "Verifying with Kraken…".
  - Accepted: "Key saved." Then, when `unnecessary` is not empty, "This key also has
    permissions CoinPilot does not need: {unnecessary, ", "}. Turn them off in Kraken."
    When `ip_allowlist` is empty, "Restrict the key to your server's IP address in
    Kraken, so that it is useless anywhere else." Button "Continue" → `portfolio`.
  - Refused: `refusalMessage(error.body.detail)`, else `describeError(error)`, in a
    `FormError`. The fields keep their values so the user can correct them.
  - Already registered (Back from portfolio): "A key is saved, verified on {date}." with
    "Continue", and the form below under "Replace the key".

- [ ] **Step 1: Write the failing tests.** `keys.test.ts`: each rejection's message;
  a string or unknown detail → `null`. `KeyStep.test.tsx`, each with `fakePlatform` at
  `/onboarding/key`:

```ts
test("the four permissions are listed, with the withdrawal warning", ...)
test("an accepted key moves on to the portfolio", ...)
  // type both fields, "Verify & save" → request body { api_key, api_secret };
  // "Key saved."; "Continue" → /onboarding/portfolio, heading "Portfolio"
test("the fields are emptied once the key is accepted", ...)
test("extra permissions and a missing IP restriction are pointed out", ...)
  // keyReply unnecessary ["query-ledger"], ip_allowlist [] → both sentences
test("a refused key shows the platform's reason", ...)
  // 422 { detail: { rejection: "missing_permissions", missing: ["query-closed-trades"], ... } }
  // → "The key is missing these permissions: query-closed-trades."; still /onboarding/key
test("a key that can withdraw is refused, naming the permissions", ...)
test("an unreachable Kraken shows the platform's message", ...)
  // 503 { detail: "kraken could not be reached; the key was not stored" } → that text
test("the button is disabled while verifying and while offline", ...)
test("a saved key can be kept", ...)
  // registered: true, config with fiat EUR, no asset; open /onboarding/key:
  // "A key is saved" → "Continue" → /onboarding/portfolio
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Add the shadcn components first.
- [ ] **Step 4: Run** the full web command line. Expected: pass, phase 10's guard tests
  included.
- [ ] **Step 5: Commit** `feat(web): the onboarding frame and the key step`

### Task 5: The portfolio step

**Files:**
- Create: `web/src/features/onboarding/PortfolioStep.tsx`, `PortfolioForm.tsx`,
  `PortfolioStep.test.tsx`
- Modify: `web/src/features/onboarding/OnboardingPage.tsx`

**Interfaces:**
- Consumes: `prefillWeights`, `cashTarget`, `saveOrder` (Task 1), `parseDecimal`,
  `formatMoney`, `formatPercent`, `FIATS` (Task 1); `useConfig`, `useAssets`,
  `invalidateAccount` (Task 4); `useAdvance`, `WizardLayout`, `FormError` (Task 4).
- Produces: `PortfolioForm({ fiat, onSaved }: { fiat: string; onSaved: () => Promise<void> })`
  — the account list, targets and save; it calls `POST /api/portfolio/refresh` itself.
  `PortfolioStep` = the currency block, then `PortfolioForm` once a fiat exists, with
  `onSaved` = `advance("automation")`.

- **Currency block.** Heading "Currency". "The currency your portfolio is valued and
  traded in. It cannot be changed later." A select of `FIATS` with the placeholder
  "Choose a currency", and "Save currency" → `PATCH /api/config { fiat }`. Once the
  config exists the block shows "Currency: {fiat}" and nothing to change.
- **The account.** Heading "Your account". "Targets start at today's weights, so the
  first rebalance has nothing to do. Change them to where you want the portfolio to be."
  While the refresh runs, skeleton rows; on an error, `LoadFailed`-style message with
  "Try again". One row per holding, in the API's order:
  - tradable and priced: asset, `formatMoney(value)`, "{formatPercent(weight)} of the
    account", a Manage switch (on) labelled "Manage {asset}", a target input labelled
    "Target for {asset}" with a "%" suffix. The target starts at the stored `target_pct`
    for a managed holding (Decision 4), at the prefill weight otherwise.
  - unpriced: "Kraken has no {asset}/{fiat} price, so it cannot be managed." No switch.
  - locked: "Locked (staked or reserved), so it cannot be managed." No switch.
- **Add asset.** An input labelled "Asset to add" (placeholder "e.g. SOL") and "Add". It
  appends a managed row with an empty target and no value, upper-cased. A code already
  listed: "{CODE} is already in the list.".
- **Cash.** "Cash ({fiat}) target: {formatPercent(cashTarget)}", recomputed on every
  keystroke over the valid managed targets.
- **Save targets.** Errors, checked before anything is sent, each next to its cause:
  an invalid target "Enter a percentage from 0 to 100, with up to two decimals.";
  managed targets over 100 "The targets add up to more than 100 %."; no managed asset
  "Manage at least one asset.". Then `saveOrder(stored, wanted)` from `useAssets` and the
  form, sent in order. A failed write stops the sequence; its `describeError` shows in the
  row of that asset, and the writes before it stand (sending again is idempotent).
  Success → `onSaved()`.

- [ ] **Step 1: Write the failing tests:**

```ts
test("the currency is chosen first, with its warning", ...)
  // no config: "It cannot be changed later." → choose EUR → "Save currency" →
  // PATCH { fiat: "EUR" }, then the refresh, then the rows
test("holdings are prefilled with today's weights", ...)
  // cash "100", BTC value "300", ETH "600" → targets "30" and "60"; "Cash (EUR) target: 10 %"
test("locked and unpriced balances cannot be managed", ...)
test("saving writes one PUT per managed asset and moves on", ...)
  // requests: PUT /api/assets/BTC { target_pct: "30" }, PUT ETH "60"; → /onboarding/automation
test("a comma is a decimal separator", ...)      // "12,5" → PUT body target_pct "12.5"
test("targets above 100 are refused before anything is sent", ...)
test("managing nothing is refused", ...)
test("an added asset Kraken cannot trade shows the reason in its row", ...)
  // add "XYZ", untradable ["XYZ"] → "kraken has no tradable XYZ/EUR pair" within the XYZ row
test("coming back keeps stored targets and deletes an asset switched off", ...)
  // assets BTC "50" managed; ETH unmanaged; switch BTC off → DELETE BTC before PUT ETH
test("moving weight between two assets never passes 100 on the way", ...)
  // stored BTC "60", ETH "40" → 40 / 60: both PUTs succeed against fakePlatform; BTC first
test("an unreachable Kraken on the read offers a retry", ...)
  // refresh 503 { detail: "kraken did not return balance; nothing was recorded" } →
  // that text, "Try again" → the rows
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): the portfolio step, prefilled from the account`

### Task 6: The automation step

**Files:**
- Create: `web/src/features/onboarding/AutomationStep.tsx`, `AutomationForm.tsx`,
  `AutomationStep.test.tsx`
- Modify: `web/src/features/onboarding/OnboardingPage.tsx`

**Interfaces:**
- Consumes: Task 2 (all of it), `parseDecimal` (Task 1), `useConfig`, `useAdvance`,
  `WizardLayout`, `FormError` (Task 4).
- Produces: `AutomationForm({ config, initial, onSaved })` with
  `initial: AutomationValues`, and `wizardValues(config: Config, today: string): AutomationValues`
  (Decision 1: wizard defaults while `rebalance_cadence_mode` is `MIN`, the saved values
  otherwise). `AutomationValues` holds both `CadenceForm`s, the three switches, and
  `min_drift_pct`, `min_order_fiat` as text.
- **Copy.** Intro: "When CoinPilot acts on its own. A run happens between 12:00 and 13:00
  your time."
  - "Invest cadence": a select with "As soon as possible (every 15 min)", "Daily",
    "Weekly", "Monthly", and "Start date" (`type="date"`, hidden for the first option).
    Below it, for weekly "Runs every {weekday}.", for monthly "Runs on the {d} of each
    month; in a shorter month, on its last day." (the second clause only for 29–31).
  - "Rebalance cadence": "Monthly", "Quarterly", "Half-yearly", "Yearly", and "Start date".
  - A custom cadence adds a selected "Custom" option and the line "Set through the API;
    kept unless you choose another option." A custom cadence the user does not change is
    left out of the request.
  - Switches, each followed by its sentence:
    - "Invest free cash automatically" — "At each invest run, free {fiat} is invested
      toward your targets. Off, you invest it yourself from Home."
    - "When investing, buy the most underweight assets first" — "Off, cash is spread in
      proportion to the targets."
    - "Rebalance automatically, without asking" — "Off, a rebalance waits for your
      approval. On, it sells and buys as soon as it is found."
  - "Rebalance only when an asset drifts more than" with a "%" suffix — "Smaller
    differences are left alone, so they cost no fees." Invalid: "Enter a percentage from
    0 to 100, with up to one decimal."
  - "Skip orders smaller than" with a "{fiat}" suffix — "Kraken's own minimum always
    applies." Invalid: "Enter an amount of 0 or more, with up to one decimal."
  - Button "Save and continue" → one `PATCH /api/config` with both cadences
    (`cadencePatch`), the switches and both thresholds → `onSaved()` = `advance("summary")`.
    A `422` shows its `describeError` above the button.

- [ ] **Step 1: Write the failing tests**, the clock faked with
  `vi.useFakeTimers({ toFake: ["Date"] })`:

```ts
test("a new configuration starts from the wizard's defaults", ...)
  // now 2026-10-19T08:00:00Z: invest "Monthly", rebalance "Quarterly", both dates
  // "2026-10-19", switches off, drift "1", minimum "0"
test("the default date is the local day", ...)
  // now 2026-10-19T22:30:00Z → dates "2026-10-20"
test("as soon as possible hides the start date", ...)
test("saving sends one PATCH and opens the summary", ...)
  // weekly → body has invest_cadence_mode "INTERVAL", invest_interval_days 7,
  // invest_cadence_anchor "2026-10-19T10:00:00.000Z", rebalance_interval_months 3,
  // min_drift_pct "1", min_order_fiat "0"; → /onboarding/summary
test("a saved configuration is shown when coming back", ...)
test("a custom cadence is kept unless changed", ...)
  // invest INTERVAL days 2 → "Custom" selected; the PATCH has no invest_cadence_* field
test("an invalid threshold is refused next to its field", ...)   // drift "1.25" → nothing sent
test("the platform's refusal is shown", ...)                     // 422 detail string
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): the automation step`

### Task 7: The summary and Start

**Files:**
- Create: `web/src/features/onboarding/SummaryStep.tsx`, `SummaryStep.test.tsx`
- Modify: `web/src/features/onboarding/OnboardingPage.tsx` (the placeholder goes)

**Interfaces:**
- Consumes: `summarize`, `formatRun`, `startsLater` (Task 3); `cadenceOf`, `readInvest`,
  `readRebalance`, `localDate` (Task 2); `useConfig`, `useAdvance`, `WizardLayout`.
- **Copy.** Intro: "This is what CoinPilot will do. Nothing is traded until then." Each
  sentence of `summarize` as a paragraph. Then "First investment: {formatRun(next_invest_at)}"
  when it is set, and "First rebalance check: {formatRun(next_rebalance_at)}". After a
  line whose `startsLater` is true: "The start date has passed, so the first run is the
  next one." Button "Start" → `PATCH /api/config { onboarded: true }` →
  `advance("/")`. "Back" goes to automation.

- [ ] **Step 1: Write the failing tests:**

```ts
test("the configuration is told in sentences", ...)   // the spec's example config → both sentences
test("the first runs are shown in local time", ...)
  // next_invest_at "2026-10-26T10:37:00Z" → "First investment: Monday 26 October at 11:37"
test("invest off shows no first investment", ...)
test("a start today after noon says the first run is the next one", ...)
test("Start finishes onboarding and opens Home", ...)
  // PATCH { onboarded: true }; → "/", heading "Home"
test("Start is disabled while it is sent", ...)
```

- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full web command line. Expected: pass.
- [ ] **Step 5: Commit** `feat(web): the summary that starts CoinPilot`

### Task 8: The onboarding journey end to end

**Files:**
- Create: `web/e2e/onboarding.spec.ts`, `web/e2e/mockApi.ts`
- Modify: `web/e2e/journey.spec.ts` (imports `mockApi` from the new module),
  `web/playwright.config.ts` (`timezoneId: "Europe/Madrid"`)

**Interfaces:**
- `mockApi(page, replies)` moves to `e2e/mockApi.ts`, unchanged for phase 10's tests, and
  gains two things: a key may be `"METHOD /path"`, which wins over a plain `"/path"`; and
  a reply function receives the request's parsed JSON body. It still returns the list of
  paths called, now as `"METHOD /path"`.
- The journey keeps its own state in the test (no config, no key, then what each write
  sets), as `fakePlatform` does for the component tests. Nothing reaches a platform.

- [ ] **Step 1: Write the journey:**

```ts
test("a new user goes from sign-in to Home through the four steps", ...)
  // / → /onboarding/key; fill both fields, "Verify & save", "Continue" →
  // /onboarding/portfolio; choose EUR, "Save currency"; the rows BTC 30 % and ETH 60 %
  // appear (cash "100", BTC "300", ETH "600"); "Save targets" → /onboarding/automation;
  // choose "Weekly", turn on "Invest free cash automatically", "Save and continue" →
  // /onboarding/summary showing "free EUR is invested toward your targets";
  // "Start" → / "Home"; the calls include, in order,
  // POST /api/credentials, PATCH /api/config, POST /api/portfolio/refresh,
  // PUT /api/assets/BTC, PUT /api/assets/ETH, PATCH /api/config, PATCH /api/config
test("a reload in the middle resumes at the same step", ...)
  // key registered, fiat and BTC saved → /settings → /onboarding/automation
```

- [ ] **Step 2: Run** `npm run e2e`. Expected: phase 10's 5 tests and these 2 pass.
- [ ] **Step 3: Commit** `test(web): the onboarding journey end to end`

---

## What you verify before phase 12

With defaults nothing is traded: investing is off and a rebalance only proposes.

1. Deploy. On the phone, sign in to production: "Kraken key".
2. Create the real Kraken key with the four permissions and register it. Read what the
   application says about extra permissions and the IP restriction, and restrict the key
   in Kraken to the server's address.
3. Choose the fiat. Check that your holdings are listed with today's values and weights,
   and that leaving the targets as they are gives a cash target close to your cash share.
   This is also phase 9's pending check: the refresh answers `200` with typed holdings.
4. Pick a cadence and read the summary: the sentences match what you chose and the first
   runs fall between 12:00 and 13:00 your time.
5. Press Start: Home opens. Reload: you stay on Home, onboarding does not come back.
6. In `/api/docs`, `GET /api/config` shows `onboarded_at` set and the cadences you chose.

## What the manual check showed (2026-10-22 and 2026-10-23)

Production runs `6891555`: phase 11, the key-step fix
([#52](https://github.com/jAjiz/coinpilot/pull/52)) and fastapi 0.148. Every step passed.

| Step | Result |
|---|---|
| 1. Deploy and sign in | Passed. |
| 2. The real key | The first attempt, on `3553545`, was refused as "Kraken did not accept this key". Both fields were hidden and nothing removed whitespace, so a space or line break copied with a value was the likely cause; the logs write the same line for an `EAPI` refusal and an undecodable secret. #52 shows both fields in clear with Kraken's names and drops whitespace before validating. On `6891555` the key was accepted, and it is restricted in Kraken to the server's address. |
| 3. Fiat and holdings | Passed: holdings listed with today's values and weights. This closes phase 9's pending check. |
| 4. Cadence and summary | Passed. |
| 5. Start | Passed: Home opens and stays after a reload. |
| 6. `GET /api/config` | Passed: `onboarded_at` set, the chosen cadences stored. |

Phase 8's step 7 is half closed: the key is restricted to the server. Still pending from
phase 8: rotating the master key with this record, and deleting the key from the
development database.
