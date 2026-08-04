# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: Phases 0–10 built, Phase 11 (CI/CD & deployment) in progress, Phase 12 not started

Updated 2026-08-04. Update this section the moment it changes — a stale status line is worse than none, see this file's own philosophy below.

Data model, demo services, ingestion, anomaly detection, correlation, RAG, the dashboard API, the frontend, JWT auth, and self-observability (Phases 0–10 in `docs/IMPLEMENTATION_PLAN.md`) all have real code — see "Architecture (as implemented)" below for where. Phase 11 has the CI/CD pipeline and production infra files written (`.github/workflows/ci-cd.yml`, `infra/docker-compose.prod.yml`, `infra/deploy.sh`), and the production VM is provisioned, but **no deploy has succeeded yet**. Phase 12 (polish pass) hasn't started.

**The thing most likely to surprise you if you only read code, not this file:** almost none of it is in git yet. `git log` on `dev` shows a single "Initial commit" containing only the skeleton (`docs/`, `justfile`, `ruff.toml`, `infra/docker-compose.yml` for local dev). Everything else — `api/`, `worker/`, `frontend/`, `demo-services/`, `.github/` — is untracked in the working tree as of this writing. `origin/main` has none of it. Don't assume CI has ever run, or that what's on GitHub matches what's on disk here — check `git status` before reasoning about "current" behavior from a deployed/CI perspective.

**Open items blocking the first production deploy**, in the order they'll bite:
1. Commit and push `api/`, `worker/`, `frontend/`, `demo-services/`, `.github/` — none of it exists on the remote yet.
2. `infra/.env.prod` on the VM (`culprit-vm`, Oracle Cloud, currently `92.4.156.135`) still needs real `VOYAGE_API_KEY` and `GEMINI_API_KEY` values — everything else in it is filled in.
3. GitHub Actions repo secrets (`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`) need to exist — confirm, don't assume.
4. `ghcr.io` package visibility: images pushed by the `build` job via `GITHUB_TOKEN` default to **private**. `deploy.sh`'s `docker compose pull` runs on the VM with no registry credentials — the first deploy will 401 unless the `api`/`worker`/`frontend` packages are flipped to public on GitHub (Profile → Packages) after the first successful `build` job, or the VM does a one-time `docker login ghcr.io`.

## What this is

Product name: **Culprit** (decided — see `docs/IMPLEMENTATION_PLAN.md` §3; the earlier "SignalStack" placeholder is gone from product-facing surfaces). The GitHub repo itself is still named **View**, not Culprit — that mismatch is intentional-by-inertia, not a mistake, but it means `ghcr.io/josh-heath123/view/*` image paths, this working folder's name, and every user-facing string (`docker-compose.prod.yml`'s `name: culprit`, the `culprit.co.za` domain, the dashboard UI copy) don't share a name. Don't "fix" this by renaming one to match the other without asking — it's cosmetic, not a bug.

An incident-correlation copilot for small engineering teams running multiple services without a dedicated SRE/observability function. It ingests logs and metrics from 2-3 services, flags anomalies statistically, correlates them across services in time, and — grounded in the team's own past incident postmortems via RAG — suggests a likely root cause instead of just a wall of unrelated alerts.

Full problem/market/monetization writeup: `docs/SPEC.md`. Don't restate that reasoning here or in code comments — it doesn't change how the code should be written.

Full build plan — exact tech stack per layer, phase-by-phase implementation order, product personality/voice spec, and the security/performance checklists: `docs/IMPLEMENTATION_PLAN.md`. Read the specific phase section you're working on, not the whole file — each phase is written to stand alone.

## Scope discipline — read before writing code

This project's biggest risk is scope creep, not technical difficulty. Concretely, for the MVP:

- **Two to three services, hardcoded, not N services configurable.** `demo-services/` has exactly three: `order_service`, `inventory_service`, `payments_service`, plus `shared/` for common fault-injection/OTel/middleware code. Don't build a general multi-tenant ingestion platform.
- **Redis Streams for ingestion, not Kafka.** Kafka is a V2 problem if this ever needs real throughput. Reaching for it now is over-engineering a demo.
- **Statistical anomaly detection only (rolling z-score / EWMA on error rate and latency), not a trained model.** Implemented in `worker/app/anomaly/scorer.py` + `state.py`. Don't build model training infra for the MVP.
- **No Slack bot, no auto-generated postmortems, no per-service learned baselines in the MVP.** These are explicitly V2.

If a session's task doesn't fit inside these boundaries, that's a signal to flag it back to the user, not to quietly expand scope.

## Architecture (as implemented)

Data flow, in order, with where each piece actually lives — understanding this requires reading across every layer, which is why it's summarized here instead of left to be reconstructed file-by-file each session:

