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
