# CoinPilot

> **Status: design approved, implementation not started.**

A multi-tenant service that keeps a crypto portfolio at the target allocation its owner
declared, on Kraken. It does two things, and they matter equally:

- **Contribute.** New fiat arriving in the account is invested according to the target
  weights.
- **Rebalance.** When the real weights drift away from the targets, the portfolio is
  brought back.

Both are the same operation — reconcile holdings toward target weights — reached by
different triggers.

It is a **client** of Kraken, not an exchange. It never holds funds. It reads balances
and places orders with an API key the user supplies, and that key is **refused unless it
lacks withdrawal permission**, so a compromise bounds to "someone can trade" rather than
"someone can drain".

## Design

The full design is in
[`docs/specs/2026-09-17-platform-design.md`](docs/specs/2026-09-17-platform-design.md).
Two sections are worth reading before the rest:

- **§14 Design choices** — the decisions a reviewer would otherwise question, each with
  its reason.
- **§15 Accepted risks** — what was taken on knowingly, and why.

## Scope

This repository is the **platform**: identity, credentials, portfolio state, the
reconciliation engine, order execution, the scheduler and the REST API. Python, with
FastAPI, SQLAlchemy, Alembic and APScheduler.

The application that consumes it — a mobile-consultable UI with notifications — is a
separate project.

## Security

No credential is ever committed. Secrets live in the environment, never in this
repository: Kraken keys, the master encryption key, OAuth client secrets and database
passwords. Three nets guard that rule — `.gitignore`, a `gitleaks` pre-commit hook, and
GitHub push protection.

Production details — host addresses, deploy paths — are configuration, not code, and are
not stored here either.
