# CoinPilot — Platform Design

**Date:** 2026-09-17 · **Status:** approved, not yet implemented · **Scope:** Project 1 of 2

---

## 1. What this is

A multi-tenant service that keeps a crypto portfolio at the target allocation its
owner declared, on Kraken. It does two things, and they matter equally:

- **Contribute.** New fiat that arrives in the account is invested according to the
  target weights.
- **Rebalance.** When the real weights drift away from the targets, the portfolio is
  brought back.

Both are the same operation — *reconcile holdings toward target weights* — reached by
different triggers. The system is one engine with policies, not four features.

It is a **client** of Kraken, not an exchange. It never holds funds. It reads balances
and places orders with an API key the user supplies.

## 2. Scope

**Project 1 (this document)** is the platform: identity, credentials, portfolio state,
the reconciliation engine, order execution, the scheduler, and the REST API. It reads
and it executes.

**Project 2 (later)** is the application: a mobile-consultable UI, configuration
screens, notifications, and the decision about how the API is exposed to the internet.

Project 1 has no user-facing interface beyond the REST API. Approving a rebalance
during project 1 is an API call.

## 3. Product rules

### 3.1 The managed portfolio

A user declares one **fiat currency** and a set of **assets** with a target percentage
each. The trading pair is derived (`asset` + `fiat`) and validated against Kraken's
`AssetPairs` when the asset is added; an asset that cannot be traded against that fiat
is refused at configuration time, not discovered at order time.

`fiat` is immutable for now. Assets are added and removed freely.

Target percentages must sum to 100 or less. This is validated in the application layer,
not as a table constraint.

### 3.2 Cash is the remainder

Whatever the asset weights do not claim is the cash target. Targets of 60/35 mean a 5 %
cash target. There is no separate reserve parameter.

Consequences: cash drift is measured like any other drift, and the denominator of every
percentage is *managed assets + cash*.

### 3.3 Holdings that are not configured

An asset held on Kraken with no configuration row is **shown and not managed**. It does
not enter the denominator, does not produce drift, and never produces a proposal. The
system never touches something it was not told about. It does appear in
`portfolio_snapshots.holdings` and in `GET /portfolio`, flagged as unmanaged, so the user
sees their real Kraken account rather than a partial view of it.

A row with a target of **0 %** is a different statement: it means *exit this position*,
and the engine will propose selling it. Two intentions, distinguished by the presence of
the row, with no extra field.

### 3.4 What needs approval

The unit of approval is the **operation**, not the individual order.

| Operation | Approval |
|---|---|
| Invest cash | never |
| One-off rebalance | always |
| Automatic rebalance | none; enabling it is the authorisation |

Investing cash only ever spends fiat the user already deposited, so the worst outcome of
a bug on that path is a bad price. A rebalance sells, and the worst outcome there is a
destroyed position, which cannot be undone. That is why it sits behind an explicit
decision, taken per operation or once, by enabling automatic rebalancing.

An operation is atomic for approval. A rebalance is approved or executed whole, including
any cash-funded buys it contains.

### 3.5 Cadence

Two independent cadences per user, with the same shape:

| Field | Meaning |
|---|---|
| `cadence_mode` | `MIN` or `INTERVAL` |
| `interval_days` | used when mode is `INTERVAL` |
| `interval_months` | used when mode is `INTERVAL`; calendar months, not 30 days |
| `cadence_anchor` | start date and time; used when mode is `INTERVAL` |

- `invest_cadence` — how often cash is invested.
- `rebalance_cadence` — how often drift is checked.

`MIN` is the system minimum cadence, an environment parameter defaulting to 15 minutes.
It is the successor of "as soon as drift is detected": no waiting period, act as soon as
there is drift. It is deliberately **not** "every tick" — the on-demand refresh endpoint
(§10.4) already solves screen freshness, and nothing in this product needs to act inside
60 seconds.

`cadence_anchor` is what lets a user say "the 1st of every month" or "every quarter
from 15 January". Occurrences are `anchor + k x interval`. Below a day the anchor
carries no meaning and is ignored; §10.2 covers how it coexists with staggering.

