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

# Run every test suite: api (which also runs scripts/tests and
# shared/tests), worker, mcp_server, the Go CLI, and both extractors.
test:
    (cd api && uv run pytest)
    (cd worker && uv run pytest)
    (cd mcp_server && uv run pytest)
    (cd cli && go test ./...)
    (cd extractors/python && uv run pytest)
    (cd extractors/node && npm test)

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
    (cd extractors/python && uv run ruff check .)
    # Go too, so the local gate set matches CI's. Not folded into the
    # ruff lines above: scripts/check_scan_coverage.py parses those for
    # its root list, and a `just cli-lint` line there would be one more
    # thing for it to misread.
    just cli-lint

# Enforce module-isolation contracts (e.g. anomaly detection vs RAG/LLM)
lint-imports:
    # PYTHONIOENCODING: import-linter draws its progress spinner with
    # `rich`, which emits emoji. On Windows, with stdout redirected,
    # rich takes its win32 console path and cp1252 cannot encode them
    # -- the run then exits 1 with a UnicodeEncodeError *after*
    # printing "Contracts: 4 kept, 0 broken". A gate that reports
    # success and then fails is the worst kind of flake, because the
    # obvious reading of the output is that it passed. Linux CI never
    # sees it; this makes the local run agree with CI.
    cd worker && PYTHONIOENCODING=utf-8 uv run lint-imports

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


# --- The culprit CLI and the extractors (Phase 28) --------------------
#
# Go lives in cli/ and is built with CGO_ENABLED=0 so the result is one
# static binary with no libc dependency -- that is acceptance criterion
# 5 ("one static binary, no runtime installed") and the reason `curl |
# sh` can work at all. It is also why the CLI has no tree-sitter
# dependency: the Go binding needs cgo, which would undo exactly this.

# Build the culprit binary for this machine into cli/bin/
cli-build:
    cd cli && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.Version=$(cat ../VERSION)" -o bin/culprit ./cmd/culprit

# Cross-compile every released platform into cli/dist/ (what CI publishes)
cli-release:
    #!/usr/bin/env bash
    set -euo pipefail
    version=$(cat VERSION)
    cd cli
    rm -rf dist && mkdir -p dist
    for target in linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64; do
        os=${target%/*}
        arch=${target#*/}
        name="culprit_${version}_${os}_${arch}"
        [ "$os" = "windows" ] && ext=".exe" || ext=""
        echo "==> $name"
        CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" go build -trimpath             -ldflags "-s -w -X main.Version=${version}"             -o "dist/${name}${ext}" ./cmd/culprit
    done
    ls -la dist/

cli-test:
    cd cli && go test ./...

# Run `culprit check` against Culprit's own repository (Phase 29 field 5).
#
# Dogfooding is the cheapest continuous eval available: this repository
# is a real multi-language system with an OpenAPI surface, an ORM, a
# migration chain, a React frontend calling the API, and about five
# hundred facts across five components. If the comparator starts
# inventing findings, it invents them here first.
#
# `--fail-on=breaks_request_path` rather than the default `degrades`: the
# gate is about faults that break requests, and a stricter threshold in
# our own CI than we recommend to users would be us not believing our own
# default.
#
# **The placeholder env is not optional here.** `just intent` sets it
# because api/app/*/config.py reads those variables at import time and
# introspecting a FastAPI app means importing it. Without them the
# extractor reports `KeyError: JWT_SECRET_KEY` and skips `http_routes`
# and `db_schema` — the two rank-90 enumerating sources — so the check
# runs against a fact set with the route table and the ORM schema
# missing and reports a confident, meaningless zero.
#
# That is exactly the failure this product exists to prevent, shipped in
# its own dogfooding gate: "no findings" that means "nothing looked".
# The Phase 29 audit caught it. Every self-check recipe below therefore
# goes through `_self-check-env`, and none of them invokes the binary
# directly.
self-check *ARGS:
    @just _self-check-env --fail-on=breaks_request_path {{ARGS}}

# The same, as the SARIF file CI uploads for pull-request annotations.
self-check-sarif:
    @just _self-check-env --fail-on=breaks_request_path --format sarif --output ../culprit.sarif

# The §0.1 coverage report: subjects only one source describes, where
# nothing could ever catch a mistake. Not defects — a map of where this
# repository is unverifiable.
self-check-coverage:
    @just _self-check-env --fail-on=any --unverifiable

# The one place the placeholder env lives. Same values as `just intent`.
_self-check-env *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    export JWT_SECRET_KEY=culprit-intent-extraction-placeholder
    export AGENT_AUTOMATION_TOKEN=culprit-intent-extraction-placeholder
    for name in INGEST_GATEWAY API_READER REGISTRY_ADMIN AUTH_SERVICE POSTMORTEM_WRITER FACT_WRITER CAPTURE_WRITER PROBE_WRITER; do
        export "${name}_DATABASE_URL=postgresql+asyncpg://localhost:5432/culprit-intent-placeholder"
    done
    cd cli && exec go run ./cmd/culprit check -f ../culprit.yaml {{ARGS}}

