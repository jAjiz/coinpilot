# Implementation Roadmap

The platform design in [`../specs/2026-09-17-platform-design.md`](../specs/2026-09-17-platform-design.md)
is delivered in eight phases. **Each phase produces working, verifiable software on its
own**, and is validated before the next one starts. One plan document per phase, written
only when its turn arrives — a plan written six phases ahead is a guess.

| Phase | Deliverable | How you verify it |
|---|---|---|
| **1. Foundations and the engine** | Project scaffolding, CI, and the pure reconciliation engine | `pytest` and `ruff` green locally and in CI. Read the engine and check its arithmetic against your own expectations. Touches no money, no credentials, no network. |
| **2. Persistence** | SQLAlchemy models, Alembic migrations, the DAL over a real Postgres | Migrations apply from empty. Integration tests pass. Inspect the schema by hand. |
| **3. The Kraken layer** | Per-user client, per-key rate limiting, status normalisation, `cl_ord_id`, key-permission validation | Unit tests with no network. Then point it at your own key and confirm a key with withdrawal permission is refused. |
| **4. Identity and the read path** | OAuth, encrypted credentials, and every read endpoint | Log in, register your Kraken key, read your real portfolio. **The system still cannot place an order.** |
| **5. Execution** | Order placement, the order ledger, and the unknown-result protocol | Trigger an invest operation by hand with a small amount and watch it complete. |
| **6. Proposals** | The proposal lifecycle, versioned approval, one-off rebalance | Request a rebalance, read the proposal, approve it, see it execute as a unit. |
| **7. The scheduler** | Cadences, anchors, staggering, failure isolation, telemetry, snapshots | Leave it running unattended and read the session history. |
| **8. Deployment** | Production image, pipeline, key procedures, host hardening | Deploy, roll back, and rotate the master key. |

The ordering is not arbitrary. Phases 1 to 3 cannot move money because nothing is wired
to an account. Phase 4 reads a real account but has no order path. The first phase that
can spend a euro is 5, by which point the engine, the schema and the exchange layer have
each been verified on their own.
