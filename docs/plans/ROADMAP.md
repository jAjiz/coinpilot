# Implementation Roadmap

The platform design in [`../specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md)
is delivered in eight phases. **Each phase produces working, verifiable software on its
own**, and is validated before the next one starts. One plan document per phase, written
only when its turn arrives — a plan written six phases ahead is a guess.

| Phase | Deliverable | How you verify it | Status |
|---|---|---|---|
| **1. Foundations and the engine** | Project scaffolding, CI, and the pure reconciliation engine | `pytest` and `ruff` green locally and in CI. Read the engine and check its arithmetic against your own expectations. Touches no money, no credentials, no network. | Done (#1) |
| **2. Persistence** | SQLAlchemy models, Alembic migrations, the DAL over a real Postgres | Migrations apply from empty. Integration tests pass. Inspect the schema by hand. | Done (#5) |
| **3. The Kraken layer** | Per-user client, per-key rate limiting, status normalisation, `cl_ord_id`, key-permission validation | Unit tests with no network. The real-key check was deferred to phase 4. | Done (#10) |
| **4. Identity and the read path** | OAuth, encrypted credentials, and every read endpoint | First, run `scripts/check_key.py` with two real keys: one with the required permissions is accepted, one that adds withdraw-funds is refused. Then log in, register your Kraken key, read your real portfolio. **The system still cannot place an order.** | Done (#12) |
| **5. Execution** | Order placement, the order ledger, and the unknown-result protocol | Trigger an invest operation by hand with a small amount and watch it complete. | Done (#16) |
| **6. Proposals** | The proposal lifecycle, versioned approval, one-off rebalance | Request a rebalance, read the proposal, approve it, see it execute as a unit. | Done (#18) |
| **7. The scheduler** | Cadences, anchors, staggering, failure isolation, telemetry, snapshots | Leave it running unattended and read the session history. | Done (#20) |
| **8. Deployment** | Production image, pipeline, key procedures, host hardening | Deploy, roll back, and rotate the master key. | Done (#23) |

The ordering is not arbitrary. Phases 1 to 3 cannot move money because nothing is wired
to an account. Phase 4 reads a real account but has no order path. The first phase that
can spend a euro is 5, by which point the engine, the schema and the exchange layer have
each been verified on their own.

## Project 2 — the application

Designed in [`../specs/2026-10-16-ui-design.md`](../specs/2026-10-16-ui-design.md). Cycle 1
is five phases, in the order of its §9; cycle 2, notifications, gets its own spec.

| Phase | Deliverable | How you verify it | Status |
|---|---|---|---|
| **9. The platform, ready for the application** | The `/api` prefix, the callback that redirects, `onboarded_at`, typed holdings, the application served from the same origin | Sign in at `/api/auth/login/google` and land on `/`. `/api/docs` lists every route under `/api`. | Done (#39) |
| **10. The application's skeleton** | `web/` with Vite, the generated client, session and guards; the multi-stage image; the CI job | Deploy, open the address on your phone, sign in, see the empty shell. Install it as an app. | Done (#41) |
| **11. Onboarding** | The four-step wizard | Run it against your real account: the key, your holdings prefilled, a cadence, the summary. | Done (#43) |
| **12. Dashboard and proposal** | Value, allocation, invest now, rebalance now, approve | Request a rebalance and approve it from the phone. | Done (#55) |
| **13. History and settings** | The execution history; every setting editable; pause; sign out | Change a cadence in settings and see the next run move. | Pending |