**Cadence says when to look. `min_drift_pct` says whether to act.**

If both cadences fall due on the same tick, there is one balance read and two
operations: the invest operation executes, and the rebalance operation is proposed or
executed according to the switch.

## 4. Architecture

### 4.1 Services

| Service | Contents |
|---|---|
| `platform` | FastAPI + APScheduler: engine, REST API and scheduler in one process |
| `postgres` | All state |

Two containers. There is no messaging service and no dashboard service; the project 2
application replaces both.

**Language and stack: Python 3.13**, with FastAPI, SQLAlchemy, Alembic and APScheduler.
This is a decision with reasons behind it, not a default — see §14.

### 4.2 Layers

- `exchange/kraken.py` — the anti-corruption boundary for Kraken's vocabulary:
  `_safe_call`, a normalised `OrderStatus` with its translator, `new_cl_ord_id`,
  `find_order_by_cl_ord_id`, and the rounding boundary where prices and volumes meet each
  pair's precision. Rate limiting is **per key** and the client is **per user** (§10.3).
- `core/` — logging, rounding helpers, a database facade over `core/db/` split by domain,
  a DB-authoritative configuration store seeded once from the environment, and the
  scheduler with its session telemetry and edge-triggered failure streaks.
- `api/` — FastAPI routing and request validation.
- Dockerfile, compose files, Alembic migrations, the CI workflow and the testing
  conventions.

Shared runtime state is held **per user**. No module-level global holds user state.

### 4.3 What this system does not contain

No volatility modelling, no parameter calibration, no optimizer, no backtest and no
simulation engine. There is no trading strategy here: the system never decides *what* to
hold, only how to reach what the user declared.

## 5. Identity and credentials

### 5.1 Authentication

External OAuth provider. The platform stores no passwords, and implements no password
reset or email verification flow. This is deliberate: the platform already custodies
third-party API keys, and passwords do not belong on that pile.

Multi-tenancy makes authentication a project 1 requirement, not a project 2 one — a
shared static token identifies nobody, and without identity there is no way to decide
whose portfolio a caller may see.

### 5.2 Kraken key validation

`GetApiKeyInfo` returns the key's `permissions` array and **requires no permission to
call**, so it is the first call made when a key is registered. Validation is a read, not
a probe.

| | Permissions |
|---|---|
| **Required** | `query-funds`, `modify-trades`, `query-open-trades`, `query-closed-trades` |
| **Forbidden** | `withdraw-funds`, `add-withdraw-address`, `update-withdraw-address` |

`query-open-trades` and `query-closed-trades` are required because
`find_order_by_cl_ord_id` calls both `OpenOrders` and `ClosedOrders`.

The two withdraw-address permissions are refused even though they cannot move funds on
their own: staging an address is the step before a withdrawal, if the withdrawal
permission is ever enabled.

A key that fails this contract is **rejected**. It is never stored.

The response also carries `ipAllowlist`; the platform surfaces it so the user can
restrict the key to the server's address.

### 5.3 Encryption at rest

Credentials are encrypted with a master key held in the environment, never in the
database or the repository, with a per-record nonce and a key version field for
rotation. They are decrypted only in the moment of calling Kraken, never logged, and
never returned by any endpoint.

**The key and the secret are one payload, not two.** They are serialised together as
`{"key": ..., "secret": ...}`, encoded UTF-8, and encrypted once. Two ciphertexts under
the same master key would need two nonces, and a nonce reused across them breaks AES-GCM
completely: an attacker recovers the exclusive-or of both plaintexts and can forge
further ciphertexts. One payload makes that mistake impossible to make rather than
merely discouraged. The cost is that the two cannot be rotated separately, and nothing
needs to — a Kraken key and its secret are issued and revoked as a pair.

**What this does and does not protect.** Encryption at rest defends against a stolen
database dump. It does not defend against a compromised server: a server that can trade
on the user's behalf must be able to decrypt the key. The permission contract in §5.2 is
what actually bounds the damage — a stolen key can trade, it cannot withdraw.

## 6. Data model

Every table carries `user_id`. There are no singleton rows.