# gofmt is the whole lint story for Go -- `go vet` catches the rest.
# Phase 30: `culprit diff` end to end against two real Compose projects
# (cli/testdata/demo/environments). Pulls postgres:16-alpine and two
# alpine images; needs Docker, uv and node. CI runs the same test in the
# `cli` job.
cli-test-docker:
    cd cli && CULPRIT_DOCKER_TESTS=1 go test ./cmd/culprit -run TestEnvironmentDiffAgainstRealContainers -v

# Phase 30: the Kubernetes adapter against a kind cluster. Creates the
# cluster if it does not exist, applies cli/testdata/kind/fixture.yaml,
# and runs the capture test against it. Needs kind, kubectl and Docker.
cli-test-kind:
    #!/usr/bin/env bash
    set -euo pipefail
    kind get clusters | grep -qx culprit-capture || kind create cluster --name culprit-capture --wait 180s
    kubectl --context kind-culprit-capture apply -f cli/testdata/kind/fixture.yaml
    kubectl --context kind-culprit-capture -n culprit-capture rollout status deployment/orders-api --timeout=180s
    cd cli && CULPRIT_KIND_TESTS=1 CULPRIT_KIND_CONTEXT=kind-culprit-capture go test ./internal/capture -run TestKubernetesCaptureAgainstKind -v

cli-lint:
    #!/usr/bin/env bash
    set -euo pipefail
    cd cli
    unformatted=$(gofmt -l .)
    if [ -n "$unformatted" ]; then
        echo "gofmt would change these files:" >&2
        echo "$unformatted" >&2
        exit 1
    fi
    go vet ./...

# Rewrite the golden files in cli/testdata/fixtures/golden/.
# READ THE DIFF before committing it: a golden file records what the
# extractor currently believes, and updating one without looking is how
# a regression becomes the new expectation.
cli-golden-update:
    cd cli && go test ./internal/extract/... -run TestGoldenFixtures -update

# The two extractor plugins, tested in their own languages against the
# same fixture corpus the Go golden tests use.
extractors-test:
    (cd extractors/python && uv run pytest)
    (cd extractors/node && npm test)

# No `extractors-lint` / `extractors-typecheck` recipes: `just lint` and
# `just typecheck` already cover extractors/python, and a second recipe
# running the same ruff invocation was actively harmful ---
# scripts/check_scan_coverage.py parses the justfile for ruff roots, so
# the duplicate satisfied the coverage check even when the real `lint`
# recipe had stopped covering the directory. Found by mutation-testing
# that gate (standing invariant 10): removing extractors/python from
# `lint` left coverage green, which is the exact failure invariant 9
# exists to prevent, one level up.

# `culprit intent` over this repository itself (culprit.yaml at the
# root) -- the fastest way to see what the command actually prints, and
# the dogfood acceptance criterion 1 is verified against.
#
# The env vars are placeholders, and they live here rather than in
# culprit.yaml on purpose: a manifest names config keys and never
# carries values, and its loader refuses anything credential-shaped.
# These are the same dummy values `just generate-types` and the CI
# schema-dump step already set, for the same reason -- api/app/*/config.py
# reads them at import time, and introspecting a FastAPI app means
# importing it. Nothing here connects to anything.
intent *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    export JWT_SECRET_KEY=culprit-intent-extraction-placeholder
    export AGENT_AUTOMATION_TOKEN=culprit-intent-extraction-placeholder
    for name in INGEST_GATEWAY API_READER REGISTRY_ADMIN AUTH_SERVICE POSTMORTEM_WRITER FACT_WRITER CAPTURE_WRITER PROBE_WRITER; do
        export "${name}_DATABASE_URL=postgresql+asyncpg://localhost:5432/culprit-intent-placeholder"
    done
    cd cli && exec go run ./cmd/culprit intent -f ../culprit.yaml {{ARGS}}

# Type-check all projects. `../shared` rides along on api's pyright for
# the same reason it rides along on api's ruff (see `lint` above).
typecheck:
    (cd api && uv run pyright . ../shared)
    (cd worker && uv run pyright)
    (cd demo-services && uv run pyright)
    (cd mcp_server && uv run pyright)
    (cd extractors/python && uv run pyright)

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
    cd api &&       JWT_SECRET_KEY=local-schema-dump-not-a-real-secret       INGEST_GATEWAY_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       API_READER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       REGISTRY_ADMIN_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       AUTH_SERVICE_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       POSTMORTEM_WRITER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       FACT_WRITER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       CAPTURE_WRITER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       PROBE_WRITER_DATABASE_URL=postgresql+asyncpg://unused:unused@localhost:5432/unused       uv run python -m scripts.dump_openapi_schema > ../frontend/openapi.schema.json
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
