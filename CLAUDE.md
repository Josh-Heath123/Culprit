# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: self-hosted-product pivot in progress — Phases 0–17 merged and deployed; Phase 18 in progress (uncommitted); Phase 19 next

Updated 2026-08-08. Update this section the moment it changes — a stale status line is worse than none, see this file's own philosophy below.

The self-hosted-product pivot described in earlier revisions of this file is no longer "under consideration" — it's the active plan, and it has its own document: **`docs/SELF_HOSTED_PLAN.md`** (Phases 13–20). That file, not this section, is the source of truth for what each of those phases actually does — read the specific phase section you're working on, same convention as `docs/IMPLEMENTATION_PLAN.md`. `docs/IMPLEMENTATION_PLAN.md` covers Phases 0–12 (the original single-VM build) and is otherwise historical now; don't restate its content here.

Phases 0–11 (original build through CI/CD & first deploy) and Phases 13–17 of the self-hosted pivot are merged into `main` and deployed to `https://culprit.co.za`: frontend routing + a real 404 (13), the service registry replacing hardcoded demo services (14), a public ingest path + instrumentation guide for onboarding a real service (15), multi-user auth replacing the single hardcoded operator account (16), and one-command local quickstart + a real-VM install guide (17). Phase 12 (the original polish-pass phase) was superseded by the pivot and was never done as its own phase — its gaps got picked up piecemeal inside 13–17 instead (e.g. the missing-routing gap it flagged became Phase 13).

**Phase 18 (postmortem write path) is in progress but not committed anywhere** — as of this writing it exists only as uncommitted working-tree changes and untracked new files on a local branch (`phase-18-postmortem-write-path`) that has never been pushed to `origin`. Don't assume `main` or any pushed branch reflects this work; check `git status` and `git log <branch> --oneline` before trusting what "Phase 18" means in a given session. Phase 19 (topology inference from traces) is next and does not depend on Phase 18 — see `docs/SELF_HOSTED_PLAN.md` §2's dependency graph — so it's safe to branch Phase 19 off `main` without waiting on 18, but branch from `main`, not from the phase-18 branch, to avoid dragging its uncommitted/unfinished state along.

**Known repo-hygiene issue, unresolved as of this writing:** there's no `.gitattributes` and `core.autocrlf` is unset, so on Windows checkouts nearly every tracked file can show as "modified" purely from CRLF/LF churn with zero real content change. Before trusting `git status`/`git diff` output in this repo, use `git diff --ignore-space-at-eol` (or `--stat` with the same flag) to see what actually changed. This also means: don't commit a large "everything changed" diff without checking it's not just line-ending noise, and don't be alarmed by a big `git status` — check it filtered first. Fixing this properly (a `.gitattributes` normalizing to LF, plus a one-time renormalization commit) hasn't been done yet; it's a real fix worth doing, not just working around, but hasn't been prioritized over the phase work.

## What this is

Product name: **Culprit** (decided — see `docs/IMPLEMENTATION_PLAN.md` §3; the earlier "SignalStack" placeholder is gone from product-facing surfaces). The GitHub repo itself is still named **View**, not Culprit — that mismatch is intentional-by-inertia, not a mistake, but it means `ghcr.io/josh-heath123/view/*` image paths, this working folder's name, and every user-facing string (`docker-compose.prod.yml`'s `name: culprit`, the `culprit.co.za` domain, the dashboard UI copy) don't share a name. Don't "fix" this by renaming one to match the other without asking — it's cosmetic, not a bug.

An incident-correlation copilot for small engineering teams running multiple services without a dedicated SRE/observability function. It ingests logs and metrics from 2-3 services, flags anomalies statistically, correlates them across services in time, and — grounded in the team's own past incident postmortems via RAG — suggests a likely root cause instead of just a wall of unrelated alerts.

Full problem/market/monetization writeup: `docs/SPEC.md`. Don't restate that reasoning here or in code comments — it doesn't change how the code should be written.

Full build plan for the original single-VM MVP (Phases 0–12) — exact tech stack per layer, phase-by-phase implementation order, product personality/voice spec, and the security/performance checklists: `docs/IMPLEMENTATION_PLAN.md`. Read the specific phase section you're working on, not the whole file — each phase is written to stand alone.

Full plan for the self-hosted-product pivot (Phases 13–20, current work) — dependencies between phases, schema changes, API surfaces, acceptance criteria, known traps: `docs/SELF_HOSTED_PLAN.md`. Same convention: read the phase section you're working on, plus §1's invariants, not the whole file.