| Table | Contents |
|---|---|
| `users` | OAuth identity: provider, subject, email, status. UUID primary key, so row counts are not leaked. |
| `user_credentials` | Encrypted Kraken key and secret, nonce, master-key version, validation timestamp. |
| `user_settings` | One row per user: `fiat`, `invest_cash_enabled`, `cash_rebalance_enabled`, `auto_rebalance_enabled`, `min_drift_pct`, `min_order_fiat`, both cadences, `next_invest_at`, `next_rebalance_at`, `paused`. |
| `asset_config` | One row per user and asset: resolved pair, `target_pct`. |
| `orders` | Every order attempted: `cl_ord_id`, txid, reason, status, requested amount, executed volume, price, fee. |
| `proposal` | The live proposal, at most one per user: version, plan, trigger, status. |
| `portfolio_snapshots` | Time series of portfolio value. |
| `sessions` | One row per user evaluation: status, duration, captured log lines. |

Settings types: `min_drift_pct` is `Numeric(4,1)`, `min_order_fiat` is `Numeric(10,1)`.

`portfolio_snapshots` exists from day one. Without it there is no way to answer how the
portfolio has performed over time, and the series cannot be reconstructed afterwards. It is
also what the project 2 application will chart.

`sessions` records **evaluations**, not system ticks. A monthly user produces twelve rows
a year, not thirty-five thousand. A retention policy is part of the initial schema, not a
later patch.

## 7. The reconciliation engine

### 7.1 Signature

```
reconcile(holdings, prices, targets, cash, policy) -> Plan
```

A pure leaf module. It imports no configuration and reads no globals; everything arrives
as arguments. A module with no ambient state can be driven by any caller and tested
exhaustively without mocks, which is why the most critical code in the system is also the
cheapest to verify.

The policy carries `allow_sells`, the cash policy (`PRORATA` or `REDUCE_DRIFT`),
`min_drift_pct` and `min_order_fiat`. The four described behaviours are four policies,
not four code paths:

| Behaviour | Policy |
|---|---|
| Invest cash by percentages | `allow_sells=false`, `PRORATA` |
| Invest cash to reduce drift | `allow_sells=false`, `REDUCE_DRIFT` |
| One-off rebalance | `allow_sells=true`, user-triggered |
| Automatic rebalance | `allow_sells=true`, cadence-triggered |

### 7.2 An operation is atomic

In a full rebalance, **sells fund buys**. A portfolio at 70/30 with a 50/50 target and no
cash must sell before it can buy.

The plan of a rebalance is therefore executed as a unit — sells first, then buys with the
proceeds — and approval applies to that unit. Approving order by order would leave an
operation half executed, with a buy waiting on a decision for money that has already been
raised.

An invest operation contains only cash-funded buys, so it carries no such ordering
constraint and always executes on arrival.

### 7.3 Filters

A leg below `min_order_fiat` is dropped. An asset whose drift is below `min_drift_pct`
produces no leg. With `min_drift_pct` at 0, `min_order_fiat` is the effective floor.

## 8. The proposal lifecycle

At most one live proposal per user, recalculated at every evaluation.

A proposal always represents a **rebalance operation**. Invest operations never produce
one, and neither does a rebalance while automatic rebalancing is enabled: that executes
directly.

**The version increments only on a material change**: a leg appears or disappears, or a
leg's amount moves by more than `min_order_fiat`. That threshold is reused deliberately —
a separate tolerance parameter would be one more thing to configure and to explain.

Approval carries the version. If it matches, the current plan executes. If it does not,
the request is refused and the new plan is returned; nothing executes.

If drift falls back below the threshold, the proposal is withdrawn automatically.

## 9. Order execution and the unknown result

### 9.1 Market orders

Orders are market orders. They execute on arrival, so **no order rests on the book
between ticks**. There is no repricing, no partial-fill reconciliation, no cancel
penalty, and no order state machine.

This is affordable because the system has **no latency budget**. Chasing a limit order
across ticks earns its complexity only when a position is exposed while the order rests.
Nothing here is exposed: a contribution can be invested this hour or the next, and so can a
drifted weight be corrected. The cost is the taker fee
against the maker fee: 0.40 % against 0.25 %, so 0.15 percentage points of every amount
traded.

