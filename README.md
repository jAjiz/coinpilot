# CoinPilot

> **Status:** project 1 built; going into production. Free cash is invested, and drift is
> looked for, on each user's cadence; a rebalance is proposed, or executed when the user
> turned automatic rebalancing on. Everything also runs on request through the REST API.
> The application that consumes it is project 2.

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
FastAPI, SQLAlchemy and Alembic.

The application that consumes it — a mobile-consultable UI with notifications — is a
separate project.

## Running it locally

```bash
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env    # then fill in the secrets it describes
set -a; . ./.env; set +a
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. uvicorn --factory api.main:build --port 8000
```

Signing in needs the development server below: with it running, go to
`http://localhost:5173/api/auth/login/google`. (To sign in directly on port 8000, set
`GOOGLE_REDIRECT_URI` to the `8000` callback.) The API is described at
`http://localhost:8000/api/docs`.

## Developing the application

The React application is in `web/` (Node 24, see `web/.nvmrc`).

1. Run the API as above.
2. In another terminal:

   ```bash
   cd web
   npm ci
   npm run dev
   ```

   Then open `http://localhost:5173`. Vite proxies `/api` to the API on port 8000, so
   sign-in goes through the proxy and the Google OAuth client needs the redirect URI
   `http://localhost:5173/api/auth/callback/google`.
3. After a change to the API's routes or schemas, regenerate the contract and commit both
   files:

   ```bash
   PYTHONPATH=. python scripts/export_openapi.py   # writes web/openapi.json
   cd web && npm run generate                      # writes web/src/api/schema.d.ts
   ```

   Two checks refuse a stale copy: a platform test and `check:generated` in CI.
4. Tests, from `web/`: `npm test` (unit) and `npm run e2e` (Playwright, builds first).

## Production

One Linux host with Docker, two containers, the API bound to loopback, and a deploy
that is dispatched by hand. Requirements, secrets, how to reach the API, deploy,
rollback, master-key rotation and backups are in [`docs/operations.md`](docs/operations.md).

## Security

No credential is ever committed. Secrets live in the environment, never in this
repository: Kraken keys, the master encryption key, OAuth client secrets and database
passwords. Three nets guard that rule — `.gitignore`, a `gitleaks` pre-commit hook, and
GitHub push protection.

Production details — host addresses, deploy paths — are configuration, not code, and are
not stored here either.
