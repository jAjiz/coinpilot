#!/usr/bin/env bash
# Prepares a fresh Debian 13 VM for the platform. Run once, as root:
#
#   sudo bash bootstrap.sh
#
# Installs Docker from Docker's own repository (Debian's lags behind, and deploy.sh needs
# Compose v2's `up --wait`), turns on unattended security upgrades, rotates container logs,
# and creates /opt/coinpilot. It opens no port.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "bootstrap: run as root" >&2; exit 1; }

apt-get update
apt-get install -y ca-certificates curl unattended-upgrades

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck source=/dev/null
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Every container's log is kept, but bounded: 5 files of 10 MB.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "local",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
systemctl restart docker
systemctl enable --now docker unattended-upgrades

install -d -m 0750 /opt/coinpilot /opt/coinpilot/backups
echo "bootstrap: done. Next: write /opt/coinpilot/.env (docs/operations.md, section 3)."
