# Operations

How the platform runs in production, and every operation on it: provisioning, secrets,
access, deploy, rollback, master-key rotation, backups, logs. The design behind it is the
spec's §13 ([`specs/2026-09-17-platform-design.md`](specs/2026-09-17-platform-design.md)).

Shell variables stand for everything the repository must not hold. Set them once per
shell:

```bash
PROJECT=...   # the Google Cloud project id
REGION=...    # e.g. europe-southwest1
ZONE=...      # e.g. europe-southwest1-a
VM=coinpilot
```

## 1. What runs where

One `e2-small` Ubuntu 26.04 LTS minimal VM in Google Cloud. Docker runs `postgres` and `platform` from
`/opt/coinpilot/compose.yml`. No port is open to the internet: SSH arrives through IAP,
and the API listens on the VM's loopback. Images are `ghcr.io/jajiz/coinpilot:<sha>`.

Files in `/opt/coinpilot`:

| File | What it is |
|---|---|
| `.env` | The secrets (section 3) |
| `release.env` | The current tag, written by `deploy.sh` |
| `releases` | Every release that became healthy, newest last |
| `backups/` | A dump before each deploy, the newest ten |
| `compose.yml`, `compose.sh`, `deploy.sh` | From `deploy/` in this repository, copied by each deploy |

## 2. Provisioning (once)

```bash
gcloud config set project "$PROJECT"
gcloud services enable compute.googleapis.com iap.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

# A static address, so the Kraken key can be restricted to it. Skip if it is reserved
# already; it must be in $REGION.
gcloud compute addresses create "$VM" --region "$REGION"

gcloud compute instances create "$VM" --zone "$ZONE" \
  --machine-type e2-small \
  --image-family ubuntu-minimal-2604-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 20GB --boot-disk-type pd-balanced \
  --address "$VM" \
  --metadata enable-oslogin=TRUE \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --no-service-account --no-scopes

# SSH from IAP only. The default network admits SSH and RDP from anywhere.
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --quiet
gcloud compute firewall-rules create allow-ssh-from-iap --network default \
  --direction INGRESS --allow tcp:22 --source-ranges 35.235.240.0/20
gcloud compute firewall-rules list   # expect: allow-ssh-from-iap, default-allow-icmp, default-allow-internal

# 14 daily snapshots of the disk, kept off the VM.
gcloud compute resource-policies create snapshot-schedule "$VM-daily" --region "$REGION" \
  --daily-schedule --start-time 03:00 --max-retention-days 14 \
  --on-source-disk-delete keep-auto-snapshots
gcloud compute disks add-resource-policies "$VM" --zone "$ZONE" --resource-policies "$VM-daily"

# Then, on the VM:
gcloud compute scp deploy/bootstrap.sh "$VM:~/" --zone "$ZONE" --tunnel-through-iap
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap --command "sudo bash ~/bootstrap.sh"
```

The pipeline's identity (Workload Identity Federation; no key file exists):

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
SA="coinpilot-deploy@$PROJECT.iam.gserviceaccount.com"

gcloud iam service-accounts create coinpilot-deploy --display-name "CoinPilot deploy"
gcloud iam workload-identity-pools create github --location global
gcloud iam workload-identity-pools providers create-oidc coinpilot --location global \
  --workload-identity-pool github \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" \
  --attribute-condition "assertion.repository == 'jAjiz/coinpilot' && assertion.environment == 'production'"
gcloud iam service-accounts add-iam-policy-binding "$SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/jAjiz/coinpilot"

gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/iap.tunnelResourceAccessor
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/compute.viewer
gcloud compute instances add-iam-policy-binding "$VM" --zone "$ZONE" --member "serviceAccount:$SA" --role roles/compute.osAdminLogin
```

In GitHub: Settings → Environments → New environment `production`; "Deployment
branches": `main` only. Add the variables `GCP_PROJECT`, `GCP_ZONE`, `GCP_VM`,
`GCP_DEPLOY_SA` (`$SA`) and `GCP_WIF_PROVIDER`:
`projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/coinpilot`.

After the first Release run: GitHub → Packages → `coinpilot` → Package settings →
Change visibility → Public. Check from any machine, with no login:
`docker pull ghcr.io/jajiz/coinpilot:<sha>`.

## 3. Secrets

On the VM: `sudo install -m 0600 /dev/null /opt/coinpilot/.env`, then fill it from
[`deploy/env.production.example`](../deploy/env.production.example) with
`sudo nano /opt/coinpilot/.env`, generating each secret on the VM with the command beside
it.

Copy `CREDENTIAL_KEYS` into your password manager before any credential is stored: if it
is lost, every stored Kraken key is unreadable, and the only remedy is for each user to
register theirs again.

## 4. Reaching the API

```bash
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap -- -N -L 8000:localhost:8000
```

Leave it open; the API is at `http://localhost:8000` (`/docs`, and sign in at
`/auth/login/google`). Stop the local development API first: it would hold port 8000,
and two schedulers on the same Kraken account would both invest.

## 5. Deploy

GitHub → Actions → Deploy → Run workflow → `deploy`, with the full SHA of a commit on
`main` whose Release run succeeded. On the VM, by hand:
`sudo /opt/coinpilot/deploy.sh deploy <sha>`.

It dumps the database to `backups/`, migrates with the new image, recreates the platform
and waits up to four minutes for it to report healthy. If it does not, the step fails
with the platform's last 100 log lines, and nothing else changes: roll back.

---

Sections 6 to 9 run on the VM in a root shell, because `.env` and `backups/` are root's:
`sudo -i`, then `cd /opt/coinpilot`.

## 6. Rollback

Actions → Deploy → `rollback`, or `./deploy.sh rollback`. It starts the release before
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

1. On the VM, generate the new key (command in `env.production.example`) with the next
   version number, and save it in your password manager.
2. In `.env`: `CREDENTIAL_KEYS=1:<old>,2:<new>` and `CREDENTIAL_KEY_VERSION=2`.
3. `./compose.sh up -d --wait --force-recreate platform` — new credentials are now
   sealed with version 2, and the old ones still open.
4. `./compose.sh run --rm platform python scripts/rotate_master_key.py` — expect
   `unreadable : 0`, exit 0.
5. `./compose.sh run --rm platform python scripts/rotate_master_key.py --check` —
   expect `not under it : 0`.
6. Remove `1:<old>,` from `CREDENTIAL_KEYS`, and recreate the platform again as in 3.
7. `GET /portfolio` through the tunnel reads your balance: the record opens with the new
   key alone. Only now delete the old key from your password manager. Dumps taken before
   step 4 still need it; keep it while `backups/` and the snapshots hold one.

## 8. Backups and restore

Each deploy leaves a dump in `/opt/coinpilot/backups/` (newest ten). The disk is
snapshotted daily, 14 kept.

- To take a dump by hand:
  `./compose.sh exec -T postgres pg_dump -U coinpilot -Fc coinpilot > backups/manual.dump`.
- To restore one, see section 6.
- To restore a whole snapshot, create a disk from it and a new VM on it (Compute Engine →
  Snapshots → Create disk).

## 9. Logs

`./compose.sh logs -f --since 1h platform`. A user whose scheduled operations keep
failing appears once, as
`WARNING coinpilot.scheduler: user <id>: 3 scheduled operations in a row have failed`:
`./compose.sh logs platform | grep WARNING`.

## 10. Restricting the Kraken key to the VM

In Kraken → API → the key → "IP address allowlist": the static address
(`gcloud compute addresses describe "$VM" --region "$REGION" --format 'value(address)'`).
The key then works from the VM alone; your local `scripts/check_key.py` will be refused,
which is the point.
