# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: Phases 0–31.2 merged, Phase 31 signed off 2026-11-03 (PR #19). Phase 25 cancelled. Current work is the diagnostic-engine rewrite, `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35, with 31.1, 31.2 and 32.1 inserted). **Phase 32 part 1 (the isolation walk, in the binary) is in progress on `phase-32-isolation-walk`** — `culprit diagnose`, `cli/internal/isolate`, the Investigation model and the fault library built, audited and locally green (fault library 6/6); awaiting the human's commit and CI on the merge result (`docs/HANDOFF.md` §5). Part 2 (storage, API, the view) follows a review. A red `deploy` no longer holds a phase open — that decision was taken 2026-09-12 and production deploy is now tracked as operations, not a gate (`docs/HANDOFF.md` §1, §4 "VM remediation"). **Production still has not deployed since Phase 13**: the VM's `.env.prod` lacks every secret added since, and pulls pre-rename `ghcr.io/josh-heath123/view/*` images, so `culprit.co.za` serves a pre-Phase-14 API.

Updated 2026-11-04. Update this section the moment it changes — a stale status line is worse than none, and this section was four phases stale until Phase 26 repaired it, which is exactly the cost being warned about.

**Read `docs/HANDOFF.md` first, every session.** It is the state carrier between the architecture conversation and the implementation session: §1 says which phase is current and whether the gates are green, §4 is the phase ledger, §5 is the last run report. (§2, the decisions register, and §3, the open-questions list, were **retired 2026-09-12**; decisions of record are `docs/DIAGNOSTIC_PLAN.md` §1 D1–D8, and the retired content is in `git log docs/HANDOFF.md`.) This file describes the repository; `HANDOFF.md` describes where the work is.

**Plan of record: `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35).** Culprit is being rewritten from an incident-correlation copilot into a diagnostic engine built on three planes of truth — INTENT (what the system is supposed to do), CONFIGURED (what an environment is set up to do), OBSERVED (what actually happened) — with divergence between them as the finding. Read §1 (architectural decisions D1–D8), §2 (the core model) and the specific phase section you are working on; not the whole file. The earlier plans are historical: `docs/IMPLEMENTATION_PLAN.md` covers Phases 0–12 (the original single-VM build), `docs/SELF_HOSTED_PLAN.md` Phases 13–20 (the self-hosted-product pivot), `docs/AI_NATIVE_PLAN.md` Phases 21–25.

Merged into `main` (only Phases 0–13 are actually deployed to `https://culprit.co.za` — every deploy since Phase 14 has failed on the VM, see `docs/HANDOFF.md` §3 Q15):

- **Phases 0–12** — the original build, through CI/CD and the first deploy. (Phase 12, the polish pass, was superseded and never done as its own phase; its gaps were picked up inside 13–17.)
- **Phases 13–20** — the self-hosted pivot: frontend routing and a real 404 (13), the service registry replacing hardcoded demo services (14), a public ingest path plus `docs/INSTRUMENTATION.md` (15), multi-user auth replacing the single operator account (16), `just quickstart` and `docs/INSTALL.md` (17), the postmortem write path (18), trace-based topology inference (19), release engineering and the repo rename to `Culprit` (20).
- **Phases 21–24** — the AI-native pass (`docs/AI_NATIVE_PLAN.md`): engineering memory generalising postmortems into `architecture_decisions` and `ai_change_records` (21), the deterministic hook-time invariant checks `scripts/check_migration_symmetry.py` and `scripts/check_coupled_files.py` (22), wiring those two together and into the correlation pipeline (23), and `mcp_server/` — read-only MCP tools over that memory, plus the `mcp-reader` DB role (24).

**Phase 25 (scoped visualization) is cancelled. Do not implement it** — see `docs/HANDOFF.md` §1.

**Phases 26, 26.1 and 27 are merged into `main`** (`d39ca3b`, `4b7dbef`, `4f6e437`). 26 removed known-false claims from the repository, fixed the security and fail-open defects the plan's reconnaissance found, and landed `shared/culprit_model/` plus the `captures`/`intent_facts`/`configured_facts`/`readings`/`divergences` tables. 26.1 made `configured_facts` structurally unable to hold an ungranted config value (architecture point 18).

**Phase 27 (the system model) is merged.** It replaced `services`/`service_dependencies` with `components`/`connections`/`contracts` — see architecture point 19.

