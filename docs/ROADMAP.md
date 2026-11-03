# Roadmap

CoinPilot was delivered in phases, each producing working, verifiable software on its own
and validated before the next one started. The per-phase implementation plans served
their purpose and are no longer kept; each phase's pull request holds what was done.

## Project 1 — the platform

Designed in [`specs/platform-design.md`](specs/platform-design.md).

| Phase | Deliverable | How it was verified | Status |
|---|---|---|---|
| **1. Foundations and the engine** | Project scaffolding, CI, and the pure reconciliation engine | `pytest` and `ruff` green locally and in CI; the engine's arithmetic read by hand. Touches no money, no credentials, no network. | Done (#1) |
| **2. Persistence** | SQLAlchemy models, Alembic migrations, the DAL over a real Postgres | Migrations apply from empty. Integration tests pass. Schema inspected by hand. | Done (#5) |
| **3. The Kraken layer** | Per-user client, per-key rate limiting, status normalisation, `cl_ord_id`, key-permission validation | Unit tests with no network. The real-key check was deferred to phase 4. | Done (#10) |
| **4. Identity and the read path** | OAuth, encrypted credentials, and every read endpoint | `scripts/check_key.py` with two real keys: one with the required permissions is accepted, one that adds withdraw-funds is refused. Then sign in, register the key, read the real portfolio — with no order path yet. | Done (#12) |
| **5. Execution** | Order placement, the order ledger, and the unknown-result protocol | An invest operation triggered by hand with a small amount, watched to completion. | Done (#16) |
| **6. Proposals** | The proposal lifecycle, versioned approval, one-off rebalance | A rebalance requested, the proposal read, approved, and executed as a unit. | Done (#18) |
| **7. The scheduler** | Cadences, anchors, staggering, failure isolation, telemetry, snapshots | Left running unattended; the session history read. | Done (#20) |
| **8. Deployment** | Production image, pipeline, key procedures, host hardening | Deploy, roll back, and rotate the master key. | Done (#23) |

The ordering was deliberate. Phases 1 to 3 could not move money because nothing was wired
to an account. Phase 4 read a real account but had no order path. The first phase that
could spend a euro was 5, by which point the engine, the schema and the exchange layer had
each been verified on their own.

## Project 2 — the application

Designed in [`specs/ui-design.md`](specs/ui-design.md).

### Cycle 1

| Phase | Deliverable | How it was verified | Status |
|---|---|---|---|
| **9. The platform, ready for the application** | The `/api` prefix, the callback that redirects, `onboarded_at`, typed holdings, the application served from the same origin | Sign in at `/api/auth/login/google` and land on `/`. `/api/docs` lists every route under `/api`. | Done (#39) |
| **10. The application's skeleton** | `web/` with Vite, the generated client, session and guards; the multi-stage image; the CI job | Deploy, open the address on a phone, sign in, see the empty shell. Install it as an app. | Done (#41) |
| **11. Onboarding** | The four-step wizard | Run against the real account: the key, holdings prefilled, a cadence, the summary. | Done (#43) |
| **12. Dashboard and proposal** | Value, allocation, invest now, rebalance now, approve | A rebalance requested and approved from the phone. | Done (#55) |
| **13. History and settings** | The execution history; every setting editable; pause; sign out | A cadence changed in settings, and the next run moved. | Done (#57) |

### Cycle 2 — notifications

Next. It gets its own spec before any plan is written.
