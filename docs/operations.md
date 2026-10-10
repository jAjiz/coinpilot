# Operations

How to run the platform on a host of your own: requirements, preparing the host, secrets,
reaching the API, deploy, rollback, master-key rotation, backups, logs. The design behind
it is the spec's §13 ([`specs/2026-09-17-platform-design.md`](specs/2026-09-17-platform-design.md)).

## 1. Requirements

- **A Linux host** with outbound internet access. `deploy/bootstrap.sh` prepares Ubuntu or
  Debian; any other distribution needs the same pieces installed by hand.
- **1 GB of memory and 2 GB of swap** are enough: during a deploy two images are on disk,
  a dump is written and a migration runs beside PostgreSQL and the platform. Some 10 GB
  of disk.
- **Docker Engine with Compose v2.** `deploy.sh` uses `up --wait`.
- **A Google OAuth client** of type "Web application" (Google Cloud console → APIs &
  Services → Credentials).
- **A static public IP** is recommended, so each Kraken key can be restricted to it
  (section 10).

No inbound port is needed by the platform itself. PostgreSQL publishes none, and the API
listens on the host's loopback.

## 2. Preparing the host

A swap file, if the host has none:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Then copy `deploy/bootstrap.sh` to the host and run it once:

```bash
sudo bash bootstrap.sh
```

It installs Docker from Docker's repository, turns on unattended security upgrades,
bounds container logs and creates `/opt/coinpilot`. It opens no port.

Files in `/opt/coinpilot`:

| File | What it is |
|---|---|
| `.env` | The secrets (section 3) |
| `release.env` | The current tag, written by `deploy.sh` |
| `releases` | Every release that became healthy, newest last |
| `backups/` | A dump before each deploy, the newest ten |
| `compose.yml`, `compose.sh`, `deploy.sh` | From `deploy/` in this repository (section 5) |

## 3. Secrets

On the host: `sudo install -m 0600 /dev/null /opt/coinpilot/.env`, then fill it from
[`deploy/env.production.example`](../deploy/env.production.example) with
`sudo nano /opt/coinpilot/.env`, generating each secret on the host with the command
beside it.

Copy `CREDENTIAL_KEYS` into your password manager before any credential is stored: if it
is lost, every stored Kraken key is unreadable, and the only remedy is for each user to
register theirs again.

To check that no value was left empty without printing any, count the lines that are a
name and nothing else: `sudo grep -c '^[A-Z_]*=$' /opt/coinpilot/.env` must say `0`. Not
`grep '=$'`: a base64 key ends in `=`, so that prints the master key.

## 4. Reaching the API

The API listens on `127.0.0.1:8000` on the host. Put something in front of it according
to who must reach it:

| Way in | When | What it takes |
|---|---|---|
| SSH tunnel | One operator, from one computer | `ssh -N -L 8000:localhost:8000 <user>@<host>`; the API is at `http://localhost:8000` |
| Private network (Tailscale, WireGuard, …) | The operator's own devices, phone included | The network's HTTPS address for the host; no port opened |
| Reverse proxy with TLS (Caddy, nginx, …) | Other people use the service | Ports 80 and 443 open to the internet, and a domain |

Whichever it is, the address it gives is the OAuth callback's host: set
`GOOGLE_REDIRECT_URI` in `.env` to `<address>/auth/callback/google`, and add the same URI
to the OAuth client's authorized redirect URIs. Then `/docs` describes the API, and you
sign in at `/auth/login/google`.

Do not run a development API against the same Kraken account as production: two
schedulers would both invest.

## 5. Deploy

Every commit on `main` whose CI passed is built by the Release workflow into
`ghcr.io/jajiz/coinpilot:<sha>`. A fork publishes its own image: change that name in
`deploy/compose.yml` and `deploy/deploy.sh`.

On the host, with the files from `deploy/` copied to `/opt/coinpilot`:

```bash
sudo /opt/coinpilot/deploy.sh deploy <sha>
```

It dumps the database to `backups/`, migrates with the new image, recreates the platform
and waits up to four minutes for it to report healthy. If it does not, it fails with the
platform's last 100 log lines, and nothing else changes: roll back.

The Deploy workflow (`.github/workflows/deploy.yml`) does the same from GitHub → Actions,
with manual approval through the `production` environment: it copies the `deploy/` files
and runs `deploy.sh` over SSH. The included one connects to a Google Cloud VM, with
Workload Identity Federation and IAP. For another host, replace its authentication and
SSH steps; the command it runs stays the same.

---

Sections 6 to 9 run on the host in a root shell, because `.env` and `backups/` are
root's: `sudo -i`, then `cd /opt/coinpilot`.

## 6. Rollback

`./deploy.sh rollback`, or Actions → Deploy → `rollback`. It starts the release before
the current one, with no migration. Rolling back twice returns to where you started.
After a deploy that never became healthy, a rollback returns to the last release that
did.

It is safe because every migration is additive: a new column is nullable or has a
default; nothing is renamed or dropped in the release that stops using it. A release that
broke that rule is undone with the dump taken before it:

```bash
cd /opt/coinpilot
./compose.sh stop platform
./compose.sh exec -T postgres pg_restore -U coinpilot -d coinpilot --clean --if-exists < backups/<dump>
./deploy.sh rollback
```

## 7. Rotating the master key

Rotate when the key may have been exposed, and when someone who knew it no longer should.

1. On the host, generate the new key (command in `env.production.example`) with the next
   version number, and save it in your password manager.
2. In `.env`: `CREDENTIAL_KEYS=1:<old>,2:<new>` and `CREDENTIAL_KEY_VERSION=2`.
3. `./compose.sh up -d --wait --force-recreate platform` — new credentials are now
   sealed with version 2, and the old ones still open.
4. `./compose.sh run --rm platform python scripts/rotate_master_key.py` — expect
   `unreadable : 0`, exit 0.
5. `./compose.sh run --rm platform python scripts/rotate_master_key.py --check` —
   expect `not under it : 0`.
6. Remove `1:<old>,` from `CREDENTIAL_KEYS`, and recreate the platform again as in 3.
7. `GET /portfolio` reads your balance: the record opens with the new key alone. Only now
   delete the old key from your password manager. Dumps taken before step 4 still need
   it; keep it while a dump or a copy of the disk holds one.

## 8. Backups and restore

Each deploy leaves a dump in `/opt/coinpilot/backups/` (newest ten). They live on the
host, so copy them somewhere else too: a lost host takes them with it.

- To take a dump by hand:
  `./compose.sh exec -T postgres pg_dump -U coinpilot -Fc coinpilot > backups/manual.dump`.
- To restore one, see section 6.

## 9. Logs

`./compose.sh logs -f --since 1h platform`. A user whose scheduled operations keep
failing appears once, as
`WARNING coinpilot.scheduler: user <id>: 3 scheduled operations in a row have failed`:
`./compose.sh logs platform | grep WARNING`.

## 10. Restricting the Kraken key to the host

In Kraken → API → the key → "IP address allowlist": the host's static public address.
The key then works from the host alone; a local `scripts/check_key.py` will be refused,
which is the point.