## Scope discipline — read before writing code

This project's biggest risk is scope creep, not technical difficulty. Concretely, for the MVP:

- **Two to three services, hardcoded, not N services configurable.** `demo-services/` has exactly three: `order_service`, `inventory_service`, `payments_service`, plus `shared/` for common fault-injection/OTel/middleware code. Don't build a general multi-tenant ingestion platform.
- **Redis Streams for ingestion, not Kafka.** Kafka is a V2 problem if this ever needs real throughput. Reaching for it now is over-engineering a demo.
- **Statistical anomaly detection only (rolling z-score / EWMA on error rate and latency), not a trained model.** Implemented in `worker/app/anomaly/scorer.py` + `state.py`. Don't build model training infra for the MVP.
- **No Slack bot, no auto-generated postmortems, no per-service learned baselines in the MVP.** These are explicitly V2.

If a session's task doesn't fit inside these boundaries, that's a signal to flag it back to the user, not to quietly expand scope. This still holds even with the self-hosted-product direction below in mind — that section is about making the already-correctly-scoped MVP usable by someone else, not an invitation to widen the MVP itself (no Kafka, no trained models, etc. still stand).

## Architecture (as implemented)

Data flow, in order, with where each piece actually lives — understanding this requires reading across every layer, which is why it's summarized here instead of left to be reconstructed file-by-file each session:

