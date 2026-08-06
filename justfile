set shell := ["bash", "-uc"]

default:
    @just --list

# Bring up local infra: Postgres+TimescaleDB+pgvector, Redis, Grafana+Tempo
up:
    docker compose --env-file infra/.env -f infra/docker-compose.yml up -d

# Tear down local infra
down:
    docker compose --env-file infra/.env -f infra/docker-compose.yml down

# Bring up infra, then run the API with autoreload
dev: up
    cd api && uv run uvicorn app.main:app --reload

# Run the test suite for both api and worker
test:
    (cd api && uv run pytest)
    (cd worker && uv run pytest)

# Apply database migrations
migrate: up
    cd api && uv run alembic upgrade head

# Lint both projects
lint:
    (cd api && uv run ruff check .)
    (cd worker && uv run ruff check .)
    (cd demo-services && uv run ruff check .)

# Enforce module-isolation contracts (e.g. anomaly detection vs RAG/LLM)
lint-imports:
    cd worker && uv run lint-imports

# Fail if worker/app/db.py's Core tables drift from api/app/db/models.py's
# ORM columns. Run via api's own venv (not a bare `python`/`python3` off
# PATH, which isn't reliably named the same across dev machines and CI) —
# the script only needs a working interpreter, api's is as good as any.
check-schema-drift:
    uv run --project api python scripts/check_schema_drift.py

# Type-check both projects
typecheck:
    (cd api && uv run pyright)
    (cd worker && uv run pyright)
    (cd demo-services && uv run pyright)

# Demo services (Phase 2) — run each in its own terminal
demo-inventory:
    cd demo-services && uv run uvicorn inventory_service.main:app --port 8002 --reload

demo-payments:
    cd demo-services && uv run uvicorn payments_service.main:app --port 8003 --reload

demo-order:
    cd demo-services && uv run uvicorn order_service.main:app --port 8001 --reload

# Steady baseline traffic against order-service
demo-load:
    cd demo-services && uv run python load_generator.py

# Trigger/inspect fault injection, e.g.: just demo-fault latency inventory-service --delay-ms 800 --duration-s 30
demo-fault *ARGS:
    cd demo-services && uv run python fault_cli.py {{ARGS}}

# Ingestion pipeline (Phase 3)
ingest-gateway:
    cd api && uv run uvicorn app.ingest_gateway.main:app --port 8010 --reload

consumer:
    cd worker && uv run arq app.main.WorkerSettings

# RAG + root-cause narrative (Phase 6) — embed and store the seed
# postmortem fixtures. Idempotent; safe to re-run after editing
# worker/app/rag/seed_postmortems.py. Requires VOYAGE_API_KEY in worker/.env.
seed-postmortems:
    cd worker && uv run python -m scripts.seed_postmortems

# Apply a declarative service list (Phase 14) — e.g.:
#   just apply-services demo-services.yaml
#   just apply-services demo-services.yaml --prune
apply-services *ARGS:
    cd api && uv run python -m scripts.apply_services {{ARGS}}

# Create a user (Phase 16) — the only way to create the *first* admin;
# prompts for the password. e.g.: just create-user operator --role admin
create-user *ARGS:
    cd api && uv run python -m scripts.create_user {{ARGS}}

# Regenerate frontend/src/lib/api-types.generated.ts from api's live
# OpenAPI schema (openapi-typescript) — the single source of truth is
# api/app/incidents/schemas.py; frontend/src/lib/types.ts just re-exports
# pieces of the generated file instead of hand-duplicating it (Phase 11
# P1 fix). Needs api's venv (to introspect the schema, no server/DB
# required) and frontend's node_modules (openapi-typescript itself).
generate-types:
    cd api && uv run python -m scripts.dump_openapi_schema > ../frontend/openapi.schema.json
    cd frontend && npm run generate-types

# Frontend dev server (Phase 8) — talks to the dashboard API from `just dev`
# (Phase 7, port 8000 by default), configurable via frontend/.env's VITE_API_URL.
frontend: generate-types
    cd frontend && npm run dev

frontend-build: generate-types
    cd frontend && npm run build

