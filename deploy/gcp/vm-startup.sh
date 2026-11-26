#!/usr/bin/env bash
# First-boot script for the DistriRAG VM (Ubuntu 24.04). The deploy workflow passes it
# as the instance startup-script; it is idempotent, so it is safe on every boot.
set -euo pipefail
READY=/var/lib/distrirag-ready
[ -f "$READY" ] && exit 0

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq docker.io docker-compose-v2 git curl
systemctl enable --now docker

REPO_URL=$(curl -sf -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/repo-url)
[ -d /opt/distrirag/.git ] || git clone --quiet "$REPO_URL" /opt/distrirag

# A swap file keeps a 4 GB VM alive while the PHI model loads.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
touch "$READY"
