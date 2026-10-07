#!/usr/bin/env bash
# Deploys a release of the platform on this host, or goes back to the previous one.
#
#   deploy.sh deploy <tag>   dump the database, migrate, start <tag>, wait until healthy
#   deploy.sh rollback       start the release before the current one; no migration runs
#
# Lives next to compose.yml, compose.sh and .env (/opt/coinpilot in production). <tag> is
# the commit SHA the Release workflow built. A rollback is safe because every migration
# leaves the previous release working (docs/operations.md).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="$here/compose.sh"
releases="$here/releases"
backups="$here/backups"
repository="ghcr.io/jajiz/coinpilot"
keep_backups=10

fail() {
  echo "deploy: $*" >&2
  exit 1
}

# Starts <tag>, waits until Docker reports it healthy, and records it as the current release.
start() {
  local tag="$1"
  printf 'TAG=%s\n' "$tag" > "$here/release.env"
  if ! "$compose" up -d --wait --wait-timeout 240 platform; then
    "$compose" logs --tail 100 platform >&2 || true
    fail "release $tag did not become healthy; 'deploy.sh rollback' goes back"
  fi
  echo "$tag" >> "$releases"
  echo "deploy: release $tag is running"
}

# A custom-format dump of the whole database, before the migration touches it.
backup() {
  local tag="$1" file
  mkdir -p "$backups"
  file="$backups/$(date -u +%Y%m%dT%H%M%SZ)-before-$tag.dump"
  "$compose" exec -T postgres pg_dump -U coinpilot -Fc coinpilot > "$file.partial"
  mv "$file.partial" "$file"
  # Newest first; everything past the newest $keep_backups goes.
  find "$backups" -name '*.dump' -printf '%T@ %p\n' | sort -rn | tail -n +"$((keep_backups + 1))" \
    | cut -d' ' -f2- | xargs -r rm --
  echo "deploy: database saved to $file"
}

deploy() {
  local tag="$1" image
  [[ "$tag" =~ ^[A-Za-z0-9._-]+$ ]] || fail "'$tag' is not an image tag"
  image="$repository:$tag"
  # Tags are commit SHAs and never move: an image already here is the right one.
  docker image inspect "$image" > /dev/null 2>&1 || docker pull "$image"
  "$compose" up -d --wait postgres
  backup "$tag"
  # The new image migrates. TAG in the environment wins over release.env, which still
  # names the release that is running.
  TAG="$tag" "$compose" run --rm migrate
  start "$tag"
}

rollback() {
  [[ -f "$releases" && -f "$here/release.env" ]] || fail "no release has run here yet"
  local current last previous
  current="$(sed -n 's/^TAG=//p' "$here/release.env")"
  last="$(tail -n 1 "$releases")"
  if [[ "$current" != "$last" ]]; then
    # The last deploy never became healthy, so it was not recorded: go back to the last
    # release that did.
    previous="$last"
  else
    [[ $(wc -l < "$releases") -ge 2 ]] || fail "there is no previous release to go back to"
    previous="$(tail -n 2 "$releases" | head -n 1)"
  fi
  start "$previous"
}

case "${1:-}" in
  deploy)
    [[ $# -eq 2 ]] || fail "usage: deploy.sh deploy <tag>"
    deploy "$2"
    ;;
  rollback)
    [[ $# -eq 1 ]] || fail "usage: deploy.sh rollback"
    rollback
    ;;
  *)
    fail "usage: deploy.sh deploy <tag> | deploy.sh rollback"
    ;;
esac