**Phases 28 and 29 are merged** (PR #15, PR #16) — see architecture points 20 and 21. **Phase 30 (environment capture and cross-environment diff) is on `main` as `c5ce4eb`, with CI red on two pre-existing failures and nothing deployed** — see architecture point 22 and `docs/HANDOFF.md` §1. **Deploying it needs two new lines in the VM's `infra/.env.prod` first** (`CAPTURE_WRITER_DB_PASSWORD`, `CAPTURE_WRITER_DATABASE_URL` — docs/UPGRADING.md): the migration and the api both refuse to start without them. As with every phase, don't assume `main` reflects any of this until it is merged; check `docs/HANDOFF.md` §1, `git status` and `git log <branch> --oneline`.

**Still genuinely outstanding, and not something a session can finish on its own:** the `ghcr.io` packages (`api`/`worker`/`frontend`/`mcp_server`, and from Phase 30 `cli`) still default to **private** under `GITHUB_TOKEN`. Flipping them to public needs a human with repo admin access in the GitHub UI (Packages → each package → Package settings → Change visibility); the `gh` CLI token in this environment lacks `read:packages`/`write:packages`. Until that happens, `docs/SELF_HOSTED_PLAN.md` Phase 20's first acceptance criterion ("a machine with no GitHub account can `docker compose pull` every image") is not met, whatever else claims otherwise.

**Known repo-hygiene issue, unresolved:** there's no `.gitattributes` and `core.autocrlf` is unset, so on Windows checkouts nearly every tracked file can show as "modified" purely from CRLF/LF churn with zero real content change. Before trusting `git status`/`git diff`, use `git diff --ignore-space-at-eol` (or `--stat` with the same flag). Don't commit a large "everything changed" diff without checking it isn't line-ending noise. Fixing it properly (a `.gitattributes` normalizing to LF plus a one-time renormalization commit) is a real fix worth doing and hasn't been prioritized over phase work.

## What this is

Product name: **Culprit** (decided — see `docs/IMPLEMENTATION_PLAN.md` §3; the earlier "SignalStack" placeholder is gone from product-facing surfaces). The GitHub repository is now also named **Culprit** (Phase 20, `docs/SELF_HOSTED_PLAN.md`, decided 2026-08-08) — it was named `View` (Culprit's original working title) from the project's start through Phase 19, which is why some older commit messages, this working folder's own name, and any bookmark to `github.com/Josh-Heath123/View` predate the rename; GitHub redirects that old URL. Image paths (`ghcr.io/josh-heath123/culprit/*`), `docker-compose.prod.yml`'s `name: culprit`, the `culprit.co.za` domain, and the dashboard UI copy all agree with the repo name now — this is a decided, one-time rename, not something to reconsider or partially redo in a later session.

An incident-correlation copilot for small engineering teams running multiple services without a dedicated SRE/observability function. It ingests logs and metrics from 2-3 services, flags anomalies statistically, correlates them across services in time, and — grounded in the team's own past incident postmortems via RAG — suggests a likely root cause instead of just a wall of unrelated alerts.

Full problem/market/monetization writeup: `docs/SPEC.md`. Don't restate that reasoning here or in code comments — it doesn't change how the code should be written.

Full build plan for the original single-VM MVP (Phases 0–12) — exact tech stack per layer, phase-by-phase implementation order, product personality/voice spec, and the security/performance checklists: `docs/IMPLEMENTATION_PLAN.md`. Read the specific phase section you're working on, not the whole file — each phase is written to stand alone.

Full plan for the self-hosted-product pivot (Phases 13–20, all merged — historical, like `docs/IMPLEMENTATION_PLAN.md` above) — dependencies between phases, schema changes, API surfaces, acceptance criteria, known traps: `docs/SELF_HOSTED_PLAN.md`. The current work is `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35); see the Status section. Same convention throughout: read the phase section you're working on, plus §1's invariants, not the whole file.

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
2. **Storage** — `api/app/db/` (`models.py`, `base.py`) + Alembic migrations in `api/migrations/versions/` (core schema, one migration per service's least-privilege DB role — ingest-gateway, anomaly-detector, correlation-engine, root-cause-writer — plus `api_keys`, root-cause fields, and raw-event compression/retention). TimescaleDB + pgvector, one Postgres instance. What was two roles when this was written is ten now — see the role list under Production deployment below, and `.claude/rules/database.md` for the rule that got it there (add a role, never widen one). A `worker`-side consumer (`worker/app/consumer.py`, run via `just consumer` → `arq app.main.WorkerSettings`) drains the stream into it. `worker/app/db.py`'s Core tables still duplicate `api/app/db/models.py`'s ORM columns by hand (worker/api are separate uv projects, no shared internals for this) — `scripts/check_schema_drift.py` (`just check-schema-drift`, also a CI step) diffs the two and fails the build if they diverge, so drift gets caught immediately instead of silently, the way it did once already (the ORM had `raw_events.id` as `INTEGER` against the real `BIGINT` schema, and four `created_at` columns wrongly non-nullable — both fixed).
3. **Anomaly detection** — `worker/app/anomaly/` (`scorer.py`, `state.py`, `job.py`). Deterministic, not an LLM call — see the rule below. State persists to Redis as plain JSON (`MetricScorer.to_dict()`/`from_dict()`), not pickle — River's `EWVar` has no introspectable state, so scoring uses a second `EWMean` tracking E[x²] instead (verified bit-identical to `EWVar.get()`), which *is* round-trippable.
4. **Correlation** — `worker/app/correlation/` (`graph.py`, `job.py`). Rule/window-based, not LLM-based — see the rule below. Adjacency is read from the DB (`services`/`service_dependencies`, Phase 14) — `shared/culprit_shared/services.py`'s `SERVICE_ADJACENCY` is demo-fixture data only now, imported by `demo-services` but not by `worker`. A second, machine-observed source exists too (Phase 19): the ingest-gateway decodes `CLIENT`-kind trace spans into `(from_service, to_service)` edge counts in `observed_service_edges`, surfaced as suggestions an admin accepts or dismisses in **Settings → Services** — inference only ever proposes, `service_dependencies` is still the one table correlation actually reads, and nothing changes correlation behaviour until a human accepts a suggestion.
5. **RAG / root-cause narrative** — `worker/app/rag/`: `embeddings.py` + `retrieval.py` (pgvector similarity search), `context.py` + `prompts.py` + `sanitize.py` (grounding), `llm.py` dispatching to `providers/anthropic_provider.py` or `providers/gemini_provider.py` based on `LLM_PROVIDER` (`.env.prod` currently sets this to `gemini`, the free-tier default). `seed_postmortems.py` (`just seed-postmortems`) embeds the fixture postmortems — idempotent, needs `VOYAGE_API_KEY`. A real write path exists too (Phase 18): `POST`/`PATCH /postmortems` (a fourth DB role, `postmortem-writer`) enqueues `worker/app/rag/embed_job.py`, event-driven, with `embedding_status` (`pending`/`embedded`/`failed`) surfaced in the UI so a Voyage rate-limit failure shows as a visible, retryable state instead of a silently-never-embedded row.
6. **API / dashboard** — `api/app/incidents/` (`router.py`, `service.py`, `schemas.py`, `transforms.py`, `limiter.py`) serves incident candidates + evidence. `api/app/auth/` is the JWT session layer (originally Phase 9's single hardcoded operator account — **superseded by Phase 16**, see point 9 below: it's a real `users` table with roles now, not `OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH`). `frontend/src/` is React + Vite + TypeScript + Tailwind + shadcn/ui: `components/Dashboard.tsx`, `components/timeline/Timeline.tsx`, `components/incident-detail/` (`IncidentDetailPanel.tsx`, `Evidence.tsx`, `ConfidenceBadge.tsx`), `components/command-palette/CommandPalette.tsx` (cmdk), plus empty/error states per the product-personality voice charter in `docs/IMPLEMENTATION_PLAN.md` §3. `components/auth/LoginScreen.tsx` + `hooks/useAuth.ts` + `lib/auth.ts` (in-memory JWT — deliberately not localStorage, so a refresh means logging in again) wire the dashboard to that auth layer; `lib/api.ts` attaches it as `Authorization: Bearer <token>` on every request and clears it on any 401, bouncing back to the login screen (this was completely missing at first launch — the deployed dashboard couldn't load any data until it was added). `frontend/src/lib/types.ts` re-exports from `src/lib/api-types.generated.ts`, generated from api's live OpenAPI schema (`api/scripts/dump_openapi_schema.py` + `openapi-typescript`, via `just generate-types` — both gitignored, regenerated on every dev/build, not hand-maintained anymore).

Self-observability (Phase 10) — `api/app/observability.py` and `worker/app/observability.py` — instruments both services with the same OTel approach the product recommends to its users, exporting to the local Grafana+Tempo stack (`infra/docker-compose.yml`) in dev, or a configurable OTLP endpoint in prod (empty by default in `.env.prod` — falls back to console export rather than retrying a dead endpoint).

The self-hosted-pivot phases (`docs/SELF_HOSTED_PLAN.md`), each adding a distinct DB role/engine on top of the above rather than replacing it:

7. **Frontend routing (Phase 13)** — `react-router-dom`; `frontend/src/routes/AppRoutes.tsx`, `RequireAuth.tsx`, `NotFound.tsx`. Before this, `App.tsx` was just `token ? <Dashboard /> : <LoginScreen />` and every URL rendered identically. `selectedIncidentId` now lives in the URL, not component state.
8. **Service registry (Phase 14)** — `api/app/registry/` (`service.py`, `keys.py`, `schemas.py`, `config.py`; its `/services` router was removed in Phase 30 and ingest keys are served at `/model/components/{id}/keys`), a `registry-admin` DB role/engine distinct from `api-reader`. Services and their API keys are now rows in `services`/`service_dependencies`/`api_keys`, managed via **Settings → Services** in the dashboard or, since Phase 27, `just apply-model <file.yaml>` (`api/scripts/apply_model.py`, declarative — see `demo-services/culprit.yaml`), not hardcoded in `shared/culprit_shared/services.py` and a literal migration anymore. `worker/app/correlation/graph.py` reads adjacency from the DB now, passed in as a parameter rather than importing the old hardcoded dict.
9. **Multi-user auth (Phase 16)** — replaces Phase 9's single operator account. `api/app/auth/` now has a real `users` table (`repository.py`, `users_router.py`), `admin`/`member` roles (`require_admin` vs `require_auth` in `dependencies.py`), and a new `auth-service` DB role/engine for writes; `api/scripts/create_user.py` (`just create-user <username> --role admin`) creates the first admin. `frontend/src/routes/SettingsUsers.tsx` + `components/auth/ChangePasswordDialog.tsx` are the UI for it. The old `OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH` env vars are now migration-time-only inputs (read once by `api/migrations/versions/fbf4cb16570a_create_users_table.py`'s backfill), not read by application code at all.
10. **Public ingest path + instrumentation guide (Phase 15)** — `ingest-gateway` is now reachable from outside the Docker network (previously only `frontend` was published), so a real third-party service can actually push telemetry in. `docs/INSTRUMENTATION.md` is the copyable guide for doing that against a real service, as opposed to `demo-services/shared/otel.py` which is demo-only.
11. **One-command quickstart + real-VM install guide (Phase 17)** — `scripts/bootstrap_env.py` generates all secrets (including the newer `REGISTRY_ADMIN_DB_PASSWORD`/`AUTH_SERVICE_DB_PASSWORD`) instead of ~10 being hand-generated; `just quickstart` brings up a full working stack + three demo services + an auto-injected fault against `infra/docker-compose.quickstart.yml`, entirely via Docker (no local Python/uv needed, `bootstrap_env.py` runs inside a throwaway container). `docs/INSTALL.md` is the equivalent guide for a real VM (what `docs/IMPLEMENTATION_PLAN.md`'s Production deployment section below used to be the only source for). `just bootstrap-env --domain <domain>` is the prompted, non-quickstart version of the same secret-generation script.
12. **Postmortem write path (Phase 18)** — `api/app/postmortems/` (a fourth DB role/engine, `postmortem-writer`), `worker/app/rag/embed_job.py` (the arq job, event-driven off `POST`/`PATCH /postmortems`, not the seed script's one-off backfill), `frontend/src/routes/PostmortemEditor.tsx`/`PostmortemList.tsx`. Before this, the only postmortems that existed were the eight fixtures `worker/scripts/seed_postmortems.py` loads once — a team could never add its own.
13. **Topology inference from traces (Phase 19)** — `api/app/ingest_gateway/otlp_decode.py`'s `decode_traces_request` (Option A only, attribute-based: reads `CLIENT`-span `peer.service`/`server.address`, never joins parent/child spans) plus a new `POST /v1/traces` endpoint; `worker/app/consumer.py`'s `drain_edges` cron job upserts into `observed_service_edges`; `GET/POST /model/topology/suggestions[/accept|/dismiss]` (logic in `api/app/registry/service.py`; under `/services` until Phase 30). No new DB role — reuses `ingestion-writer`/`api-reader`/`registry-admin`, the one phase in this list that didn't need one. Traces are never stored; only the `(from_service, to_service)` pair survives past decode. `demo-services/order_service/main.py` had to gain its own `CLIENT`-span instrumentation for this to produce anything at all — it previously only propagated trace context without ever creating a span describing an outbound call.


The AI-native pass (`docs/AI_NATIVE_PLAN.md`, Phases 21–24), all merged:

14. **Engineering memory (Phase 21)** — `architecture_decisions` and `ai_change_records` join `postmortems` as sibling tables (`api/app/memory/`, `worker/app/rag/embed_job.py`), retrieval generalised across all three (`worker/app/rag/retrieval.py`'s UNION ALL). No new DB role: `postmortem-writer`'s grants were extended, the one sanctioned role reuse in this repo, because engineering memory is the same trust domain as postmortems. `ai_change_records` rows are written automatically by `.claude/hooks/capture_ai_change.sh`, authenticated with `AGENT_AUTOMATION_TOKEN` rather than a user JWT.
15. **Deterministic invariant checks (Phase 22)** — `scripts/check_migration_symmetry.py` (a migration's `upgrade()`/`downgrade()` must be structurally symmetric) and `scripts/check_coupled_files.py` (`scripts/coupled_files.yaml` declares files that must change together). Both run at file-write time via `.claude/hooks/check_invariants.sh` *and* in CI, because a hook that fails to fire is not a gate.
16. **The flywheel (Phase 23)** — `worker/app/memory/link_job.py` links an incident to a recent AI change record when one touched a related service. Rule-based, no LLM: a change record links only if it was committed at or before the incident's `opened_at` and no more than `AI_CHANGE_LOOKBACK` (30 minutes) before it, and the service/file match is a plain substring test. See `docs/LIMITS.md` — this heuristic went undocumented for months and is exactly the kind of threshold that must not.
17. **MCP server (Phase 24)** — `mcp_server/`, read-only tools over Phases 21–23's data for a coding agent to call *before* making a change. Its own uv project, its own `mcp-reader` DB role, its own image; deliberately not wired into `docker-compose.prod.yml` — a team runs it themselves.

The diagnostic-engine rewrite (`docs/DIAGNOSTIC_PLAN.md`, Phases 26–35) has begun:

18. **The three-plane core model (Phase 26)** — `shared/culprit_model/` (`planes.py`, `facts.py`, `subjects.py`, `canonical.py`), shipped inside the existing `culprit-shared` distribution so both `api/` and `worker/` already have it. `subjects.build()` is the **only** sanctioned way to construct a subject URI (`http:orders-svc/POST /orders`) — hand-formatting one anywhere else is a lint failure (`scripts/tests/test_subject_construction.py`). The `captures`/`intent_facts`/`configured_facts`/`readings`/`divergences` tables exist and are **empty by design** until Phase 27; nothing reads or writes them, and no role has been granted anything on them. Phase 26.1 then made `configured_facts` structurally unable to hold an ungranted config value: `value` is nullable and NULL by default, `value_shape` carries type/format instead, and a CHECK (`ck_configured_facts_value_requires_grant`) means a literal value can exist only in a row naming an explicit `grant_ref`. That guarantee covers the `value` column only — `value_shape` is still free-form JSONB (`docs/LIMITS.md`).

19. **The system model (Phase 27)** — `services`/`service_dependencies` became `components`/`connections`, plus an empty `contracts` table. `services` was **renamed**, not copied, so every FK (`api_keys.service_id`, which keeps its old name) and every GRANT followed it intact. `connections` had to be a new table: its identity is `(from, to, kind)`, because two components may be connected in more than one way, where `service_dependencies`' primary key was the untyped pair. `shared/culprit_model/graph.py` is the pure in-memory graph — components, typed connections, reachability, and `upstream_connections()` for request-path derivation (plain BFS, no `networkx`: that is a `worker`-only dependency and `culprit_model` is installed into `api` too). `api/app/model/` is the new HTTP surface (`/model/components`, `/model/connections`, `/model/graph?symptom=`, `/model/apply`, `/model/export`); The `/services` alias it kept for one release was removed in Phase 30. `culprit.yaml` (`api/app/model/manifest.py`, applied with `just apply-model`) is the declarative source — it names config keys and never their values, and the loader refuses anything credential-shaped. `demo-services/culprit.yaml` replaced `infra/demo-services.yaml` and the last hardcoded topology fixture. Two standing gates landed with it: `scripts/check_migration_round_trip.py` (invariant 8 — every migration round-trips against a real database with rows present, its own CI job) and `scripts/check_scan_coverage.py` (invariant 9 — every repo-wide check's declared roots actually cover the repository; it immediately found `examples/` covered by nothing).

20. **The CLI, the extractor protocol and intent extraction (Phase 28)** — the first non-Python code in the repository. `cli/` is a Go module producing one static binary (`just cli-build`), which orchestrates extraction and **never parses application code itself** (D3). It reads built-in artefacts (OpenAPI, `.env.example`, compose, Alembic version chains, dependency manifests) and shells out to *extractor plugins* over a JSON-on-stdin/stdout protocol — `docs/EXTRACTOR_PROTOCOL.md` is the contract, `extractors/python/` and `extractors/node/` are the two reference implementations, and both install into the *target* project's virtualenv because introspecting a FastAPI app means importing it. `culprit intent` prints an inventory and stops: it compares nothing and uploads nothing (that phase's field 17). `shared/culprit_model/shape.py` is the Q5 remediation — a closed four-field `ValueShape` a config literal structurally cannot fit in — with `api/migrations/versions/d1f4a9c73b60_*.py` narrowing `configured_facts.value_shape` to match and adding the `fact-writer` role behind `POST /facts/captures` (an eleventh role; a project token, not a user JWT). The root `culprit.yaml` describes Culprit to itself and is what `just intent` extracts. There are now **three** implementations of subject construction, one per language, held together by `shared/tests/*conformance.json` — see `.claude/rules/model.md`.

21. **The divergence engine (Phase 29)** — `culprit check`, the first shippable product: it finds real faults in a real repository, in CI, with no runtime access, no telemetry, no baseline and no account. `cli/internal/diverge/` is the generic comparator (D7) — it groups facts by `(subject, predicate)`, canonicalises values and emits a `Divergence`, and **knows nothing about HTTP, SQL or auth**; a new fault class is a new extractor, never an engine change. Two rules: *conflict* (two sources, same claim, different answers) and *absence* (one source names a subject that a source which **enumerates** — rank 80 or above, and not a hand-written assertion — does not list). `cli/internal/severity/` computes severity from `culprit.yaml`'s connection graph, deterministically; `cli/internal/report/` renders text, JSON, **SARIF** (GitHub pull-request annotations, which is most of the adoption story) and JUnit; `cli/internal/check/` is the pipeline as a function so the eval suite can drive it. `culprit.yaml` gains `invariants:` (rank-100 developer assertions, which become ordinary INTENT facts so the same generic comparator handles them), `suppress:` and `severity_overrides:`, both requiring a `reason`. Exit codes are a contract: `0` clean, `1` findings at or above `--fail-on`, `2` execution error. `POST /divergences/captures` (`api/app/divergences/`) stores history, upserting on a shared identity computed identically in Go and Python; it reuses `fact-writer` — the **second** sanctioned role reuse in this repository, reasoned in `api/app/divergences/config.py`. `cli/testdata/faults/` is the eval suite, asserting the exact divergence set per fixture with a false-positive baseline of zero, and `cli/testdata/demo/` is a three-component repository that demonstrates all four detection criteria end to end through the real extractors. **The check pipeline links no networking package at all** — a test asserts it against `go list -deps`, which is field 17's "no LLM anywhere near this path" made structural.

22. **Environment capture and cross-environment diff (Phase 30)** — the CONFIGURED plane. `culprit env capture <env>` reads one environment declared under `culprit.yaml`'s `environments:` (`cli/internal/extract/environments.go`) through an adapter — `compose` and `kubernetes` shell out to `docker`/`kubectl` rather than linking their SDKs (a plan correction; the binary linked no `net/http` until Phase 31's HTTP probes), `process` reads its own environment, `exec` runs an allowlisted command — and writes a sealed envelope (`cli/internal/capture/envelope.go`: base64 payload, SHA-256, optional Ed25519, DSSE-style). Every check asks `cli/internal/capability/` first; what is not granted is a *refusal* recorded in the bundle, never an omission. Config values become `ValueShape`s (which gained a closed-enum `scheme`, Q7) unless a key is on the `config.read.values` allowlist; every CONFIGURED fact names the grant that permitted it in `grant_ref`, which `POST /captures` checks against the capture's own grant list. `culprit diff <a> <b>` (`cli/internal/check/diff.go`, taking captures as arguments so `internal/check` still links no networking) runs the Phase 29 comparator across scopes (`cli/internal/diverge/scope.go`): `intent_vs_configured` and `env_vs_env`, INTENT as the reference wherever it has an answer, absence judged only INTENT → environment and never against an enumeration the capture marked incomplete. Live schema is read from `pg_catalog` (any role sees every table). `api/app/model/captures*.py` is `POST /captures`, `GET /captures/{id}`, `GET /captures/diff` under a new `capture-writer` role; `api-reader` reads, through one serialiser that never renders a config value. `docs/PERMISSIONS.md` documents every grant. Evals: `cli/testdata/envdiff/`; end to end against real Compose projects (`just cli-test-docker`) and a kind cluster (`just cli-test-kind`), both also CI jobs.

23. **Probes (Phase 31)** — the OBSERVED plane, and the first active reading. `cli/internal/probe/` is the runtime: a manifest loader/validator (`effect: mutate` is refused by the type itself and again at catalogue registration), a runner that asks `capability.Ledger` **before** anything is dialled, applies the manifest timeout, bounds concurrency and stamps the run-describing fields (`taken_at`, `agent_id`, `grants_used`) so a probe cannot claim an authority it was not given. Thirteen core probes: `net.dns_resolve`/`tcp_connect`/`tls_validity`, `http.reachable`/`route_conformance`/`schema_conformance`, `auth.token_shape`/`propagation`, `db.connect`/`schema_conformance`, `config.present`, `dep.version`, `edge.impedance`. Four verdicts, with `inconclusive` and `refused` first-class — a refused TCP connection is `fail` but a timeout is `inconclusive`, because a dropped packet does not prove a port is closed. `Reading` and `ProbeManifest` are in `shared/culprit_model/readings.py` and `cli/internal/model/reading.go`, held together by `shared/tests/reading_conformance.json`. **This phase changed the binary's network posture**: `probe.http.*` needs `net.http.outbound`, so the blanket "the binary links no `net/http`" assertion was replaced by a per-package one, and Phase 31.1 made it an allowlist (`TestTheNetworkBoundaryIsAnAllowlist`): only `internal/probe` may link `net/http`, only `probe` and `capture` may link `net`/`crypto/tls`, and every other package `go list ./internal/...` finds may link none — so a new package is covered the day it exists. `internal/probe`'s client cannot express a write. `worker/app/anomaly/job.py` additionally emits impedance readings keyed by a connection subject (`scorer.py`/`state.py` untouched, D5); the attribution rule and its limits are in `docs/LIMITS.md`. A thirteenth role, `probe-writer` (INSERT on `readings`, not even SELECT), backs `POST /readings` — and the same migration **widens `anomaly-detector` with SELECT on `connections`**, a read grant on a sibling of a table it already reads (Phase 27's rename carried its `services` grant to `components`), needed to resolve which edge a metric belongs to; argued in the migration, and the role's write surface is unchanged. Note the role bounds a leaked *database* credential, not a leaked *API* one: `POST /readings` shares `CULPRIT_PROJECT_TOKEN` with the facts and divergences endpoints. `GET /probes` serves the catalogue and `POST /probes/{id}/run` honestly answers 503, because probes execute where the environment is and no agent transport exists until Phase 33. `docs/PROBES.md` documents every probe, and why the passive `env capture` network checks and the active `probe.net.*` ones both exist.

## Tech stack (decided, don't re-litigate per session)

- **Backend:** Python, FastAPI (`api/`), managed with `uv`
- **Worker / job runner:** Python, `arq` (Redis-backed job queue) — drives the stream-drain consumer and the anomaly/correlation/RAG jobs (`worker/`)
- **Shared contracts:** `shared/culprit_shared/` — a real installable package, path-dependency in both `api/` and `worker/`'s `pyproject.toml`. `raw_event.py` (`RawEventIn`) and `service_edge.py` (`ServiceEdgeObservation`, Phase 19) are the wire-shape contracts api/worker validate against and reference the exact same definitions instead of hand-duplicating them. `services.py` used to be this too for adjacency/topology, but is demo-fixture data only since Phase 14 (see Architecture point 4) — `demo-services` still imports it, `worker` doesn't.
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

`.claude/rules/determinism.md` is the full, current statement of this boundary — including the packages the diagnostic-engine rewrite adds (fact extraction, comparison, probes, fault isolation, verification, subject construction, the MCP tools, the check scripts) and the narrower role the single LLM call is allowed to play: rendering an already-settled fault tree into prose and ranking hypotheses within an already-computed set. It may not create a fact, a divergence, a reading, a verdict or a hypothesis.

This isn't just a stated intention — CI enforces it structurally, two ways:

- `worker`'s `lint-imports` (import-linter, `just lint-imports`, and its own step in the `typecheck` CI job) fails the build if `worker/app/anomaly/`, `worker/app/correlation/` or `worker/app/memory/` imports from `worker/app/rag/` (or vice versa for the first pair), and if `culprit_model` reaches an LLM client at all.
- `scripts/check_no_llm_imports.py` (`just check-no-llm-imports`, also a CI step) walks source text across every project for the same violation, catching packages that have no venv for import-linter to build a graph from.

If a change needs to cross that boundary, that's the signal the rule above is about to be violated — not a contract to widen, a forbidden-module list to shorten, or an ignore to add.

## Production deployment (Phase 11) — done, live at culprit.co.za

Target: a single self-hosted Oracle Cloud Always Free VM, not a managed PaaS (`docs/IMPLEMENTATION_PLAN.md` §7 corrected this from an earlier Fly.io plan after Fly.io dropped its free tier). Current VM: `culprit-vm`, Ubuntu 22.04, public IP `92.4.156.135`, domain `culprit.co.za`. VM is on a 2 OCPU / 11 GB **x86_64** flex shape, not the commonly-cited Always Free options (`E2.1.Micro` at 1 OCPU/1GB, or the ARM `A1.Flex` up to 4 OCPU/24GB) — confirmed still within Always Free, but don't assume a fresh Oracle account will land on either textbook shape. x86_64 is convenient here: GitHub Actions' `ubuntu-latest` runners build `amd64` images by default, no cross-platform/buildx step needed.

Pipeline (`.github/workflows/ci-cd.yml`): lint → typecheck (includes the `lint-imports` contract above) → pytest → build + Trivy scan (CRITICAL/HIGH, blocking) → on `main` only: push `api`/`worker`/`frontend` images to `ghcr.io/josh-heath123/culprit/*` → SCP `docker-compose.prod.yml` + `deploy.sh` to the VM → SSH in and run `deploy.sh`. Pushing a `vX.Y.Z` git tag (Phase 20) runs the same pipeline and additionally pushes a `:vX.Y.Z` image tag, but never deploys — only a `main` push does that; see `docs/UPGRADING.md` for why a third party should pin to a version tag rather than track `:latest`. `infra/deploy.sh` order is deliberate: pull images → `alembic upgrade head` → restart containers → health check (now a retry loop, not a single flat `sleep 5` + curl — see below). `infra/.env.prod` is created once, by hand, on the VM from `.env.prod.example` — never from GitHub Actions secrets, never baked into an image, never committed; every literal `$` in a value (matters for the argon2 `OPERATOR_PASSWORD_HASH`) must be escaped as `$$`.

**Real issues hit getting the first deploy green — don't reintroduce these if touching CI/Docker again:**
- `aquasecurity/trivy-action` retired all un-prefixed version tags (e.g. `0.24.0`) after a supply-chain-attack response; only `v`-prefixed tags exist now (pinned to `v0.36.0`).
- `api/` and `worker/` both depend on `shared/` (the `culprit-shared` path dependency). Their Docker builds use the **repo root** as context (`context: .`, `file: api/Dockerfile` in `ci-cd.yml`'s build matrix), not their own subdirectory — otherwise `shared/` is invisible to the build and `uv sync` fails with "Distribution not found." `frontend/` has no such dependency and keeps its own directory as context. There's a root `.dockerignore` for this reason; `api/.dockerignore` and `worker/.dockerignore` no longer exist (dead once their directory stopped being the build context).
- `frontend/src/lib/api-types.generated.ts` is gitignored and generated from `api`'s live OpenAPI schema — the frontend Docker build can't reach `api`'s Python, so CI generates it on the runner (`api/scripts/dump_openapi_schema.py` + `npm run generate-types`) *before* the Docker build step, for the frontend matrix entry only. That generation step imports `app.main`, which needs the same dummy `JWT_SECRET_KEY`/`OPERATOR_USERNAME`/`OPERATOR_PASSWORD_HASH` env vars the `pytest (api)` job already sets, or it fails on import.
- `ghcr.io` images pushed via `GITHUB_TOKEN` default to **private** — `deploy.sh`'s `docker compose pull` on the VM needs either the packages flipped to public (GitHub → Packages → visibility), or a one-time `docker login ghcr.io` on the VM using a **classic** PAT with `read:packages` scope (fine-grained PATs don't support Packages access yet, confirmed against GitHub's own docs as of this writing). Still true as of Phase 20 (2026-08-08) — flipping this to public is that phase's own step 2, and it's still outstanding; see the Status section above for why a session can't just do it.
- Caddy's first-ever Let's Encrypt cert issuance for a fresh domain took ~10s in practice — longer than the original flat `sleep 5` + 10s curl timeout budgeted for. `deploy.sh`'s health check now polls (12 attempts, 5s apart) instead of checking once.

**Thirteen Postgres roles exist now**, not the four this section was written against: `ingestion-writer`, `api-reader`, `ingest-gateway`, `anomaly-detector`, `correlation-engine`, `root-cause-writer`, plus `registry-admin` (14), `auth-service` (16), `postmortem-writer` (18, extended in 21 rather than joined by a new role), `mcp-reader` (24) `fact-writer` (28 — INSERT on `captures`/`intent_facts`, SELECT on `captures`; extended to `divergences` in 29), `capture-writer` (30 — INSERT on `captures`/`configured_facts`, SELECT on `captures`, nothing else) and `probe-writer` (31 — INSERT on `readings` and nothing else, not even SELECT on it; the api and the worker both connect as it). Phases 19 and 26 deliberately added none. The rule is in `.claude/rules/database.md`: **if a component needs a write the current roles cannot do, add a role — do not widen an existing one.** `scripts/bootstrap_env.py` generates every one of these passwords; the manual "~10 hand-generated secrets" process this section used to be the only record of is superseded by `docs/INSTALL.md` (Phase 17) — follow that doc for a real install, not a reconstruction from memory of what this section says.

## Toward a self-hosted, downloadable product — all seven original gaps closed (historical)

This used to be a speculative backlog section listing 7 gaps blocking a third party from downloading this and running it against their own services. That plan (`docs/SELF_HOSTED_PLAN.md`, Phases 13–20) has now closed every one of them:

1. ~~Services are hardcoded, not configured.~~ **Done (Phase 14)** — service registry, see Architecture point 8 above.
2. ~~Correlation's adjacency is hand-specified, not inferred.~~ **Done (Phase 19)** — trace-based topology inference, see Architecture point 13 above. (Hand-declared adjacency is still fully supported and still the default — inference only adds suggestions on top of it.)
3. ~~RAG has no postmortem write path.~~ **Done (Phase 18)** — see Architecture point 12 above.
4. ~~Auth is one hardcoded operator account.~~ **Done (Phase 16)** — see Architecture point 9 above.
5. ~~Setup friction is real.~~ **Done (Phase 17)** — `just quickstart` + `scripts/bootstrap_env.py` + `docs/INSTALL.md`, see Architecture point 11 above.
6. ~~`ingest-gateway` isn't exposed to the internet.~~ **Done (Phase 15)** — see Architecture point 10 above.
7. ~~No generic instrumentation guide.~~ **Done (Phase 15)** — `docs/INSTRUMENTATION.md`.

Phase 20's release-engineering pass is done too: versioned image tags (pushing a `vX.Y.Z` git tag publishes one), a license (MIT, see `LICENSE`), `docs/UPGRADING.md`, `scripts/backup.sh`, `docs/LIMITS.md`, and the repo/product name reconciliation. The one piece still outstanding is making the `ghcr.io` packages public (see the Known Traps list under Production deployment above) — that needs a human in the GitHub UI, not something a session can finish on its own.

This whole section is history now. It describes gaps in the *incident-correlation* product; the current work (`docs/DIAGNOSTIC_PLAN.md`) is a different product built on the same substrate. Keep it for the reasoning, don't treat it as a backlog.

## Setup & commands — verified against the actual `justfile`

Everything routes through `just` (recipes wire up `--env-file infra/.env` and working directories for you — don't run the raw `uvicorn`/`pytest`/`docker compose` commands standalone unless you're intentionally bypassing that).

```bash
# local infra: Postgres+TimescaleDB+pgvector, Redis, Grafana+Tempo
just up / just down

# api with autoreload (brings up infra first)
just dev

# apply migrations (brings up infra first)
just migrate

# full test suite — api (which also runs scripts/tests and shared/tests),
# worker, and mcp_server
just test

# single test — don't run the full suite for a one-line change
cd api && uv run pytest tests/path/to/test_file.py::test_name -v
cd worker && uv run pytest tests/path/to/test_file.py::test_name -v

# lint / typecheck / import-boundary contract / schema-drift check
just lint
just typecheck
just lint-imports
just check-schema-drift
just check-no-llm-imports   # Phase 26: no LLM client in a deterministic package
just check-invariants       # Phase 22: coupled files + migration symmetry
just check-scan-coverage    # Phase 27: every repo-wide check's roots cover the repo
just check-migration-round-trip  # Phase 27: upgrade -> seed -> downgrade -> upgrade (needs Docker)

# the whole gate set at once, honestly reported: /verify (.claude/skills/verify)

# the Go CLI and the two extractor plugins (Phase 28). Needs Go on PATH.
just cli-build        # -> cli/bin/culprit, one static binary (CGO_ENABLED=0)
just cli-test
just cli-lint         # gofmt + go vet
just cli-release      # cross-compile every published target into cli/dist/
just cli-golden-update  # rewrite cli/testdata/fixtures/golden/ -- read the diff
just extractors-test  # extractors/python (pytest) + extractors/node (node --test)

# `culprit intent` over this repository itself (the root culprit.yaml),
# with the placeholder env api/app/*/config.py needs at import time.
just intent                        # human-readable inventory
just intent --format json          # the capture bundle
SOURCE_DATE_EPOCH=0 just intent --format json   # byte-reproducible

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

# system model (Phase 27) — declarative culprit.yaml, e.g. demo-services/culprit.yaml
just apply-model <file.yaml>               # add --prune to disable components not in the file
just apply-model --export                  # print the current model as a culprit.yaml

# multi-user auth (Phase 16) — the only way to create the first admin account
just create-user <username> --role admin

# one-command local quickstart (Phase 17) — full stack + demo services + an
# auto-injected fault via docker-compose.quickstart.yml, Docker-only, no uv needed
just quickstart
just quickstart-down

# secret generation for a real (non-quickstart) install — docs/INSTALL.md
just bootstrap-env --domain <domain>

# back up the running deployment's Postgres DB before upgrading (Phase 20)
scripts/backup.sh   # see docs/UPGRADING.md
```

To actually see the pipeline detect something end-to-end (locally — `demo-services` was deliberately never added to `docker-compose.prod.yml`, see "Toward a self-hosted product" point 6 for why production has no telemetry source): bring up infra + migrate, run `ingest-gateway` + `consumer` + all three `demo-*` services + `demo-load` each in their own terminal, let baseline traffic run for a minute or two so the anomaly scorer has history to compare against, then `just demo-fault latency inventory-service --delay-ms 800 --duration-s 30` (or the `errors` variant). An anomaly → incident → root-cause narrative should appear on the dashboard within the next few 5-second worker cron cycles.

## Token/context efficiency notes for future sessions

- **Don't dump raw ingested logs/metrics into context to debug something.** Query or aggregate first (e.g. `SELECT` a specific window, not a table scan) — this data is high-volume by design.
- **Keep the anomaly-detection module and the RAG/LLM module in separate files with no shared internals.** `lint-imports` enforces this in CI (see above) — a session working on correlation logic shouldn't need to load the LLM prompt-construction code, and vice versa.
- **Don't re-run the full test suite to check a one-line change in an isolated module.** Use the single-test command above.
- **Don't re-read this whole file's "Architecture" section into working memory every session if only touching one layer** — jump to the relevant numbered step.
- **Check `docs/HANDOFF.md` §1, then `git status` and the current branch, before trusting what "the codebase" means in a session.** Every phase from 18 onward has spent real time as work-in-progress on an unpushed local branch before merging; `HANDOFF.md` §1 names the current phase and its branch, which is why it now exists instead of this file trying to track it. Windows checkouts can separately show large `git diff` output that is pure line-ending noise (see the repo-hygiene note above) rather than real change — don't assume a big diff is real without checking `--ignore-space-at-eol` first.
