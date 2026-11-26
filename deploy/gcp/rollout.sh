#!/usr/bin/env bash
# Runs on the VM (as root) after the deploy workflow has checked out the commit.
# Inputs: IMAGE_TAG (required), DOMAIN (optional: enables Caddy HTTPS).
# App settings arrive on stdin (the APP_ENV GitHub secret); empty stdin keeps the current file.
set -euo pipefail
cd /opt/distrirag
: "${IMAGE_TAG:?IMAGE_TAG is required}"

gcloud auth configure-docker "${IMAGE_TAG%%/*}" --quiet >/dev/null

app_env=$(cat || true)
if [ -n "$app_env" ]; then
  printf '%s\n' "$app_env" > .env
elif [ ! -f .env ]; then
  cp .env.example .env
fi
chmod 600 .env

files=(-f deploy/docker-compose.yml)
services=(app)
if [ -n "${DOMAIN:-}" ]; then
  # HTTPS through Caddy; the overlay reads deploy/.env.cloud.
  cp .env deploy/.env.cloud
  grep -q '^AUTH_COOKIE_SECURE=' deploy/.env.cloud || echo 'AUTH_COOKIE_SECURE=true' >> deploy/.env.cloud
  chmod 600 deploy/.env.cloud
  files+=(-f deploy/cloud/docker-compose.cloud.yml)
  services+=(caddy)
else
  export PORT=80   # plain HTTP on the VM's external IP
fi
export IMAGE_TAG DOMAIN="${DOMAIN:-}"
dc() { docker compose "${files[@]}" --profile lite "$@"; }

dc pull app
dc up -d --no-build --remove-orphans "${services[@]}"

for _ in $(seq 1 100); do
  if dc exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=3)" 2>/dev/null; then
    echo "app ready: $IMAGE_TAG"
    docker image prune -af --filter "until=72h" >/dev/null || true
    exit 0
  fi
  sleep 3
done
echo "app never became ready"
dc logs --tail=150 app
exit 1