# One-command local quickstart (Phase 17): builds every image locally and
# brings up a working Culprit + the three demo services at
# http://localhost. Needs only Docker and `just` on the host -- no
# Python/uv required, even for bootstrap_env.py below, which runs inside
# a throwaway python:3.12-slim container instead of on the host. Safe to
# re-run: infra/.env.prod is generated once and reused, and
# docker-compose.quickstart.yml's `bootstrap` service is itself
# idempotent (see its own comments).
quickstart:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f infra/.env.prod ]; then
        echo "==> Generating infra/.env.prod"
        # MSYS_NO_PATHCONV: on Windows Git Bash, MSYS rewrites any
        # argument that looks like a Unix absolute path (e.g. /repo)
        # into a Windows path before docker ever sees it, breaking -w.
        # A no-op everywhere else (Linux/macOS bash don't look at it).
        MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/repo" -w /repo python:3.12-slim python scripts/bootstrap_env.py --local
    else
        echo "==> infra/.env.prod already exists, reusing it"
    fi
    COMPOSE=(docker compose -f infra/docker-compose.quickstart.yml --env-file infra/.env.prod)
    echo "==> Building and starting Culprit"
    "${COMPOSE[@]}" up -d --build postgres redis api ingest-gateway worker frontend
    echo "==> Running bootstrap (migrations, demo service registration, admin user)"
    # `run`, not part of the `up` above: `up -d` only waits for containers
    # to *start*, not for a one-shot container's script to *finish* --
    # bootstrap writes demo-services/.env, which the demo profile below
    # reads via env_file: at container-creation time (a one-time read, not
    # re-read live), so the demo containers starting before bootstrap
    # actually finishes is a real race, not a hypothetical one (caught
    # live while verifying this end to end -- order-service came up
    # without a valid key the first time this was wired as two `up`
    # calls). `run --rm` blocks until bootstrap's script exits.
    "${COMPOSE[@]}" run --rm bootstrap
    echo "==> Building and starting the demo services"
    "${COMPOSE[@]}" --profile demo up -d --build order-service inventory-service payments-service load-generator
    echo "==> Scheduling an automatic fault injection in 90s"
    # Steady baseline traffic alone won't trip the anomaly scorer -- it IS
    # the baseline (CLAUDE.md's own manual-verification walkthrough
    # injects a fault for the same reason). Without this, "a real
    # correlated incident... within ~5 minutes" (the acceptance criterion
    # this recipe exists to satisfy) would depend on the user separately
    # discovering and running a fault-injection command themselves.
    # Run as a DETACHED container (`-d`), not a nohup'd/disowned background
    # shell job -- a `&`-backgrounded process is a child of this recipe's
    # own shell and is not guaranteed to survive that shell exiting (some
    # environments tear down a process's whole job/group on exit
    # regardless of nohup; caught live while verifying this). A detached
    # container is supervised by the Docker daemon instead, independent of
    # this shell entirely. Uses a throwaway curl image on the compose
    # network directly (not `just demo-fault`, which shells out to
    # `uv run` -- unavailable by design on a host that only has Docker and
    # just) so this needs nothing beyond what quickstart already requires.
    docker run -d --rm --network culprit-quickstart_default \
        curlimages/curl:latest sh -c \
        'sleep 90 && curl -s -X POST http://inventory-service:8002/admin/fault/latency -H "Content-Type: application/json" -d "{\"delay_ms\": 800, \"duration_s\": 30}"' \
        >/dev/null
    echo ""
    echo "Culprit is running at http://localhost"
    admin_user=$(grep -E '^QUICKSTART_ADMIN_USERNAME=' infra/.env.prod | cut -d= -f2-)
    admin_pass=$(grep -E '^QUICKSTART_ADMIN_PASSWORD=' infra/.env.prod | cut -d= -f2-)
    echo "Log in as: ${admin_user} / ${admin_pass}"
    echo "A fault will auto-inject in ~90s; an incident with a root-cause narrative"
    echo "should appear within about 5 minutes. To trigger another fault yourself:"
    echo "  docker run --rm --network culprit-quickstart_default curlimages/curl:latest \\"
    echo "    -X POST http://inventory-service:8002/admin/fault/latency \\"
    echo "    -H 'Content-Type: application/json' -d '{\"delay_ms\": 800, \"duration_s\": 30}'"

# Tear down the local quickstart (containers + demo profile; named
# volumes, and infra/.env.prod / demo-services/.env, are left in place so
# a following `just quickstart` doesn't regenerate secrets or keys).
quickstart-down:
    docker compose -f infra/docker-compose.quickstart.yml --env-file infra/.env.prod --profile demo down

# Generate infra/.env.prod for a real install (docs/INSTALL.md) -- prompts
# for DOMAIN, LLM_PROVIDER, and the relevant API keys. e.g.:
#   just bootstrap-env --domain example.com
# `just quickstart` calls scripts/bootstrap_env.py --local directly
# instead of this recipe (no prompts needed there).
bootstrap-env *ARGS:
    MSYS_NO_PATHCONV=1 docker run --rm -it -v "$(pwd):/repo" -w /repo python:3.12-slim python scripts/bootstrap_env.py {{ARGS}}
