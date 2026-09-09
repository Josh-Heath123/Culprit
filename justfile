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

# Run the test suite for api, worker, and mcp_server
test:
    (cd api && uv run pytest)
    (cd worker && uv run pytest)
    (cd mcp_server && uv run pytest)

# Apply database migrations
migrate: up
    cd api && uv run alembic upgrade head

# Lint all projects. `shared/` and `scripts/` have no venv of their own,
# so they ride along on api's ruff (which picks up the same root ruff.toml
# either way). Both were unlinted before Phase 26 — `shared/` because it
# had no code worth linting until culprit_model landed there, `scripts/`
# for no reason at all: .claude/hooks/fast_gates.sh lints every changed
# Python file wherever it lives, so the hook was stricter than the gate
# and caught pre-existing violations this recipe had never looked at.
lint:
    (cd api && uv run ruff check . ../shared ../scripts ../examples)
    (cd worker && uv run ruff check .)
    (cd demo-services && uv run ruff check .)
    (cd mcp_server && uv run ruff check .)

# Enforce module-isolation contracts (e.g. anomaly detection vs RAG/LLM)
lint-imports:
    cd worker && uv run lint-imports

# Fail if worker/app/db.py's Core tables drift from api/app/db/models.py's
# ORM columns. Run via api's own venv (not a bare `python`/`python3` off
# PATH, which isn't reliably named the same across dev machines and CI) —
# the script only needs a working interpreter, api's is as good as any.
check-schema-drift:
    uv run --project api python scripts/check_schema_drift.py

# Fail if a package declared deterministic (.claude/rules/determinism.md)
# imports an LLM or embedding client (Phase 26). Also a CI step, next to
# lint-imports -- the two enforce the same boundary from different angles:
# import-linter follows the installed import graph of one uv project,
# this walks source text across all of them.
check-no-llm-imports:
    uv run --project api python scripts/check_no_llm_imports.py

# Fail on a declared "must change together" pair (scripts/coupled_files.yaml)
# changing on only one side, or a migration whose upgrade()/downgrade() aren't
# structurally symmetric (Phase 22). Same reasoning as check-schema-drift
# above for running via api's own venv rather than a bare python/python3.
check-invariants:
    uv run --project api python scripts/check_coupled_files.py
    uv run --project api python scripts/check_migration_symmetry.py

# Fail if a repo-wide check's declared roots don't actually cover the
# repository (Phase 27, standing invariant 9). Cheap and offline -- the
# roots are read from the checks themselves, nothing is executed.
check-scan-coverage:
    uv run --project api python scripts/check_scan_coverage.py

# Fail if the migration chain can't round-trip against a real database
# (Phase 27, standing invariant 8): upgrade head -> seed rows ->
# downgrade base -> upgrade head. NOT part of `check-invariants` above:
# it needs Docker and takes ~40s, where everything there is instant and
# offline. Its own CI job for the same reason.
check-migration-round-trip:
    uv run --project api python scripts/check_migration_round_trip.py

# Type-check all projects. `../shared` rides along on api's pyright for
# the same reason it rides along on api's ruff (see `lint` above).
typecheck:
    (cd api && uv run pyright . ../shared)
    (cd worker && uv run pyright)
    (cd demo-services && uv run pyright)
    (cd mcp_server && uv run pyright)

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

# Culprit MCP server (Phase 24) -- stdio transport, register it in a
# Claude Code session's own MCP config (docs/AI_NATIVE_INSTRUMENTATION.md).
# Run from the repo root, not `cd mcp_server &&`: mcp_server/ is a *flat*
# package (pyproject.toml beside __init__.py, not one level above it),
# so `python -m mcp_server` needs a cwd *above* the package directory to
# resolve `import mcp_server` at all.
mcp-server:
    uv run --project mcp_server python -m mcp_server

# RAG + root-cause narrative (Phase 6) — embed and store the seed
# postmortem fixtures. Idempotent; safe to re-run after editing
# worker/app/rag/seed_postmortems.py. Requires VOYAGE_API_KEY in worker/.env.
seed-postmortems:
    cd worker && uv run python -m scripts.seed_postmortems

# Apply a declarative system model from a culprit.yaml (Phase 27,
# replacing Phase 14's `just apply-services`) — e.g.:
#   just apply-model demo-services/culprit.yaml
#   just apply-model demo-services/culprit.yaml --prune
#   just apply-model --export > culprit.yaml
apply-model *ARGS:
    cd api && uv run python -m scripts.apply_model {{ARGS}}

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
# The dummy env vars mirror what .github/workflows/ci-cd.yml sets for the
# same step, and for the same reason: importing app.main runs every
# app/*/config.py module-level read, and those deliberately refuse to
# start without a value (Phase 26, api/app/env.py). Nothing here connects
# to a database -- this only serialises the OpenAPI schema. Without them
# `just generate-types` (and therefore `just frontend`, `just
# frontend-build` and the frontend's Docker build) only worked on a
# machine that already had a hand-written api/.env.
generate-types:
    cd api &&       JWT_SECRET_KEY=local-schema-dump-not-a-real-secret       INGEST_GATEWAY_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       API_READER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       REGISTRY_ADMIN_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       AUTH_SERVICE_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       POSTMORTEM_WRITER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       uv run python -m scripts.dump_openapi_schema > ../frontend/openapi.schema.json
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
    #
    # `--build` is not optional (Phase 26, docs/DIAGNOSTIC_PLAN.md).
    # `bootstrap` is deliberately absent from the `up --build` list above,
    # so without it `run` reuses whatever culprit-quickstart-bootstrap
    # image the machine already has. On a machine that ran quickstart
    # once before, that is a months-old image, and its `alembic upgrade
    # head` upgrades to *its* head, not the repo's -- silently, exit 0,
    # no error anywhere. Found live: a quickstart on this branch left the
    # database at fbf4cb16570a (Phase 16) while every other container ran
    # current code. A fresh machine never sees it, which is exactly why
    # it went unnoticed since Phase 17.
    "${COMPOSE[@]}" run --rm --build bootstrap
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
