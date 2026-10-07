#!/usr/bin/env bash
# docker compose for this host's platform, with its secrets (.env) and its current release
# (release.env). Everything after the script's name goes to docker compose:
#
#   compose.sh ps
#   compose.sh logs -f platform
#   compose.sh run --rm platform python scripts/rotate_master_key.py --check
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
args=(--project-directory "$here" -f "$here/compose.yml" --env-file "$here/.env")
if [[ -f "$here/release.env" ]]; then
  args+=(--env-file "$here/release.env")
fi
exec docker compose "${args[@]}" "$@"