### 9.2 The unknown result

`_safe_call` returns `None` on any error, and `None` cannot distinguish three realities:
the request never arrived; Kraken executed it and the response was lost; Kraken rejected
it and the response was lost.

Re-sending on the assumption of the first buys twice. Not re-sending on the assumption of
the second silently fails to do the job.

The balance almost resolves this on its own — a market order changes the balance, so the
next evaluation sees the truth. The hole is that **settlement is not atomic**: between
the fill and the balance endpoint reflecting it there is a window, it cannot be observed
or bounded, and it widens exactly when Kraken is degraded, which is the same condition
that produced the lost response.

The protocol:

1. **Write before sending.** An `orders` row is inserted `PENDING` with the minted
   `cl_ord_id` *before* `AddOrder` is called. Persisted state must describe the attempt
   before the attempt happens.
2. **Never guess on `None`.** The row stays `PENDING`.
3. **Resolve before computing.** Every evaluation starts by resolving `PENDING` rows with
   `find_order_by_cl_ord_id`:

| Answer | Meaning | Action |
|---|---|---|
| A txid | The order exists | Adopt it, read the fill, mark `FILLED` |
| `None` | The lookup itself failed | Still unknown: stay `PENDING`, skip this user's evaluation, count toward the failure streak |
| Answered, absent | Genuine absence | Mark `FAILED`; the next plan retries naturally |

**A lookup failure is "unknown", never "absent."** The two readings differ by a duplicate
order.

While anything is unresolved, that user is not evaluated. A plan computed on an ambiguous
balance is a wrong plan, and doing nothing for one round is safe here.

### 9.3 No partial transactions

Each leg is an independent order recorded in `orders`. If the second leg fails, the first
stands and the next evaluation recomputes from the real balance. The balance is the
truth, which is why the system converges instead of becoming inconsistent.

## 10. The scheduler

### 10.1 Tick and selection

The scheduler ticks on a fixed short interval (environment parameter, default 60 s). Each
tick runs one indexed query: the users whose `next_invest_at` or `next_rebalance_at` has
passed. Which one is due decides whether the plan may contain sells.

Public prices are fetched **once per tick and shared**. Only private calls multiply per
user, and since Kraken's rate limit is counted per key, those calls do not contend.

### 10.2 Staggering

The offset comes from the user's identifier, not from the clock:

```
offset      = stable_hash(user_id) mod interval    # e.g. CRC32 of the UUID
next_run_at = next multiple of interval + offset
```

Uniform by construction, and deterministic, so an incident can be reproduced. It also
prevents the failure it is there for: an offset anchored to the clock would put every
monthly user in the same minute of the month.

**An interval of a day or more honours the anchor.** The anchor fixes the date; the hash
offset then spreads users inside a bounded window after the anchor's time, one hour by
default. "The 1st at 09:00" runs between 09:00 and 10:00, at the same point every time for
the same user. Intent is honoured to the hour, and a thousand monthly users spread over
3 600 seconds instead of landing in one minute. Below a day there is no anchor, and the
offset spreads across the whole interval.

A missed run — the system was down — recomputes **forward** to the next slot. One
evaluation, never three accumulated.

Each tick processes a **bounded batch**. After an outage every user is overdue at once,
and without a cap the recovery is a stampede at the worst possible moment.

### 10.3 Capacity

Each user's load is one balance read per cadence period, so:

```
users per tick = Σ (tick_seconds / user_interval_seconds)
```

| Population | Average load per 60 s tick |
|---|---|
| 1 000 users at 15 min | 67 |
| 1 000 daily users | 0.7 |
| 1 000 at 15 min + 5 000 daily | 70 |

Sixty-seven balance reads, concurrent and rate-limited per key, are about a second of
wall clock. The problem was never the number of calls; it was their distribution.

The real ceiling is the host, not Kraken and not the user count. Every evaluation records
its duration in `sessions` from day one, so the ceiling shows up on a chart instead of
being reconstructed during an incident.