1. **Ingestion** — `api/app/ingest_gateway/` (`main.py`, `auth.py`, `otlp_decode.py`, `schemas.py`, `streams.py`), run standalone via `just ingest-gateway`. This ended up as a small custom FastAPI service decoding OTLP payloads directly, not a real OpenTelemetry Collector binary — the demo services push into it using the OTel SDK (`demo-services/shared/otel.py`), and it writes into Redis Streams. `RawEventIn` (the wire shape) lives in `shared/culprit_shared/raw_event.py` — a real installable package, path-dependency in both `api/` and `worker/` — so the worker's stream consumer validates against the exact same model instead of hand-parsing the dict (fixed post-launch; used to be duplicated).
2. **Storage** — `api/app/db/` (`models.py`, `base.py`) + Alembic migrations in `api/migrations/versions/` (core schema, one migration per service's least-privilege DB role — ingest-gateway, anomaly-detector, correlation-engine, root-cause-writer — plus `api_keys`, root-cause fields, and raw-event compression/retention). TimescaleDB + pgvector, one Postgres instance, two roles. A `worker`-side consumer (`worker/app/consumer.py`, run via `just consumer` → `arq app.main.WorkerSettings`) drains the stream into it. `worker/app/db.py`'s Core tables still duplicate `api/app/db/models.py`'s ORM columns by hand (worker/api are separate uv projects, no shared internals for this) — `scripts/check_schema_drift.py` (`just check-schema-drift`, also a CI step) diffs the two and fails the build if they diverge, so drift gets caught immediately instead of silently, the way it did once already (the ORM had `raw_events.id` as `INTEGER` against the real `BIGINT` schema, and four `created_at` columns wrongly non-nullable — both fixed).
3. **Anomaly detection** — `worker/app/anomaly/` (`scorer.py`, `state.py`, `job.py`). Deterministic, not an LLM call — see the rule below. State persists to Redis as plain JSON (`MetricScorer.to_dict()`/`from_dict()`), not pickle — River's `EWVar` has no introspectable state, so scoring uses a second `EWMean` tracking E[x²] instead (verified bit-identical to `EWVar.get()`), which *is* round-trippable.
4. **Correlation** — `worker/app/correlation/` (`graph.py`, `job.py`). Rule/window-based, not LLM-based — see the rule below. `SERVICE_ADJACENCY` now lives in `shared/culprit_shared/services.py`, imported by both `worker` and `demo-services` — still a hardcoded dict of the three demo services' relationships, not inferred or user-configurable (see "Toward a self-hosted product" below).
5. **RAG / root-cause narrative** — `worker/app/rag/`: `embeddings.py` + `retrieval.py` (pgvector similarity search), `context.py` + `prompts.py` + `sanitize.py` (grounding), `llm.py` dispatching to `providers/anthropic_provider.py` or `providers/gemini_provider.py` based on `LLM_PROVIDER` (`.env.prod` currently sets this to `gemini`, the free-tier default). `seed_postmortems.py` (`just seed-postmortems`) embeds the fixture postmortems — idempotent, needs `VOYAGE_API_KEY`. There is still no write path for a real postmortem after a real incident — this only ever seeds the fixture set once.
6. **API / dashboard** — `api/app/incidents/` (`router.py`, `service.py`, `schemas.py`, `transforms.py`, `limiter.py`) serves incident candidates + evidence. `api/app/auth/` is the JWT session layer (originally Phase 9's single hardcoded operator account — **superseded by Phase 16**, see point 9 below: it's a real `users` table with roles now, not `OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH`). `frontend/src/` is React + Vite + TypeScript + Tailwind + shadcn/ui: `components/Dashboard.tsx`, `components/timeline/Timeline.tsx`, `components/incident-detail/` (`IncidentDetailPanel.tsx`, `Evidence.tsx`, `ConfidenceBadge.tsx`), `components/command-palette/CommandPalette.tsx` (cmdk), plus empty/error states per the product-personality voice charter in `docs/IMPLEMENTATION_PLAN.md` §3. `components/auth/LoginScreen.tsx` + `hooks/useAuth.ts` + `lib/auth.ts` (in-memory JWT — deliberately not localStorage, so a refresh means logging in again) wire the dashboard to that auth layer; `lib/api.ts` attaches it as `Authorization: Bearer <token>` on every request and clears it on any 401, bouncing back to the login screen (this was completely missing at first launch — the deployed dashboard couldn't load any data until it was added). `frontend/src/lib/types.ts` re-exports from `src/lib/api-types.generated.ts`, generated from api's live OpenAPI schema (`api/scripts/dump_openapi_schema.py` + `openapi-typescript`, via `just generate-types` — both gitignored, regenerated on every dev/build, not hand-maintained anymore).

Self-observability (Phase 10) — `api/app/observability.py` and `worker/app/observability.py` — instruments both services with the same OTel approach the product recommends to its users, exporting to the local Grafana+Tempo stack (`infra/docker-compose.yml`) in dev, or a configurable OTLP endpoint in prod (empty by default in `.env.prod` — falls back to console export rather than retrying a dead endpoint).

The self-hosted-pivot phases (`docs/SELF_HOSTED_PLAN.md`), each adding a distinct DB role/engine on top of the above rather than replacing it:

7. **Frontend routing (Phase 13)** — `react-router-dom`; `frontend/src/routes/AppRoutes.tsx`, `RequireAuth.tsx`, `NotFound.tsx`. Before this, `App.tsx` was just `token ? <Dashboard /> : <LoginScreen />` and every URL rendered identically. `selectedIncidentId` now lives in the URL, not component state.
8. **Service registry (Phase 14)** — `api/app/registry/` (`router.py`, `service.py`, `keys.py`, `schemas.py`, `config.py`), a `registry-admin` DB role/engine distinct from `api-reader`. Services and their API keys are now rows in `services`/`service_dependencies`/`api_keys`, managed via **Settings → Services** in the dashboard or `just apply-services <file.yaml>` (`api/scripts/apply_services.py`, declarative — see `infra/demo-services.yaml`), not hardcoded in `shared/culprit_shared/services.py` and a literal migration anymore. `worker/app/correlation/graph.py` reads adjacency from the DB now, passed in as a parameter rather than importing the old hardcoded dict.
9. **Multi-user auth (Phase 16)** — replaces Phase 9's single operator account. `api/app/auth/` now has a real `users` table (`repository.py`, `users_router.py`), `admin`/`member` roles (`require_admin` vs `require_auth` in `dependencies.py`), and a new `auth-service` DB role/engine for writes; `api/scripts/create_user.py` (`just create-user <username> --role admin`) creates the first admin. `frontend/src/routes/SettingsUsers.tsx` + `components/auth/ChangePasswordDialog.tsx` are the UI for it. The old `OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH` env vars are now migration-time-only inputs (read once by `api/migrations/versions/fbf4cb16570a_create_users_table.py`'s backfill), not read by application code at all.
10. **Public ingest path + instrumentation guide (Phase 15)** — `ingest-gateway` is now reachable from outside the Docker network (previously only `frontend` was published), so a real third-party service can actually push telemetry in. `docs/INSTRUMENTATION.md` is the copyable guide for doing that against a real service, as opposed to `demo-services/shared/otel.py` which is demo-only.
11. **One-command quickstart + real-VM install guide (Phase 17)** — `scripts/bootstrap_env.py` generates all secrets (including the newer `REGISTRY_ADMIN_DB_PASSWORD`/`AUTH_SERVICE_DB_PASSWORD`) instead of ~10 being hand-generated; `just quickstart` brings up a full working stack + three demo services + an auto-injected fault against `infra/docker-compose.quickstart.yml`, entirely via Docker (no local Python/uv needed, `bootstrap_env.py` runs inside a throwaway container). `docs/INSTALL.md` is the equivalent guide for a real VM (what `docs/IMPLEMENTATION_PLAN.md`'s Production deployment section below used to be the only source for). `just bootstrap-env --domain <domain>` is the prompted, non-quickstart version of the same secret-generation script.
12. **Postmortem write path (Phase 18, in progress, not yet committed)** — `api/app/postmortems/` (a fourth DB role/engine, `postmortem-writer`), `worker/app/rag/embed_job.py` (the arq job, event-driven off `POST`/`PATCH /postmortems`, not the seed script's one-off backfill), `frontend/src/routes/PostmortemEditor.tsx`/`PostmortemList.tsx`. Before this, the only postmortems that existed were the eight fixtures `worker/scripts/seed_postmortems.py` loads once — a team could never add its own. See the Status section above for why this isn't safe to assume present in any given session yet.

## Tech stack (decided, don't re-litigate per session)

- **Backend:** Python, FastAPI (`api/`), managed with `uv`
- **Worker / job runner:** Python, `arq` (Redis-backed job queue) — drives the stream-drain consumer and the anomaly/correlation/RAG jobs (`worker/`)
- **Shared contracts:** `shared/culprit_shared/` — a real installable package, path-dependency in both `api/` and `worker/`'s `pyproject.toml`. `raw_event.py` (`RawEventIn`) and `services.py` (adjacency/topology) live here so api/worker validate against and reference the exact same definitions instead of hand-duplicating them.
- **Time-series storage:** TimescaleDB (Postgres extension) — reuse the same Postgres instance for relational data
- **Vector storage:** pgvector, same Postgres instance — no separate vector DB for MVP
- **Ingestion transport:** Redis Streams
- **Telemetry collection:** OpenTelemetry SDK in each service, decoded by the custom ingest-gateway (see Architecture step 1)
- **LLM calls:** server-side only (`worker/app/rag/`), never client-side, so usage can be metered later — provider is switchable (Anthropic or Gemini) via `LLM_PROVIDER`
- **Frontend:** React + Vite + TypeScript, Tailwind + shadcn/ui, cmdk for the command palette, `openapi-typescript` for generated API types (needs `typescript` pinned to whatever range `openapi-typescript`'s peer dependency allows — currently `^5.x`; check before bumping either)
- **Deployment:** self-hosted Oracle Cloud Always Free VM (Ubuntu 22.04) + Docker Compose + Caddy for TLS — see Production deployment below

## Where the AI must stay deterministic vs. where an LLM belongs

This is the one rule in this project most likely to get silently violated, because "just ask the LLM" is the path of least resistance and looks fine in a demo:

- **Anomaly detection (is this metric actually unusual) must be statistical, not an LLM judgment call.** It has to run continuously and cheaply, and a hallucinated "this looks fine" here is the failure mode that makes the whole product untrustworthy.
- **Correlation (do these anomalies belong to the same incident) is rule/window-based, not LLM-based.**
- **Only the final root-cause narrative is an LLM call, and only after retrieval has grounded it in real past incidents.** An ungrounded LLM guess at root cause is worse than no suggestion — it reads as confident and is often wrong.

This isn't just a stated intention — CI enforces it structurally. `worker`'s `lint-imports` (import-linter, run via `just lint-imports` and as its own step in the `typecheck` CI job) fails the build if `worker/app/anomaly/` or `worker/app/correlation/` ever imports from `worker/app/rag/`, or vice versa. If a change needs to cross that boundary, that's a signal the rule above is about to be violated, not a lint config problem to silence.

## Production deployment (Phase 11) — done, live at culprit.co.za

Target: a single self-hosted Oracle Cloud Always Free VM, not a managed PaaS (`docs/IMPLEMENTATION_PLAN.md` §7 corrected this from an earlier Fly.io plan after Fly.io dropped its free tier). Current VM: `culprit-vm`, Ubuntu 22.04, public IP `92.4.156.135`, domain `culprit.co.za`. VM is on a 2 OCPU / 11 GB **x86_64** flex shape, not the commonly-cited Always Free options (`E2.1.Micro` at 1 OCPU/1GB, or the ARM `A1.Flex` up to 4 OCPU/24GB) — confirmed still within Always Free, but don't assume a fresh Oracle account will land on either textbook shape. x86_64 is convenient here: GitHub Actions' `ubuntu-latest` runners build `amd64` images by default, no cross-platform/buildx step needed.

Pipeline (`.github/workflows/ci-cd.yml`): lint → typecheck (includes the `lint-imports` contract above) → pytest → build + Trivy scan (CRITICAL/HIGH, blocking) → on `main` only: push `api`/`worker`/`frontend` images to `ghcr.io/josh-heath123/view/*` → SCP `docker-compose.prod.yml` + `deploy.sh` to the VM → SSH in and run `deploy.sh`. `infra/deploy.sh` order is deliberate: pull images → `alembic upgrade head` → restart containers → health check (now a retry loop, not a single flat `sleep 5` + curl — see below). `infra/.env.prod` is created once, by hand, on the VM from `.env.prod.example` — never from GitHub Actions secrets, never baked into an image, never committed; every literal `$` in a value (matters for the argon2 `OPERATOR_PASSWORD_HASH`) must be escaped as `$$`.

**Real issues hit getting the first deploy green — don't reintroduce these if touching CI/Docker again:**
- `aquasecurity/trivy-action` retired all un-prefixed version tags (e.g. `0.24.0`) after a supply-chain-attack response; only `v`-prefixed tags exist now (pinned to `v0.36.0`).
- `api/` and `worker/` both depend on `shared/` (the `culprit-shared` path dependency). Their Docker builds use the **repo root** as context (`context: .`, `file: api/Dockerfile` in `ci-cd.yml`'s build matrix), not their own subdirectory — otherwise `shared/` is invisible to the build and `uv sync` fails with "Distribution not found." `frontend/` has no such dependency and keeps its own directory as context. There's a root `.dockerignore` for this reason; `api/.dockerignore` and `worker/.dockerignore` no longer exist (dead once their directory stopped being the build context).
- `frontend/src/lib/api-types.generated.ts` is gitignored and generated from `api`'s live OpenAPI schema — the frontend Docker build can't reach `api`'s Python, so CI generates it on the runner (`api/scripts/dump_openapi_schema.py` + `npm run generate-types`) *before* the Docker build step, for the frontend matrix entry only. That generation step imports `app.main`, which needs the same dummy `JWT_SECRET_KEY`/`OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH` env vars the `pytest (api)` job already sets, or it fails on import.
- `ghcr.io` images pushed via `GITHUB_TOKEN` default to **private** — `deploy.sh`'s `docker compose pull` on the VM needs either the packages flipped to public (GitHub → Packages → visibility), or a one-time `docker login ghcr.io` on the VM using a **classic** PAT with `read:packages` scope (fine-grained PATs don't support Packages access yet, confirmed against GitHub's own docs as of this writing).
- Caddy's first-ever Let's Encrypt cert issuance for a fresh domain took ~10s in practice — longer than the original flat `sleep 5` + 10s curl timeout budgeted for. `deploy.sh`'s health check now polls (12 attempts, 5s apart) instead of checking once.

**Since this section was written, three more DB roles/engines (Phases 14/16/18) have joined `ingest-gateway`/`anomaly-detector`/`correlation-engine`/`root-cause-writer` in `infra/.env.prod`** — `registry-admin`, `auth-service`, and (once Phase 18 merges) `postmortem-writer`. `scripts/bootstrap_env.py` generates all of these now; the manual "~10 hand-generated secrets" process this section used to be the only record of is superseded by `docs/INSTALL.md` (Phase 17) — follow that doc for a real install, not a reconstruction from memory of what this section says.

## Toward a self-hosted, downloadable product — in progress, tracked in docs/SELF_HOSTED_PLAN.md

This used to be a speculative backlog section listing 7 gaps blocking a third party from downloading this and running it against their own services. That plan is now underway (`docs/SELF_HOSTED_PLAN.md`, Phases 13–20) and most of the original gaps are closed:

1. ~~Services are hardcoded, not configured.~~ **Done (Phase 14)** — service registry, see Architecture point 8 above.
2. **Correlation's adjacency is hand-specified, not inferred.** Still open — this is Phase 19 (topology inference from traces), next up as of this writing.
3. ~~RAG has no postmortem write path.~~ **In progress (Phase 18)**, uncommitted — see Status above.
4. ~~Auth is one hardcoded operator account.~~ **Done (Phase 16)** — see Architecture point 9 above.
5. ~~Setup friction is real.~~ **Done (Phase 17)** — `just quickstart` + `scripts/bootstrap_env.py` + `docs/INSTALL.md`, see Architecture point 11 above.
6. ~~`ingest-gateway` isn't exposed to the internet.~~ **Done (Phase 15)** — see Architecture point 10 above.
7. ~~No generic instrumentation guide.~~ **Done (Phase 15)** — `docs/INSTRUMENTATION.md`.

What's left, per `docs/SELF_HOSTED_PLAN.md` §2's dependency graph: Phase 18 (finish + commit + merge), Phase 19 (topology inference, next), Phase 20 (release engineering — docs, upgrade path, and the repo/product name reconciliation the "What this is" section above flags as a real decision, not a mechanical rename). Read the specific phase section before starting it, not this summary — this list exists for orientation, not as a substitute for the plan's actual acceptance criteria, known traps, and rollback sections.

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

# lint / typecheck / import-boundary contract / schema-drift check
just lint
just typecheck
just lint-imports
just check-schema-drift

# demo services (Phase 2) — one per terminal
just demo-order / just demo-inventory / just demo-payments
just demo-load                      # steady baseline traffic
just demo-fault <args>              # e.g. just demo-fault latency inventory-service --delay-ms 800 --duration-s 30

# ingestion pipeline (Phase 3)
just ingest-gateway
just consumer

# RAG seed data (Phase 6) — needs VOYAGE_API_KEY in worker/.env
just seed-postmortems

# frontend (Phase 8) — both depend on generate-types (needs api's venv + frontend's node_modules)
just frontend        # dev server, talks to `just dev`'s API on :8000 by default
just frontend-build
just generate-types  # regenerates frontend/openapi.schema.json + src/lib/api-types.generated.ts

# service registry (Phase 14) — declarative service list, e.g. infra/demo-services.yaml
just apply-services <file.yaml>            # add --prune to remove services not in the file

# multi-user auth (Phase 16) — the only way to create the first admin account
just create-user <username> --role admin

# one-command local quickstart (Phase 17) — full stack + demo services + an
# auto-injected fault via docker-compose.quickstart.yml, Docker-only, no uv needed
just quickstart
just quickstart-down

# secret generation for a real (non-quickstart) install — docs/INSTALL.md
just bootstrap-env --domain <domain>
```

To actually see the pipeline detect something end-to-end (locally — `demo-services` was deliberately never added to `docker-compose.prod.yml`, see "Toward a self-hosted product" point 6 for why production has no telemetry source): bring up infra + migrate, run `ingest-gateway` + `consumer` + all three `demo-*` services + `demo-load` each in their own terminal, let baseline traffic run for a minute or two so the anomaly scorer has history to compare against, then `just demo-fault latency inventory-service --delay-ms 800 --duration-s 30` (or the `errors` variant). An anomaly → incident → root-cause narrative should appear on the dashboard within the next few 5-second worker cron cycles.

## Token/context efficiency notes for future sessions

- **Don't dump raw ingested logs/metrics into context to debug something.** Query or aggregate first (e.g. `SELECT` a specific window, not a table scan) — this data is high-volume by design.
- **Keep the anomaly-detection module and the RAG/LLM module in separate files with no shared internals.** `lint-imports` enforces this in CI (see above) — a session working on correlation logic shouldn't need to load the LLM prompt-construction code, and vice versa.
- **Don't re-run the full test suite to check a one-line change in an isolated module.** Use the single-test command above.
- **Don't re-read this whole file's "Architecture" section into working memory every session if only touching one layer** — jump to the relevant numbered step.
- **Check `git status` and the current branch before trusting what "the codebase" means in a session.** This caveat was removed once already (2026-08-04, when everything actually was committed and pushed) and had to come back: Phase 18 is currently uncommitted on an unpushed local branch (see Status above), and Windows checkouts of this repo can show large `git diff` output that's pure line-ending noise (see Status above) rather than real changes. Don't assume `main` reflects the latest work, and don't assume a big diff is real without checking `--ignore-space-at-eol` first.
