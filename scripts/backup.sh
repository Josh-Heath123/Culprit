#!/usr/bin/env bash
# Backs up the running deployment's Postgres database via `pg_dump` inside
# the already-running `postgres` container — no separate pg_dump/psql
# client needed on the host, same reasoning as infra/deploy.sh running
# one-off commands through `docker compose run`/`exec` rather than
# assuming host tooling.
#
# Run this from the same directory infra/deploy.sh runs from (~/culprit on
# a real VM install, or the repo root for local/quickstart use) — it looks
# for docker-compose.prod.yml and .env.prod next to itself by default; see
# --compose-file/--env-file to override for docker-compose.quickstart.yml.
#
# Always run this before an upgrade (docs/UPGRADING.md) — a migration
# that turns out wrong is far cheaper to recover from with a backup than
# without one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$SCRIPT_DIR/../infra/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/../infra/.env.prod}"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/../backups}"

while [ $# -gt 0 ]; do
  case "$1" in
    --compose-file) COMPOSE_FILE="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE not found — pass --env-file, or run this next to your infra/.env.prod." >&2
  exit 1
fi

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

# POSTGRES_USER/POSTGRES_DB come from .env.prod via the postgres service's
# own env_file (infra/docker-compose.prod.yml) — read the same way here so
# this never needs its own copy of those values.
POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)

mkdir -p "$OUT_DIR"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT_FILE="$OUT_DIR/culprit-${TIMESTAMP}.sql.gz"

echo "==> Dumping ${POSTGRES_DB} from the running postgres container"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > "$OUT_FILE"

echo "==> Wrote $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
echo "See docs/LIMITS.md for what this backup actually needs to cover."

# To restore, see docs/UPGRADING.md's "Restoring a backup" section —
# restore into a database that has already had `alembic upgrade head`
# run against it (so this project's DB roles already exist; the dump's
# own GRANT statements reference them and error, harmlessly, on a bare
# instance) and that has no conflicting data in it yet.
