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
  echo "infra/.env.prod not found — create it from .env.prod.example first (once, by hand, on this VM)." >&2
  exit 1
fi

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

echo "==> Pulling images"
"${COMPOSE[@]}" pull

echo "==> Running database migrations"
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "==> Restarting containers"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Waiting for the API to come up"
sleep 5

# Extracted with grep/cut, not `source .env.prod` — dotenv values (e.g.
# OPERATOR_PASSWORD_HASH's argon2 hash) legitimately contain literal `$`
# characters that a bash `source` would try to expand as variables.
DOMAIN=$(grep -E '^DOMAIN=' .env.prod | cut -d= -f2-)

echo "==> Health check: https://${DOMAIN}/api/incidents"
# /incidents requires a bearer token (Phase 9) — 200 (would only happen
# with a valid token, not expected here) or 401 (means the server, auth
# dependency, and DB connection are all up and routing correctly) both
# count as healthy. Anything else (connection refused, 5xx, timeout)
# means the deploy is broken.
STATUS=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://${DOMAIN}/api/incidents" || echo "000")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "401" ]; then
  echo "Health check passed (HTTP $STATUS)"
else
  echo "Health check FAILED (HTTP $STATUS)" >&2
  exit 1
fi