1. **Ingestion** — `api/app/ingest_gateway/` (`main.py`, `auth.py`, `otlp_decode.py`, `schemas.py`, `streams.py`), run standalone via `just ingest-gateway`. This ended up as a small custom FastAPI service decoding OTLP payloads directly, not a real OpenTelemetry Collector binary — the demo services push into it using the OTel SDK (`demo-services/shared/otel.py`), and it writes into Redis Streams.
2. **Storage** — `api/app/db/` (`models.py`, `base.py`) + Alembic migrations in `api/migrations/versions/` (core schema, one migration per service's least-privilege DB role — ingest-gateway, anomaly-detector, correlation-engine, root-cause-writer — plus `api_keys`, root-cause fields, and raw-event compression/retention). TimescaleDB + pgvector, one Postgres instance, two roles. A `worker`-side consumer (`worker/app/consumer.py`, run via `just consumer` → `arq app.main.WorkerSettings`) drains the stream into it.
3. **Anomaly detection** — `worker/app/anomaly/` (`scorer.py`, `state.py`, `job.py`). Deterministic, not an LLM call — see the rule below.
4. **Correlation** — `worker/app/correlation/` (`graph.py`, `job.py`). Rule/window-based, not LLM-based — see the rule below.
5. **RAG / root-cause narrative** — `worker/app/rag/`: `embeddings.py` + `retrieval.py` (pgvector similarity search), `context.py` + `prompts.py` + `sanitize.py` (grounding), `llm.py` dispatching to `providers/anthropic_provider.py` or `providers/gemini_provider.py` based on `LLM_PROVIDER` (`.env.prod` currently sets this to `gemini`, the free-tier default). `seed_postmortems.py` (`just seed-postmortems`) embeds the fixture postmortems — idempotent, needs `VOYAGE_API_KEY`.
6. **API / dashboard** — `api/app/incidents/` (`router.py`, `service.py`, `schemas.py`, `transforms.py`, `limiter.py`) serves incident candidates + evidence; `api/app/auth/` is the JWT session layer (Phase 9). `frontend/src/` is React + Vite + TypeScript + Tailwind + shadcn/ui: `components/Dashboard.tsx`, `components/timeline/Timeline.tsx`, `components/incident-detail/` (`IncidentDetailPanel.tsx`, `Evidence.tsx`, `ConfidenceBadge.tsx`), `components/command-palette/CommandPalette.tsx` (cmdk), plus empty/error states per the product-personality voice charter in `docs/IMPLEMENTATION_PLAN.md` §3.

Self-observability (Phase 10) — `api/app/observability.py` and `worker/app/observability.py` — instruments both services with the same OTel approach the product recommends to its users, exporting to the local Grafana+Tempo stack (`infra/docker-compose.yml`) in dev, or a configurable OTLP endpoint in prod (empty by default in `.env.prod` — falls back to console export rather than retrying a dead endpoint).

## Tech stack (decided, don't re-litigate per session)

- **Backend:** Python, FastAPI (`api/`), managed with `uv`
- **Worker / job runner:** Python, `arq` (Redis-backed job queue) — drives the stream-drain consumer and the anomaly/correlation/RAG jobs (`worker/`)
- **Time-series storage:** TimescaleDB (Postgres extension) — reuse the same Postgres instance for relational data
- **Vector storage:** pgvector, same Postgres instance — no separate vector DB for MVP
- **Ingestion transport:** Redis Streams
- **Telemetry collection:** OpenTelemetry SDK in each service, decoded by the custom ingest-gateway (see Architecture step 1)
- **LLM calls:** server-side only (`worker/app/rag/`), never client-side, so usage can be metered later — provider is switchable (Anthropic or Gemini) via `LLM_PROVIDER`
- **Frontend:** React + Vite + TypeScript, Tailwind + shadcn/ui, cmdk for the command palette
- **Deployment:** self-hosted Oracle Cloud Always Free VM (Ubuntu 22.04) + Docker Compose + Caddy for TLS — see Production deployment below

## Where the AI must stay deterministic vs. where an LLM belongs

This is the one rule in this project most likely to get silently violated, because "just ask the LLM" is the path of least resistance and looks fine in a demo:

- **Anomaly detection (is this metric actually unusual) must be statistical, not an LLM judgment call.** It has to run continuously and cheaply, and a hallucinated "this looks fine" here is the failure mode that makes the whole product untrustworthy.
- **Correlation (do these anomalies belong to the same incident) is rule/window-based, not LLM-based.**
- **Only the final root-cause narrative is an LLM call, and only after retrieval has grounded it in real past incidents.** An ungrounded LLM guess at root cause is worse than no suggestion — it reads as confident and is often wrong.

This isn't just a stated intention — CI enforces it structurally. `worker`'s `lint-imports` (import-linter, run via `just lint-imports` and as its own step in the `typecheck` CI job) fails the build if `worker/app/anomaly/` or `worker/app/correlation/` ever imports from `worker/app/rag/`, or vice versa. If a change needs to cross that boundary, that's a signal the rule above is about to be violated, not a lint config problem to silence.

## Production deployment (Phase 11)

Target: a single self-hosted Oracle Cloud Always Free VM, not a managed PaaS (`docs/IMPLEMENTATION_PLAN.md` §7 corrected this from an earlier Fly.io plan after Fly.io dropped its free tier). Current VM: `culprit-vm`, Ubuntu 22.04, public IP `92.4.156.135`, domain `culprit.co.za` (DNS A record already pointed at it). Note the VM ended up on a 2 OCPU / 11 GB **x86_64** flex shape, not the commonly-cited Always Free options (`E2.1.Micro` at 1 OCPU/1GB, or the ARM `A1.Flex` up to 4 OCPU/24GB) — confirmed still within Always Free, but don't assume a fresh Oracle account will land on either textbook shape; check what actually got provisioned. x86_64 is actually convenient here: GitHub Actions' `ubuntu-latest` runners build `amd64` images by default, so no cross-platform/buildx step is needed in `ci-cd.yml`.

Pipeline (`.github/workflows/ci-cd.yml`): lint → typecheck (includes the `lint-imports` contract above) → pytest → build + Trivy scan (CRITICAL/HIGH, blocking) → on `main` only: push `api`/`worker`/`frontend` images to `ghcr.io/josh-heath123/view/*` → SCP `docker-compose.prod.yml` + `deploy.sh` to the VM → SSH in and run `deploy.sh`.

`infra/deploy.sh` order is deliberate and load-bearing: pull images → `alembic upgrade head` → restart containers → health check. Migrating before restarting means no container ever runs code that expects a schema the DB doesn't have yet.

`infra/.env.prod` is created once, by hand, directly on the VM from `infra/.env.prod.example` — never from GitHub Actions secrets, never baked into an image, never committed. Every `$` inside a value (this matters for the argon2 `OPERATOR_PASSWORD_HASH`) must be escaped as `$$`, or Compose's env-file interpolation silently corrupts it — `.env.prod.example`'s header comment covers this in detail, don't re-derive it.

## Setup & commands — verified against the actual `justfile`

Everything routes through `just` (recipes wire up `--env-file infra/.env` and working directories for you — don't run the raw `uvicorn`/`pytest`/`docker compose` commands standalone unless you're intentionally bypassing that).

```bash
# local infra: Postgres+TimescaleDB+pgvector, Redis, Grafana+Tempo
just up / just down

# api with autoreload (brings up infra first)
just dev

# apply migrations (brings up infra first)
just migrate

# full test suite — both api and worker
just test

# single test — don't run the full suite for a one-line change
cd api && uv run pytest tests/path/to/test_file.py::test_name -v
cd worker && uv run pytest tests/path/to/test_file.py::test_name -v

# lint / typecheck / import-boundary contract
just lint
just typecheck
just lint-imports

# demo services (Phase 2) — one per terminal
just demo-order / just demo-inventory / just demo-payments
just demo-load                      # steady baseline traffic
just demo-fault <args>              # e.g. just demo-fault latency inventory-service --delay-ms 800 --duration-s 30

# ingestion pipeline (Phase 3)
just ingest-gateway
just consumer

# RAG seed data (Phase 6) — needs VOYAGE_API_KEY in worker/.env
just seed-postmortems

# frontend (Phase 8)
just frontend        # dev server, talks to `just dev`'s API on :8000 by default
just frontend-build
```

## Token/context efficiency notes for future sessions

- **Don't dump raw ingested logs/metrics into context to debug something.** Query or aggregate first (e.g. `SELECT` a specific window, not a table scan) — this data is high-volume by design.
- **Keep the anomaly-detection module and the RAG/LLM module in separate files with no shared internals.** `lint-imports` enforces this in CI (see above) — a session working on correlation logic shouldn't need to load the LLM prompt-construction code, and vice versa.
- **Don't re-run the full test suite to check a one-line change in an isolated module.** Use the single-test command above.
- **Don't re-read this whole file's "Architecture" section into working memory every session if only touching one layer** — jump to the relevant numbered step.
- **Before reasoning about "what's deployed" or "what CI does," check `git status` first.** See the Status section above — this repo's working tree and `origin/main` are currently very different, and that gap will close over time without this file being updated to say so.
