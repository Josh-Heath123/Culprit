#!/usr/bin/env bash
# Run ON THE VM — .github/workflows/ci-cd.yml SSHes in and invokes this,
# it never talks to the production DB directly from the CI runner.
#
# Order matters and is deliberate: pull -> migrate -> restart. Migrating
# before restarting means the containers are never running code that
# expects a schema the DB doesn't have yet (see CLAUDE.md / Phase 11).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env.prod ]; then
  echo "infra/.env.prod not found on this VM. Generate it once, by hand, with:" >&2
  echo "  MSYS_NO_PATHCONV=1 docker run --rm -it -v \"\$(pwd)/..:/repo\" -w /repo python:3.12-slim python scripts/bootstrap_env.py --domain <your-domain>" >&2
  echo "(or 'just bootstrap-env --domain <your-domain>' from the repo root) — see docs/INSTALL.md." >&2
  exit 1
fi

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

echo "==> Pulling images"
"${COMPOSE[@]}" pull

echo "==> Running database migrations"
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "==> Restarting containers"
"${COMPOSE[@]}" up -d --remove-orphans

# Extracted with grep/cut, not `source .env.prod` — dotenv values (e.g.
# OPERATOR_PASSWORD_HASH's argon2 hash) legitimately contain literal `$`
# characters that a bash `source` would try to expand as variables.
DOMAIN=$(grep -E '^DOMAIN=' .env.prod | cut -d= -f2-)

# Polled, not a single flat sleep+curl: on the very first deploy for a
# given domain, Caddy has to complete a live Let's Encrypt handshake
# (tls-alpn-01) before it can serve anything on 443 at all — observed
# taking ~10s in practice (2026-08-04 first deploy), which a single
# `sleep 5` + 10s curl timeout doesn't reliably cover. Later deploys
# reuse the cached cert in the caddy-data volume and pass on the first
# attempt; this loop just means a slow cold cert doesn't fail an
# otherwise-successful deploy. Shared by both checks below (Phase 15
# added the second one) since they need the identical retry shape.
poll_health() {
  local label="$1" url="$2"
  shift 2
  local ok_statuses=("$@")
  local status="000"
  for i in $(seq 1 12); do
    status=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "$url" || echo "000")
    for ok in "${ok_statuses[@]}"; do
      if [ "$status" = "$ok" ]; then
        echo "${label} health check passed (HTTP ${status})"
        return 0
      fi
    done
    echo "  ${label} attempt $i/12: HTTP ${status}, retrying in 5s..."
    sleep 5
  done
  echo "${label} health check FAILED (HTTP ${status})" >&2
  return 1
}

echo "==> Health check: https://${DOMAIN}/api/incidents"
# /incidents requires a bearer token (Phase 9) — 200 (would only happen
# with a valid token, not expected here) or 401 (means the server, auth
# dependency, and DB connection are all up and routing correctly) both
# count as healthy. Anything else (connection refused, 5xx, timeout)
# means the deploy is broken.
dashboard_ok=1
poll_health "dashboard API" "https://${DOMAIN}/api/incidents" 200 401 || dashboard_ok=0

echo "==> Health check: https://${DOMAIN}/ingest/healthz"
# Phase 15: checked independently of the dashboard API above — a broken
# ingest path with a healthy dashboard (or vice versa) is a real failure
# mode now that they're two different backend containers behind the same
# Caddy. /healthz touches neither the DB nor Redis (see
# api/app/ingest_gateway/main.py), so 200 is the only healthy response.
ingest_ok=1
poll_health "ingest gateway" "https://${DOMAIN}/ingest/healthz" 200 || ingest_ok=0

if [ "$dashboard_ok" = "1" ] && [ "$ingest_ok" = "1" ]; then
  exit 0
else
  exit 1
fi