### 10.4 On-demand refresh

Acting and showing are separated:

| | Triggered by | Cost | Acceptable latency |
|---|---|---|---|
| Acting | the scheduler | 1 call per user per cadence | minutes |
| Showing | a user opening the app | 1 call, theirs only | seconds |

`GET /portfolio` returns the last snapshot immediately with its `as_of` timestamp.
`POST /portfolio/refresh` fetches that one user's balance now. The cost is the handful of
people with the application open, not the whole population — which decouples perceived
freshness from the scheduler's cadence.

### 10.5 Failure isolation

One user's failure is recorded and skipped; the rest of the tick proceeds. Alerting is
edge-triggered on a per-user failure streak: one message when the streak crosses the
threshold and one when it recovers, never one per failure.

## 11. API surface

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /auth/login/{provider}`, `GET /auth/callback/{provider}`, `POST /auth/logout`, `GET /auth/me` | OAuth |
| `POST /credentials`, `DELETE /credentials`, `GET /credentials/status` | Kraken key, validated on write per §5.2 |
| `GET /config`, `PATCH /config` | Settings |
| `GET /assets`, `PUT /assets/{asset}`, `DELETE /assets/{asset}` | Target weights |
| `GET /portfolio`, `POST /portfolio/refresh` | Snapshot and on-demand refresh |
| `GET /proposal`, `POST /proposal/approve`, `DELETE /proposal` | The live proposal; approval carries the version |
| `POST /rebalance` | One-off: evaluate now with sells allowed. Creates or refreshes the proposal; it never executes a sell by itself |
| `GET /orders`, `GET /sessions` | History |

Every endpoint is scoped to the authenticated user. No endpoint returns a credential.

## 12. Testing

Conventions: `tests/unit/` with no external calls, `tests/integration/` behind
`RUN_DB_INTEGRATION`, `pytest-asyncio` for routes, and an 80 % coverage gate.

Five additions specific to this system:

- **The engine is table-driven.** Given holdings, prices, targets and a policy, expect
  this exact plan. No mocks at all. The most critical code in the system is also the
  easiest to test, which is the point of making it a pure leaf module.
- **No test reads configuration from the environment.** A test that reads ambient
  settings passes on a developer machine holding a local `.env` and fails in CI, which has
  none — and it fails as a mystery, because the code under test is correct. Every test
  states what it needs explicitly, and CI runs without a `.env` precisely to catch the one
  that does not.
- **Tenant isolation is its own test category.** User A seeing or acting on user B's data
  is a class of bug that appears only once a system is multi-tenant. Every DAL function
  and every endpoint needs a
  scoping test.
- **Credential handling is tested.** Ciphertext differs from plaintext; no response schema
  carries a credential field; no log line contains a secret.
- **The unknown-result protocol is tested in all three branches.** It is the highest-risk
  code in the system.

No integration test places a real order. Against Kraken, `validate=true` only.

## 13. Deployment and operations

The same VM and the same pipeline shape: image to GHCR, rollout over SSH. Two containers
instead of four.

**The master encryption key** lives in the environment. If it is lost, every stored
credential is unrecoverable. A backup procedure and a rotation procedure are part of the
initial documentation — rotation is what the key-version column exists for.

**OAuth client secrets** follow the same path.

**Host hardening is now a prerequisite.** Port 22 is open to the internet and under
constant brute force. For single-user operation that was an annoyance. With third-party
credentials inside, it must be closed before the service is opened to anyone else.

## 14. Design choices

Non-obvious decisions a reviewer would otherwise question.

- **Market orders, not limit orders with a chase.** The system has no latency budget, and
  the chase machinery existed entirely to serve one. Dropping it removes the largest
  source of complexity and of failure modes in this class of system, for 0.15 points of
  fee.
- **`cl_ord_id` survives anyway.** It solves the lost response, which is independent of
  order type. It is a safety net for a rare path, not a central mechanism.
- **Cash is the remainder of the weights, not a separate reserve.** One model, one
  denominator, and cash drift is measured like any other.
- **A configured asset at 0 % means "exit"; an unconfigured asset means "not mine to
  touch".** Two intentions distinguished by row presence, with no extra field.
- **Approval is granted per operation, not per order.** Inside a rebalance, sells fund
  buys, so approving order by order would leave an operation half executed. Investing cash
  needs no approval because it only ever spends fiat already deposited; a rebalance does,
  unless the user authorised it once by enabling automatic rebalancing.
- **Python, decided rather than assumed.** The workload is I/O bound — HTTP to Kraken and
  queries to Postgres — with almost no computation, so language throughput is not a
  differentiator; the bottleneck is network latency and the host. Node would hold a smaller
  resident footprint and would pay off if the project 2 application were TypeScript,
  sharing one API contract across both. It loses on the point that decides here: the
  exchange layer already exists in Python, and its value is concentrated in the subtle
  parts — status normalisation, lost-response resolution, per-key rate limiting.
  Re-deriving those in another language means learning them a second time.
- **One Python version, not a supported range.** `requires-python` declares a floor that
  a library's consumers depend on. This is an application: nobody installs it on their own
  interpreter, and the production image pins whatever version we choose. A range would
  oblige CI to prove it with a matrix, so the venv, CI and the production image all state
  the same single version, and raising it is one deliberate change in three places.
- **An interval cadence carries an anchor, and the stagger runs inside a window.** Left to
  themselves, users all choose the 1st at 09:00, so a pure anchor clusters and a pure hash
  ignores intent. The anchor fixes the date and the hash spreads the hour.
- **The proposal version tracks material change only, measured in `min_order_fiat`.**
  A version that bumped on every recalculation would make approval impossible, and a
  separate tolerance would be one more knob.
- **Cadence is the load regulator, not just a preference.** The private call per user is
  the cost driver, so the cadence is what makes multi-tenancy affordable. `MIN` is the
  expensive class and is bounded by an environment floor.
- **Staggering by `hash(user_id)`, not by the clock.** Uniform by construction, and it
  prevents every monthly user landing in the same minute.
- **Acting and showing are separate mechanisms.** On-demand refresh costs one call for
  the user who is looking, which decouples screen freshness from scheduler cadence and
  removes the only good reason to tick fast.
- **Per-key rate limiting, not a module-level lock.** Kraken counts per key, so different
  users do not contend. A single global lock would cap the system at one user per second.
- **OAuth instead of local passwords.** The platform already custodies API keys; adding
  password custody, reset and verification flows would enlarge the blast radius for no
  product gain.
- **Multi-tenant schema and runtime from the start.** Chosen deliberately over a
  single-user build, accepting the larger project 1 in exchange for not retrofitting
  identity later.

## 15. Accepted risks and deferred decisions

- **Key permissions are verified only at registration.** A user can enable
  `withdraw-funds` afterwards and the platform will not notice. Accepted. Re-verification
  costs one `GetApiKeyInfo` call if this is revisited.
- **Encryption at rest does not protect against server compromise.** Bounded instead by
  the permission contract in §5.2.
- **Deposits and withdrawals are not observed as events.** All free fiat above the cash
  target is treated as investable. The order ledger therefore yields cost basis and total
  invested, but not fiat that was deposited and never invested, nor withdrawals.
- **Slippage is unmeasured.** Market orders fill at whatever the book offers.
- **Custody of third-party credentials carries a legal posture** different from operating
  one's own account. To be reviewed before the service is opened to other people.

## 16. Deferred to project 2

- The application: mobile-consultable UI, configuration screens, notifications.
- **How the API is exposed to the internet** — a tunnel with no open ports, or a reverse
  proxy with certificates. Authentication itself is in project 1; the exposure shape is
  not.
- **Kraken WebSockets.** Technically viable today — v2 has private balance and execution
  channels — and rejected for project 1 for three reasons: a persistent connection must be
  supervised and its characteristic failure is silent non-delivery; a periodic
  reconciliation is still required after any gap; and drift depends on prices, so a
  rebalancer wants periodic evaluation as its semantics, not as a workaround. It becomes
  attractive in project 2, where live prices on a screen have a real latency requirement.
