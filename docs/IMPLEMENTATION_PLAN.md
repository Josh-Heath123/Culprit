# Culprit — Implementation Plan

*(Written under the working title "SignalStack" — see `CLAUDE.md` for
when and why the product was renamed to Culprit. Left as "Implementation
Plan" rather than renamed throughout, since every phase reference below
predates that decision and rewriting them would edit history for no
benefit.)*

Companion to `CLAUDE.md` and `docs/SPEC.md`. Those files say *what* this is and *why*; this file says *exactly what to build, in what order, with what technology, and why each choice earns its place*. No dates or time estimates — sequencing here is dependency order, not calendar order. Skip ahead to whatever phase you're actually touching; you don't need the whole document loaded to work on one layer.

Every technology below is chosen against four criteria, in this priority order for a solo-built demo: **it has to actually work under real load and real failure modes (performance/correctness), it has to not be embarrassing in a security review (security), it has to not eat weeks of plumbing before you see results (implementation ease), and it has to make the product feel deliberately designed rather than assembled from tutorials (personality/viability).** Where a "simple" option and a "correct" option conflict, this plan picks correct — a demo that silently produces wrong anomaly scores is worse than no demo.

---

## 1. Exact tech stack

| Layer | Technology | Why this, specifically |
|---|---|---|
| Language & tooling | Python 3.12+, **uv** | uv now runs dependency resolution/install 10-100x faster than pip and has effectively replaced pip/Poetry/pyenv/virtualenv as the default in CI — one binary, one lockfile, no ecosystem juggling. Astral (uv's maker) was acquired by OpenAI in early 2026, which only accelerated its adoption as the default. |
| Lint & format | **Ruff** | One tool replaces flake8 + black + isort. Fast enough to run on every save without thinking about it. |
| Static typing | **Pyright** + Pydantic v2 everywhere | Pydantic v2 models double as runtime validation *and* static types — you get both for one definition instead of maintaining dataclasses and schemas separately. |
| Backend framework | **FastAPI**, async throughout | Already the project's locked-in choice; async matters here specifically because ingestion, DB writes, and LLM calls all overlap in time and you don't want a sync framework serializing them. |
| ORM & migrations | **SQLAlchemy 2.0 (async)** + **Alembic** | Async SQLAlchemy avoids blocking the event loop on every query; Alembic gives you reviewable, reversible schema changes instead of hand-run SQL. |
| Primary datastore | **PostgreSQL 16 + TimescaleDB + pgvector**, hosted on **Timescale Cloud** | One managed instance does hypertables (metrics/logs), continuous aggregates (rollups), and vector similarity search (RAG) — confirmed as a supported combination on Timescale Cloud, not a workaround. This is the direct implementation of the "one database, two roles" decision already locked in `CLAUDE.md`; a managed host means you're not also debugging Postgres ops on top of everything else. |
| Ingestion buffer | **Redis 7 Streams** | Consumer groups give you at-least-once delivery and backpressure handling without Kafka's operational weight — appropriate for a 2-3 service demo, explicitly not over-engineered per the scope rules already set. |
| Background jobs | **arq** | Async-native task queue built on Redis, from the same ecosystem as Pydantic/FastAPI. Runs the stream-drain consumer, the scheduled anomaly-scoring job, and RAG+LLM calls off the request path. Chosen over Celery deliberately — Celery's async support is bolted on and adds real complexity for zero benefit in an asyncio-first codebase. |
| Anomaly detection | **River** (streaming/online ML library), numpy fallback | River gives you production-grade rolling z-score/EWMA implementations designed for streaming data, instead of hand-rolled loops that silently mishandle edge cases (cold start, NaNs, window resets). This is the single highest-leverage "not vibe coded" choice in the stack — it's the difference between "I wrote a for-loop that averages numbers" and "I used the right tool for online statistics." |
| Correlation | Pure Python rule engine + **networkx** | Deterministic, unit-testable grouping logic (per `CLAUDE.md`'s AI-boundary rule). networkx represents anomalies as nodes and same-time-window co-occurrence as edges — incident candidates fall out as connected components, which is a real graph algorithm doing real work, not decoration. |
| Embeddings | **Voyage AI** (`voyage-4` family, not `voyage-3.x`) | Anthropic's recommended embedding partner; pairs naturally with Claude for the generation step and avoids standing up a second unrelated AI vendor relationship. Specifically the `voyage-4` generation, not `voyage-3.x` — Voyage's 200M free-token allocation only applies to `voyage-4`+ models, and a demo-scale postmortem corpus will likely never leave that free tier. See Section 7. |
| Vector search | **pgvector** cosine similarity, same Postgres instance | No separate vector DB — already decided, and the embedding volume here (past postmortems, not internet-scale) doesn't come close to needing one. |
| Root-cause generation | **Anthropic Claude API**, server-side only, structured tool-use output | Called only after RAG retrieval, per the deterministic/LLM boundary in `CLAUDE.md`. Structured output (not free-text) means the API response is a parseable object the frontend can render deterministically, not a blob of prose you regex out of. |
| Frontend | **React 18 + TypeScript + Vite** | Vite's dev server is fast enough that the frontend loop doesn't fight you; TypeScript matters more here than in a typical CRUD app because the incident/anomaly data shapes are non-trivial and you want the compiler catching shape mismatches, not the browser console. |
| Data fetching | **TanStack Query** | Handles caching, retries, and background refetch for you — the dashboard is going to poll for incident updates, and hand-rolled polling logic is exactly the kind of plumbing that eats a week for no payoff. |
| Styling & components | **Tailwind CSS + shadcn/ui** | shadcn/ui ships components you own and edit (not a black-box npm dependency), which is the difference between a dashboard that looks like every other admin-template SaaS and one with an actual visual identity — see Section 3. |
| Timeline visualization | **visx** (or raw D3 if you want more control) | Purpose-built, custom-rendered — this is the signature visual of the product (see Section 3) and shouldn't be a generic chart-library widget. |
| Command palette | **cmdk** | The same primitive Linear and Vercel's own tools use for their command-K interfaces. Cheap to add, disproportionately signals "built by someone who's used good tools," which matters for personality. |
| AuthN | JWT sessions via **pyjwt**, **argon2-cffi** for password hashing | argon2 is the current recommended default over bcrypt for new projects — no reason to reach for the older algorithm. |
| AuthZ | Scoped API keys, least-privilege DB roles | The ingestion gateway gets a Postgres role that can only INSERT into raw tables; the dashboard API gets a role that can only SELECT. A compromised ingestion endpoint shouldn't be able to read or alter anything it doesn't need to touch. |
| Rate limiting | **slowapi** | Specifically guards the endpoint that triggers an LLM call — that's the one request type with real per-call cost and real abuse potential. |
| Dependency/image scanning | **pip-audit** (or GitHub Dependabot) + **Trivy** | Dependency CVEs and container image CVEs are two different attack surfaces; scan both, not just one. |
| Structured logging | **structlog** | JSON-structured logs from day one — grepping unstructured print-style logs across an ingestion pipeline is exactly the kind of self-inflicted pain this avoids. |
| Self-observability | OpenTelemetry SDK instrumenting SignalStack's own services, **prometheus-fastapi-instrumentator** for request metrics | An incident-correlation tool that isn't instrumented itself is a bad look and a missed interview talking point — "I dogfooded the exact telemetry approach the product recommends" is a real thing to say in an interview. |
| Testing | **pytest** + **pytest-asyncio**, **testcontainers-python**, **Hypothesis** | testcontainers spins up real Postgres/Timescale/Redis for integration tests — no mocking the database, which is exactly the kind of thing that lets a broken migration or a bad query pass a green test suite. Hypothesis property-tests the anomaly-detection math specifically (e.g., "a z-score is never NaN," "a wider window never produces a stricter threshold") because statistical code has edge cases that example-based tests don't reliably hit. |
| CI/CD | **GitHub Actions**: lint → type-check → test → build → deploy | Standard, but the ordering matters — fail fast on lint/types before burning CI minutes on integration tests. |
| Containers | Multi-stage Dockerfiles (uv-based builder stage, slim runtime stage) | Keeps runtime images small and free of build tooling, which is both a performance win (image pull time) and a security win (smaller attack surface). |
| Deployment | **Timescale Cloud free tier** for the database; API + worker + frontend either self-hosted via Docker Compose on a free-tier VM, or split across Render's free static-site tier plus a low-cost Starter web service | Fly.io (the original choice here) dropped its free tier in 2024 — a minimal always-on app there now runs ~$2/month per service, which multiplies across API+worker+frontend. See Section 7 for the actual cost breakdown and the free-vs-cheap tradeoff. |

---

## 2. Build order

Each phase names what gets built and folds in the performance/security/DX call-outs specific to that phase, rather than treating those as a separate pass at the end.

### Phase 0 — Repo skeleton & local environment
Set up the monorepo layout (`api/`, `worker/`, `frontend/`, `infra/`), `uv` project files, Ruff/Pyright config, and a single `docker-compose.yml` that brings up Postgres+TimescaleDB+pgvector, Redis, and a Grafana+Tempo stack for self-observability with one command. Add a `justfile` (or `Makefile`) wrapping the common commands — `just dev`, `just test`, `just migrate` — so no one, including future-you, has to remember flag combinations.
*Why this order:* every later phase assumes a working local environment exists; building it last means every phase before it was developed against guesswork.

### Phase 1 — Data model & storage layer
Define the core schema: raw metrics/log events (hypertable), anomalies, incident candidates, postmortems (with pgvector embedding column). Write the Alembic migration from the start — don't hand-edit schema and backfill migrations later. Set TimescaleDB compression and retention policies on the raw-event hypertable now, even before there's real volume — retrofitting compression policy onto a table that's already grown large is a self-inflicted performance problem to avoid.
*Security:* create the least-privilege DB roles (ingestion-writer, api-reader) at this stage, not as an afterthought — it's much cheaper to design against them from the first query than to retrofit permission boundaries later.

### Phase 2 — Demo services & fault injector
Before building ingestion, build the thing that generates data worth ingesting: 2-3 small demo services (per the hardcoded-services scope rule) instrumented with the OpenTelemetry SDK, plus a fault-injection script that deliberately trips latency spikes, error bursts, or cascading failures across them on demand. Without this, every later phase is developed against silence — you can't tell if anomaly detection works if nothing anomalous ever happens. This is also what makes the eventual demo *look* real instead of staged with fabricated screenshots.

### Phase 3 — Ingestion pipeline
Build the `ingest-gateway` FastAPI service: receives OTLP/HTTP payloads from the demo services, validates and normalizes via Pydantic models, and `XADD`s into the appropriate Redis Stream. Build the arq-based consumer that drains the stream into TimescaleDB using consumer groups (so a crashed consumer doesn't lose data, and a slow consumer doesn't block ingestion).
*Performance:* batch writes into TimescaleDB rather than one `INSERT` per event — this is the pipeline's actual throughput bottleneck if done naively.
*Security:* the ingest-gateway authenticates the demo services via scoped API keys, not an open endpoint — even in a demo, model this like a real multi-tenant boundary.

*Superseded (Phase 14, `docs/SELF_HOSTED_PLAN.md`):* this originally meant three fixed, manually-provisioned keys (one per demo service, hashed into `api_keys` by a migration). A service is a row in a `services` table now, created through an authenticated admin API with its own key issued at creation time — onboarding a new service no longer means writing a migration. The three demo services still exist and still authenticate the same way; they're just no longer the only way a service can exist.

### Phase 4 — Anomaly detection engine
Implement rolling z-score/EWMA scoring per service/metric using River, running as a scheduled arq job. Keep this module's internals completely separate from the RAG/LLM module (per `CLAUDE.md`) — no shared imports, no shared state. Property-test the scoring math with Hypothesis before wiring it to real data, so you're not debugging statistics and plumbing at the same time.

### Phase 5 — Correlation engine
Group anomalies within a configurable time window into incident candidates using the networkx-based connected-components approach. This stays a deterministic rule engine, not an LLM call — the AI boundary from `CLAUDE.md` is load-bearing here, not a style preference: a wrong correlation silently discards real signal, and a hallucinated correlation invents an incident that isn't there.

### Phase 6 — RAG + root-cause narrative
Embed past postmortems with Voyage AI into the pgvector column. On a new incident candidate, retrieve the most similar past postmortems, then call Claude with a strict system prompt (see Section 3's voice charter) and structured tool-use output so the response is a typed object: hypothesis, confidence level, cited evidence, not a paragraph you parse with regex.
*Security:* treat retrieved postmortem text and raw log content as untrusted input to the prompt — sanitize/truncate before it reaches the LLM, and never let ingested log content itself trigger tool calls. Prompt injection via log lines an attacker controls is a real, not theoretical, risk for a tool that ingests arbitrary service output.

*Superseded (Phase 18, `docs/SELF_HOSTED_PLAN.md`):* this originally meant the corpus was eight fixture postmortems loaded once by `seed_postmortems.py`, with no way for a real team to add its own. A team can now write a postmortem — from scratch or attached to a real incident — through `/postmortems` in the dashboard, and it becomes retrievable context for future incidents once embedded. The fixture seeding script still exists and still runs the same way; it's just no longer the only way the corpus grows.

### Phase 7 — API layer
Expose incident candidates, their correlated evidence, and root-cause suggestions via FastAPI, with pagination on every list endpoint (the dashboard should never be able to accidentally request "all events ever"). Rate-limit the endpoints that trigger new LLM calls specifically — that's where a bug or an abusive client turns into a real cost, not just a slow response.

### Phase 8 — Frontend / dashboard
Build the incident timeline (visx), the command palette (cmdk), and the incident detail view showing the cited root-cause evidence. Use TanStack Query for all data fetching so retries/caching aren't hand-rolled per-component. This is also where Section 3's visual identity gets implemented — do this after the API is stable, not in parallel with it, so you're not building UI against a shape that keeps changing.

### Phase 9 — AuthN/AuthZ hardening pass
Wire up JWT session auth for the dashboard and confirm the least-privilege DB roles from Phase 1 are actually enforced end-to-end (write a test that asserts the ingestion role genuinely cannot `SELECT`, not just that it's configured that way). This is a dedicated pass, not something bolted on per-endpoint as you go, because auth bugs are exactly the kind of thing that's easy to get subtly wrong when it's scattered across many small changes.

### Phase 10 — Self-observability
Instrument SignalStack's own services with the same OpenTelemetry approach it recommends for its users, exporting to the Grafana+Tempo stack from Phase 0. Add structured logging via structlog everywhere. This phase is what turns "we built an observability tool" into "we run our own observability tool," which is the more credible claim.

### Phase 11 — CI/CD & deployment
GitHub Actions pipeline: Ruff → Pyright → pytest (with testcontainers) → Trivy scan on the built image → deploy to the self-hosted VM from Section 7 (Oracle Cloud Always Free), not Fly.io — Section 7 corrected that choice after Fly.io dropped its free tier. Get this running early enough that it's protecting real work, not bolted on right before a demo when it's too late to catch anything.

### Phase 12 — Personality & polish pass
A dedicated pass after the system works functionally: empty states, error states, loading states, the command palette's keyboard shortcuts, copy tone throughout the UI. This is deliberately last — polishing a UI whose data model is still shifting is wasted effort, but skipping this phase entirely is how a technically solid project still reads as a half-finished template.

---

## 3. Product personality

A dashboard that works but looks like every other admin-template SaaS reads as a tutorial project regardless of what's happening underneath it. This section is meant to be treated as concrete implementation input, not mood-board inspiration.

**Naming.** "SignalStack" is a placeholder and reads generically. Sharper alternatives worth considering: **Culprit** (one word, confident, states the product's entire value proposition — "found the culprit"), **Blast Radius** (evokes exactly what the correlation engine computes — the scope of an incident's impact), **Aftershock** (evokes cascading failures across services). Pick one and use it consistently everywhere, including in the LLM's own voice ("Culprit thinks this is your root cause" reads very differently from a generic dashboard label).

**Visual identity.** Dark-mode-first, not dark-mode-as-an-afterthought-toggle — this is a tool for people staring at it during an incident at 2am, and it should look like it knows that. A constrained palette: near-black background (not pure `#000`), a single confident accent color for "this is the answer" moments (avoid default Tailwind blue — it's the fastest way to look like every other SaaS product built in the last five years), and reserved red/amber strictly for severity, not decoration. Typography: a monospace face (JetBrains Mono or Berkeley Mono) for anything that's actually data — metric values, timestamps, service names — paired with a clean sans (Inter or Geist) for UI chrome. The monospace-for-data convention is a small detail that reads as "built by someone who thinks about what a number is," not decoration for its own sake.

**Voice charter for the LLM's root-cause narrative.** This is a concrete artifact to write into the system prompt, not a vibe: state the hypothesis first, then the evidence — never bury the conclusion. Ban hedge words ("might," "could possibly," "it seems") in favor of an explicit confidence label (High/Medium/Low) attached to a stated reason. Always cite the specific retrieved postmortem passage the hypothesis is grounded in, visibly, like a footnote — this makes the suggestion auditable instead of a "trust me" black box, which is both a personality choice and a real trust/safety feature. Cap it at a few sentences; a root-cause suggestion that reads like a wall of text has already failed at 2am.

**Signature UX moments.** The incident timeline should look like a flight recorder or a git-blame view — a dense, technical, information-first visualization — rather than a generic line chart with tooltips. The command palette (cmdk) means a user can jump to any incident, service, or postmortem without touching the mouse, which is a small thing that disproportionately signals "built by someone who uses good tools themselves." Empty and error states should carry the same voice as the LLM narratives — terse and specific ("No anomalies in the last 4 hours across order-service, payments-service, or inventory-service" beats a generic "No data") — small, but it's the difference between a product with a point of view and a template with data in it.

---

## 4. Security checklist (cross-cutting reference)

Consolidated so a review pass doesn't require re-reading every phase above.

- Least-privilege Postgres roles: ingestion-writer (INSERT-only on raw tables), api-reader (SELECT-only), enforced and tested, not just configured.
- Scoped API keys for service-to-service ingestion auth, separate from user-facing JWT session auth.
- Secrets via environment variables locally (`.env`, gitignored) and a real secrets store in whatever host you deploy to (Render/Fly.io secrets, or a `.env` restricted to root-only permissions on a self-hosted VM) — never committed, never hardcoded even for "just the demo."
- Rate limiting specifically on any endpoint that triggers an LLM call — cost and abuse control, not just general throttling.
- Treat ingested log/postmortem content as untrusted input to any LLM prompt — sanitize/truncate, and never let ingested content itself trigger tool calls (prompt-injection surface).
- Dependency scanning (pip-audit or Dependabot) and container image scanning (Trivy) both wired into CI, not run manually before a demo.
- argon2 for password hashing, not bcrypt or, worse, hand-rolled hashing.
- TLS everywhere in deployment (handled automatically by Render; on a self-hosted VM, terminate it with Caddy, which gets you free Let's Encrypt certs with near-zero config — verify it either way, don't assume it).

## 5. Performance checklist (cross-cutting reference)

- Batch writes into TimescaleDB from the stream consumer; never one `INSERT` per ingested event.
- TimescaleDB compression + retention policy on the raw-event hypertable set up in Phase 1, not retrofitted after the table is already large.
- Redis Streams consumer groups for backpressure handling — the ingestion gateway should never be able to overwhelm a slow consumer into data loss.
- Anomaly scoring and RAG/LLM calls run as background arq jobs, off the request path — the API should never block on either.
- Pagination on every list endpoint; no endpoint that can return an unbounded result set.
- TanStack Query caching on the frontend so the dashboard isn't re-fetching unchanged data on every render.
- Async SQLAlchemy throughout so a slow query doesn't block the event loop for unrelated requests.

## 6. Guardrails (do not build yet)

Carried forward from `CLAUDE.md` and restated here because a "make it feel real" instinct is exactly what causes scope creep: no Kafka, no multi-tenant configurable N-services platform, no trained anomaly-detection model, no Slack bot, no auto-generated postmortems, no per-service learned baselines. Every item in this list is a legitimate V2 idea and a bad use of MVP effort.

## 7. Cost & free-tier notes

Checked against current (Aug 2026) pricing. Two viable paths, depending on how much server-ops you want to own yourself.

**Database — already effectively free.** Timescale Cloud's free tier covers 10 GB storage, pre-installed pgvector included, explicitly positioned for proof-of-concept deployments. The Phase 1 compression/retention policies keep raw_events from growing unbounded, so a demo stays under 10 GB indefinitely. No change from the original plan — just don't skip those policies, or this stops being free.

**Embeddings — already effectively free, but the model choice matters.** Voyage AI's 200M free-token allocation applies only to the `voyage-4` generation — `voyage-3.x` models (the original pick in Section 1) no longer get a free allocation at all. Use `voyage-4` or `voyage-4-lite`. 200M tokens is far more than a demo postmortem corpus will ever use.

**Self-observability — free either way, pick based on how much you want to maintain.** Grafana Cloud's free tier (10K active metric series, 50 GB logs, 50 GB traces, 14-day retention, no card required, no expiration as of mid-2026) comfortably covers this project and removes Grafana+Tempo from the things you self-host and patch. Self-hosting them locally via Phase 0's docker-compose is also free and remains the right call for local dev either way — this is only about where the *deployed* instance's telemetry goes.

**App hosting — this is where the original plan actually cost money, and where the real decision is.** Fly.io removed its free tier in 2024; a minimal always-on service there now runs ~$2/month, and this project needs three (API, worker, frontend), plus Redis. Two ways to get close to $0 instead:
- **Self-host everything on one free VM.** Oracle Cloud's Always Free tier (historically 4 ARM OCPUs / 24 GB RAM, though some new accounts are now being provisioned at a reduced 2 OCPU / 12 GB, and ARM capacity can be constrained in some regions) runs the exact same docker-compose stack from Phase 0 — Postgres+Timescale+pgvector, Redis, API, worker, frontend — for $0/month indefinitely. Terminate TLS with Caddy (free, auto-renewing Let's Encrypt certs, near-zero config). This is also arguably a *better* CV story than a managed PaaS: "I provisioned and operate my own production box" is a more senior claim than "I clicked deploy."
- **Stay on managed hosting, pay only where you must.** Render's free tier covers the frontend (unlimited static sites) and one web service, though that free web service spins down after 15 minutes idle — a bad look if a recruiter clicks your demo link cold. A Starter web service ($7/month) keeps the API always warm. Don't run the arq worker as a persistent Starter service if avoidable — restructure the scheduled jobs (Phases 3-5) as Render Cron Jobs instead, which bill per minute of actual execution (fractions of a cent per run at this volume) rather than a $7-25/month always-on dyno. Upstash's Redis free tier (256 MB, 500K commands/month, no card required) covers this project's stream volume comfortably.

**LLM root-cause generation — the one real, unavoidable recurring cost.** No free tier exists for ongoing Claude API usage. Use Haiku 4.5 specifically for this call ($1/$5 per million tokens) — the root-cause narrative is short, structured, and RAG-grounded, not a task that needs frontier-model reasoning. At a demo's actual incident volume (occasional fault-injector runs, not production traffic), this realistically costs cents to low single-digit dollars total, not a meaningful recurring bill.

**CI/CD — already free.** GitHub Actions gives 2,000 free minutes/month on a private repo, or completely unmetered free minutes if the repo is public. Given this is a portfolio project, making the repo public is worth considering anyway — it makes CI fully free *and* means recruiters can actually see the code, which a private repo defeats the purpose of.

**Net realistic cost:** the fully self-hosted path (Oracle free VM + Timescale Cloud free + Grafana Cloud free + Voyage free) runs $0/month in infrastructure, with only Claude API usage as a real (and small) recurring cost. The managed-hosting path (Render Starter + Upstash free + Timescale Cloud free + Grafana Cloud free) runs roughly $7-10/month in exchange for not operating a VM yourself. Neither path requires downgrading anything in Section 1's stack — this is entirely about *where* things run, not swapping out River, arq, TimescaleDB, or pgvector for cheaper substitutes that would cost you the "not vibe coded" quality bar.
