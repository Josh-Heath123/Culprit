# Culprit — Self-Hosted Product Plan (Phases 13–20)

Written 2026-08-04. Companion to `docs/IMPLEMENTATION_PLAN.md` (Phases 0–12, all
built and deployed) — that document is history now; this one is the forward
backlog. `CLAUDE.md`'s "Toward a self-hosted, downloadable product" section is
the short version of what's below; this is the executable version.

**The one-sentence goal:** a solo developer or a three-person startup clones
this repo, runs one command, points their own services at it, and sees a real
correlated incident with a grounded root-cause narrative — without editing a
single line of Python.

---

## 0. How to use this document

Each phase below is written to be handed to a single Claude Code session with
no other context beyond `CLAUDE.md` and the repo itself. A phase section
contains, in this order:

- **Goal** — one paragraph, what "done" means in product terms.
- **Depends on** — which earlier phases must be merged first, and why.
- **Out of scope** — the specific adjacent things that will feel tempting
  mid-phase and must be flagged back rather than built. This section is
  load-bearing: this project's stated biggest risk is scope creep, not
  technical difficulty.
- **Files touched** — exact paths, marked `NEW` / `EDIT` / `DELETE`.
- **Schema changes** — the migration, sketched concretely enough to write.
- **API / config surface** — exact request and response shapes.
- **Steps** — ordered, each one independently reviewable.
- **Acceptance criteria** — observable, checkable statements. Not "works
  correctly."
- **Tests** — what to add, and at which layer.
- **Rollback** — what to do if this lands and breaks the live deployment at
  `culprit.co.za`.
- **Known traps** — the specific mistakes that are likely in *this* codebase,
  drawn from what already went wrong in Phases 0–12.

**One phase per branch, one phase per PR.** Every phase below ends with a
green CI run as an acceptance criterion, and CI already gates lint → typecheck
(+ `lint-imports` + `check-schema-drift`) → pytest → Trivy → push → deploy.
Do not stack two phases into one branch; the deploy step is live and a failed
health check takes down a real domain.

---

## 1. Invariants — true in every phase below

These are not restated in each phase. Violating one of them is a defect even
if the feature works.

1. **Anomaly detection stays statistical. Correlation stays rule-based. Only
   the root-cause narrative is an LLM call, and only after retrieval.** Making
   services configurable does not make "ask the LLM which services are
   related" acceptable. `worker`'s import-linter contracts
   (`worker/pyproject.toml`, `[[tool.importlinter.contracts]]`) enforce the
   module boundary structurally; if a change needs `app.anomaly` or
   `app.correlation` to import `app.rag`, that is a design error, not a lint
   config to silence.
2. **`worker/app/db.py` and `api/app/db/models.py` must not drift.** Every
   schema change below touches *both*, plus a migration.
   `scripts/check_schema_drift.py` (`just check-schema-drift`) runs in CI and
   will fail the build. Nullability matters: a column declared with only a
   `server_default` and no explicit `NOT NULL` is nullable, and must be typed
   `Mapped[X | None]` on the ORM side. This exact mistake has already been
   made four times in this repo.
3. **Least privilege per job, enforced by DB roles, not by convention.** Every
   new table gets explicit `GRANT`s in a migration for exactly the roles that
   need it. The existing roles are `ingestion-writer`, `api-reader`,
   `ingest-gateway`, `anomaly-detector`, `correlation-engine`,
   `root-cause-writer`. If a new component needs writes the API currently
   can't do, add a role — do not widen `api-reader`.
4. **Migrations are historical snapshots.** They do not import mutable
   application code (`shared/culprit_shared/services.py` is deliberately
   duplicated by hand into `api/migrations/versions/48c0b29fa215_*.py` for
   this reason). Phase 14 makes one narrow, deliberate exception to the
   "never edit an applied migration" rule — see Phase 14, Trap 1, which
   explains exactly why it's safe there and nowhere else.
5. **Secrets never enter CI.** `infra/.env.prod` is created by hand on the VM
   and never written by GitHub Actions. The only real secret CI holds is the
   SSH deploy key. Any setup tooling added in Phase 17 runs on the target
   machine, never on a runner.
6. **Scope ceilings from `CLAUDE.md` still apply.** Redis Streams, not Kafka.
   Statistical scoring, not a trained model. No Slack bot, no auto-generated
   postmortems. Making the product installable by a third party is not a
   licence to widen the MVP itself.
7. **Don't dump raw telemetry into context to debug.** `raw_events` is
   high-volume by design; query a bounded time window.

---

## 2. Phase order and dependency graph

```
Phase 13  Frontend routing + real 404            (independent, small)
   │
Phase 14  Service registry + API-key management  ← THE BLOCKER
   │
   ├── Phase 15  Public ingest path + instrumentation guide
   │
   ├── Phase 16  Multi-user auth + roles
   │        │
   │        └── Phase 17  One-command setup + local quickstart
   │
   ├── Phase 18  Postmortem write path (needs 13 for routing, 16 for authorship)
   │
   └── Phase 19  Topology inference from traces (replaces hand-declared edges)

Phase 20  Release engineering, docs, upgrade path  (last; needs all of the above)
```

**Why this order, given `CLAUDE.md` lists the gaps differently.** `CLAUDE.md`
lists topology inference as gap #2, but it is a *quality* improvement on top of
a user-declared graph, not a prerequisite for anyone using the product. A
hand-declared adjacency in the service registry (Phase 14) is a perfectly
serviceable v1. Inference is therefore late (Phase 19), and is the one phase
here that is genuinely optional.

Auth (Phase 16) comes before the setup script (Phase 17) so the script
bootstraps a real user row rather than an env-var argon2 hash it would then
have to un-build. This is the single ordering choice most likely to be
questioned mid-programme; it is deliberate.

---

## Phase 13 — Frontend routing and a real 404

### Goal

`App.tsx` is currently `token ? <Dashboard /> : <LoginScreen />` with no router
at all, so every URL path renders identically and an unknown path silently
shows the dashboard (or the login screen). Introduce real client-side routing
with typed routes, a genuine 404 state written in the Section 3 voice charter,
and deep-linkable incident URLs. Every later phase adds pages (`/settings/services`,
`/incidents/:id/postmortem`); this is the prerequisite for all of them.

### Depends on

Nothing. Do this first — it is small, self-contained, and unblocks three later
phases.

### Out of scope

- Server-side rendering. Caddy's `try_files {path} /index.html` already serves
  the SPA shell for any path; that stays.
- A navigation redesign. `components/layout/Nav.tsx` exists and stays as-is
  apart from becoming router-aware.
- Route-level code splitting. The bundle is small; revisit if it isn't.

### Files touched

| Path | Action |
| --- | --- |
| `frontend/package.json` | EDIT — add `react-router-dom@^7` |
| `frontend/src/App.tsx` | EDIT — router setup, auth gate becomes a layout route |
| `frontend/src/routes/` | NEW — `AppRoutes.tsx`, `RequireAuth.tsx`, `NotFound.tsx` |
| `frontend/src/components/Dashboard.tsx` | EDIT — selected incident comes from the URL, not local state |
| `frontend/src/components/incident-detail/IncidentDetailPanel.tsx` | EDIT — close navigates, doesn't just setState |
| `frontend/src/components/command-palette/CommandPalette.tsx` | EDIT — actions navigate |
| `frontend/src/components/layout/Nav.tsx` | EDIT — `NavLink` instead of static markup |
| `frontend/src/lib/auth.ts` | EDIT — 401 handler redirects to `/login` with a `?next=` param |

### Route table

| Path | Auth | Renders |
| --- | --- | --- |
| `/login` | public | `LoginScreen`; redirects to `next` (or `/`) if already authenticated |
| `/` | required | `Dashboard` (timeline, no incident selected) |
| `/incidents/:incidentId` | required | `Dashboard` with the detail panel open on that incident |
| `*` | public | `NotFound` — HTTP-200 SPA page, real 404 copy |

A malformed or unknown `:incidentId` must render the panel's existing error
state (the API already returns 404 from `GET /incidents/{id}`), **not** the
global `NotFound` page — an incident that has been deleted or never existed is
a different user story from a mistyped URL, and conflating them was the whole
point of fixing this.

### Steps

1. Add the dependency. Pin against React 18 (`react@^18.3.1` is what's
   installed) — react-router 7 supports it, but confirm at install time rather
   than assuming.
2. Create `routes/RequireAuth.tsx`: reads `useAuthToken()`, renders `<Outlet />`
   when present, otherwise `<Navigate to={"/login?next=" + encodeURIComponent(location.pathname + location.search)} replace />`.
3. Create `routes/NotFound.tsx`. Copy tone per `docs/IMPLEMENTATION_PLAN.md` §3
   — dry and specific, not cute. It must offer a link back to `/` and must not
   look like a browser error page.
4. Rewrite `App.tsx`: `QueryClientProvider` → `TooltipProvider` →
   `BrowserRouter` → `AppRoutes`. Keep the existing `useEffect` that calls
   `queryClient.clear()` when the token disappears — it is still correct and
   still necessary.
5. `Dashboard.tsx`: replace the `selectedIncidentId` state with
   `useParams<{ incidentId?: string }>()`. Selection becomes
   `navigate(`/incidents/${id}`)`; closing becomes `navigate("/")`.
6. Update `CommandPalette.tsx` so "jump to incident" navigates rather than
   calling a callback prop.
7. `lib/auth.ts` / `lib/api.ts`: on 401, clear the in-memory token as it does
   today *and* let the router redirect. Do not add `localStorage` — the
   deliberate decision that a refresh means logging in again stands
   (`frontend/src/lib/auth.ts` documents why).

### Acceptance criteria

- `https://culprit.co.za/nonsense` renders the 404 page, not the dashboard and
  not the login screen.
- `https://culprit.co.za/incidents/<real-uuid>` deep-links straight into that
  incident's detail panel after login, including when the user was logged out
  when they clicked the link (the `?next=` round-trip works).
- `https://culprit.co.za/incidents/00000000-0000-0000-0000-000000000000`
  renders the detail panel's error state, not the 404 page.
- Browser back/forward move between the timeline and an open incident.
- `npm run lint` (oxlint) and `tsc -b` both clean; CI green.

### Tests

The frontend currently has no test runner at all. Do **not** stand up Vitest +
Testing Library as part of this phase — that is its own decision with its own
CI cost, and bundling it here makes this phase unreviewable. Verify manually
against the four acceptance criteria above and note in the PR description that
frontend testing remains unaddressed. If it is going to be added, add it as a
deliberate standalone piece of work.

### Rollback

Pure frontend change. Revert the commit and redeploy; no schema, no API, no
data migration.

### Known traps

- **Trap 1.** `frontend/Caddyfile`'s `try_files {path} /index.html` is what
  makes client-side routes survive a hard refresh in production. It's already
  correct — but the *local* Vite dev server has its own history fallback, so a
  route that works locally and 404s in production means this line was touched.
  Don't touch it.
- **Trap 2.** `frontend/vite.config.ts` deliberately sets no `base`, so it
  defaults to `/`. Caddy serves the SPA at the domain root and proxies `/api/*`
  separately; adding a non-root base breaks asset paths only in the production
  image, not in `npm run dev`.

---

## Phase 14 — Service registry and API-key management

### Goal

This is the blocker: today, onboarding a service means editing
`shared/culprit_shared/services.py`, editing
`frontend/src/lib/services.ts`, and writing an Alembic migration. After this
phase, a service is a row in a table, created through an authenticated admin
API (or a declarative YAML applied by a script), with its own API key issued at
creation time and shown exactly once. Correlation reads its adjacency from the
database. The frontend reads its service list from the API.

### Depends on

Phase 13 (the settings UI needs a route). The backend half does not, so the
backend can proceed in parallel if Phase 13 is in review.

### Out of scope

- **Inferring topology.** Adjacency is user-declared here. Phase 19.
- **Multi-tenancy.** One Culprit install serves one team's services. There is
  no org/tenant concept and adding one is not in this plan at all.
- **Per-service retention or sampling policy.** `raw_events` compression and
  retention stay global (`api/migrations/versions/e2cab79bcc93_*.py`).
- **Deleting a service's historical data.** Deleting a service registration
  must not cascade into `raw_events`/`anomalies` — see step 9.

### Schema changes

One new migration, `NEW api/migrations/versions/<rev>_create_service_registry.py`,
revising down from the current head. Contents:

```sql
CREATE TABLE services (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name               TEXT NOT NULL UNIQUE,        -- matches OTel resource service.name exactly
    display_name       TEXT,                        -- NULL => fall back to name in the UI
    sort_order         INTEGER NOT NULL DEFAULT 0,  -- timeline lane order
    monitored_metrics  JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [] => score every metric seen
    disabled_at        TIMESTAMPTZ,                 -- soft delete; ingest rejects, history retained
    created_at         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_services_sort_order ON services (sort_order, name);

CREATE TABLE service_dependencies (
    from_service_id  UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    to_service_id    UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    created_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (from_service_id, to_service_id),
    CONSTRAINT ck_service_dependencies_no_self_edge CHECK (from_service_id <> to_service_id)
);
```

Edges are **directed** (`from` calls `to`) and stored one row per direction.
`worker/app/correlation/graph.py`'s `_services_related` currently treats the
relation as effectively symmetric (`b in SERVICE_ADJACENCY.get(a)`, with the
hardcoded dict listing both directions). Preserve that behaviour exactly:
build the in-memory adjacency by inserting both `(from, to)` and `(to, from)`.
Storing direction anyway costs nothing now and is what Phase 19's inference
will actually produce.

`api_keys` changes in the same migration:

```sql
ALTER TABLE api_keys ADD COLUMN service_id UUID REFERENCES services(id) ON DELETE CASCADE;
ALTER TABLE api_keys ADD COLUMN label TEXT;             -- e.g. "rotated 2026-08-10"
ALTER TABLE api_keys ADD COLUMN revoked_at TIMESTAMPTZ;
ALTER TABLE api_keys ADD COLUMN last_used_at TIMESTAMPTZ;
ALTER TABLE api_keys DROP CONSTRAINT api_keys_service_name_key;  -- confirm the real name first
```

Dropping the `service_name` unique constraint is what makes key rotation
possible (two live keys for one service during a cutover). `key_hash` stays
unique. Keep the `service_name` column: `ingest_gateway/auth.py` returns it and
it is the value written to `raw_events.service_name`, so removing it is a much
larger change for no benefit. Add a `NOT NULL` on `service_id` only *after* the
backfill in the same migration succeeds.

Backfill, in this order:

```sql
INSERT INTO services (name, sort_order)
SELECT service_name, row_number() OVER (ORDER BY created_at, service_name)
FROM api_keys
ON CONFLICT (name) DO NOTHING;

UPDATE api_keys SET service_id = s.id FROM services s WHERE s.name = api_keys.service_name;
```

Then insert the demo adjacency edges **only for services that were backfilled**
— i.e. join against `services` by name for the three demo names and skip
silently if absent. On the live `culprit.co.za` database this reproduces
today's exact behaviour; on a fresh install with no demo keys it is a no-op.

Grants in the same migration:

```sql
GRANT SELECT ON services, service_dependencies TO "correlation-engine";
GRANT SELECT ON services, service_dependencies TO "api-reader";
GRANT SELECT ON services TO "anomaly-detector";      -- for monitored_metrics filtering
GRANT SELECT ON services, api_keys TO "ingest-gateway";  -- verify api_keys grant already exists
```

`api-reader` stays SELECT-only. Writes to `services`/`api_keys` need a new
role:

```sql
CREATE ROLE "registry-admin" LOGIN PASSWORD :registry_admin_password;
GRANT USAGE ON SCHEMA public TO "registry-admin";
GRANT SELECT, INSERT, UPDATE, DELETE ON services, service_dependencies, api_keys TO "registry-admin";
```

Password from `REGISTRY_ADMIN_DB_PASSWORD`, following the exact pattern in
`api/migrations/versions/a0cac3233f8d_create_correlation_engine_role.py`
(including `_require_env` and `_pg_string_literal`).

### API surface

New router `api/app/registry/router.py`, mounted at `/services`, gated by the
same `require_auth` dependency `incidents_router` uses (Phase 16 upgrades this
to `require_admin` without changing any path).

```
GET    /services
       -> 200 {"items": [ServiceOut, ...]}

POST   /services
       <- {"name": "checkout-api", "display_name": "Checkout API",
           "depends_on": ["postgres-proxy"], "monitored_metrics": []}
       -> 201 {"service": ServiceOut, "api_key": "clp_live_<43 url-safe chars>"}
          api_key is returned EXACTLY ONCE and never retrievable again.

GET    /services/{service_id}          -> 200 ServiceOut | 404
PATCH  /services/{service_id}          <- any of display_name, sort_order,
                                          monitored_metrics, depends_on, disabled
                                       -> 200 ServiceOut
DELETE /services/{service_id}          -> 204   (soft delete: sets disabled_at)
DELETE /services/{service_id}?purge=true -> 204 (hard delete of the registration
                                          row + its keys; telemetry history is
                                          deliberately NOT deleted — see step 9)

POST   /services/{service_id}/keys
       <- {"label": "rotation 2026-08-10"}
       -> 201 {"api_key": "clp_live_...", "key_id": "<uuid>", "label": ...}
DELETE /services/{service_id}/keys/{key_id}  -> 204 (sets revoked_at)
```

`ServiceOut`:

```json
{
  "id": "uuid",
  "name": "checkout-api",
  "display_name": "Checkout API",
  "sort_order": 1,
  "monitored_metrics": [],
  "disabled": false,
  "depends_on": ["postgres-proxy"],
  "keys": [{"id": "uuid", "label": "initial", "created_at": "...",
            "last_used_at": "...", "revoked": false}],
  "created_at": "..."
}
```

Never include `key_hash` or any key material in `ServiceOut`. Add a test that
asserts this by string-searching the serialised response, not just by reading
the schema — this is the class of bug that a later "just add the field" change
reintroduces silently.

Validation on `name`: `^[a-z0-9][a-z0-9._-]{0,62}$`. It must match the OTel
`service.name` resource attribute byte-for-byte, so reject anything that would
produce a confusing mismatch (uppercase, spaces, leading punctuation).

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_create_service_registry.py` | NEW |
| `api/migrations/versions/48c0b29fa215_create_api_keys_table.py` | EDIT — see Trap 1 |
| `api/app/db/models.py` | EDIT — `Service`, `ServiceDependency`; extend `ApiKey` |
| `worker/app/db.py` | EDIT — mirror `services`, `service_dependencies`, new `api_keys` columns |
| `api/app/registry/__init__.py`, `router.py`, `schemas.py`, `service.py`, `keys.py` | NEW |
| `api/app/registry/config.py` | NEW — `REGISTRY_ADMIN_DATABASE_URL` |
| `api/app/main.py` | EDIT — second engine for the registry role; mount router |
| `api/app/ingest_gateway/auth.py` | EDIT — cache refresh, revoked-key filtering, `last_used_at` |
| `api/scripts/apply_services.py` | NEW — declarative YAML apply |
| `shared/culprit_shared/services.py` | EDIT — see step 8; do not delete the file |
| `worker/app/correlation/graph.py` | EDIT — adjacency becomes a parameter |
| `worker/app/correlation/job.py` | EDIT — load adjacency from DB per run |
| `worker/app/anomaly/job.py` | EDIT — honour `monitored_metrics` |
| `worker/app/main.py` | EDIT — `registry` read engine in `ctx` |
| `frontend/src/lib/services.ts` | DELETE |
| `frontend/src/hooks/useServices.ts` | NEW |
| `frontend/src/components/timeline/Timeline.tsx` | EDIT — lanes from the API |
| `frontend/src/components/EmptyState.tsx` | EDIT — copy no longer names demo services |
| `frontend/src/routes/SettingsServices.tsx` | NEW |
| `justfile` | EDIT — `just apply-services` |
| `infra/.env.prod.example` | EDIT — `REGISTRY_ADMIN_*`, demo keys become optional |
| `docs/IMPLEMENTATION_PLAN.md` | EDIT — mark the Phase 3 "three fixed keys" decision superseded |

### Steps

1. **Migration first, applied locally against `just up`**, before any
   application code. Confirm `alembic upgrade head` then `alembic downgrade -1`
   both succeed on a database that already contains the three demo services —
   a downgrade that fails on real data is a broken migration even if the
   upgrade works.
2. Update `api/app/db/models.py` and `worker/app/db.py` **in the same commit**,
   then run `just check-schema-drift` before writing anything else. Watch
   nullability: `created_at`, `disabled_at`, `revoked_at`, `last_used_at`,
   `display_name`, and `service_id` (pre-backfill) are all nullable.
3. Build `api/app/registry/` — `service.py` for DB access, `keys.py` for
   generation/hashing, `schemas.py` for Pydantic, `router.py` for HTTP. Key
   generation: `"clp_live_" + secrets.token_urlsafe(32)`. Hash with the same
   plain SHA-256 as `ingest_gateway/auth.py::_hash_key` — the reasoning in
   that function's comment (high-entropy generated tokens, not user-chosen
   passwords) still holds. Import that helper rather than reimplementing it;
   two independent SHA-256 helpers is exactly how a future change breaks one
   side only.
4. Wire the second engine in `api/app/main.py`'s lifespan:
   `app.state.registry_session_factory` on `REGISTRY_ADMIN_DATABASE_URL`.
   `app.state.session_factory` (api-reader) stays untouched and stays
   read-only. Registry reads (`GET /services`) may use api-reader; only writes
   need registry-admin.
5. **`ingest_gateway/auth.py` cache invalidation.** `ApiKeyStore.load()` runs
   once at startup today, so a key created after boot never authenticates —
   the single most likely "the admin API works but ingest still 401s" bug in
   this phase. Implement: keep the in-memory map, but on an authentication
   *miss*, reload from the DB at most once per `_MIN_RELOAD_INTERVAL` (10s) and
   retry the lookup once. Also filter `revoked_at IS NULL` and
   `services.disabled_at IS NULL` in the load query. Update `last_used_at`
   opportunistically — at most once per key per minute, fire-and-forget, and
   never on the request's critical path. Do not add a DB round-trip per
   ingested payload; that is the throughput cliff.
6. **Correlation reads adjacency from the DB.** Change
   `graph.build_graph(nodes)` to `build_graph(nodes, adjacency)` where
   `adjacency: Mapping[str, frozenset[str]]`. `graph.py` stays pure and
   import-free of DB code — that separation is the reason its tests are worth
   anything. `correlation/job.py` loads the adjacency once per run into a plain
   dict, from the `correlation-engine` engine already in `ctx`. Cache it
   in-process for ~60s to avoid a query every 5-second tick; a service added
   mid-minute correlating one tick late is acceptable and should be said out
   loud in a comment.
7. **Anomaly scoring honours `monitored_metrics`.** In `anomaly/job.py`, after
   pulling the batch, drop rows whose `(service_name, metric_name)` isn't in
   the service's allowlist — with an empty list meaning "score everything", so
   existing behaviour is unchanged. This matters more than it looks: a real
   third-party service exports hundreds of metrics, and today every single one
   would get its own persistent EWMA scorer in Redis.
8. **`shared/culprit_shared/services.py` does not get deleted.** Rewrite it as
   the *demo* topology only, rename the constants to `DEMO_SERVICE_ADJACENCY`,
   `DEMO_SERVICES`, `DEMO_SERVICE_API_KEY_ENV_VARS`, and update its docstring
   to say it is demo fixture data, no longer the product's source of truth.
   `demo-services/shared/otel.py` still imports the env-var mapping and that is
   correct. `worker/app/correlation/graph.py` must stop importing it.
9. **Deletion semantics.** `DELETE /services/{id}` is a soft delete
   (`disabled_at = now()`): ingest starts rejecting that service's keys, the
   timeline stops showing a lane for it, but every historical `raw_events`,
   `anomalies`, and `incident_candidates` row survives. `?purge=true` hard
   deletes the registration and its keys. Neither ever touches telemetry
   tables — `raw_events` has no FK to `services` on purpose (it is a
   TimescaleDB hypertable, and this project already documents why FKs into
   hypertables are avoided).
10. `api/scripts/apply_services.py` — reads a YAML file, diffs against the DB,
    applies creates/updates, and prints newly-issued keys to stdout. Idempotent.
    Never deletes unless `--prune` is passed. Wire as `just apply-services`.
    File shape:

    ```yaml
    services:
      - name: checkout-api
        display_name: Checkout API
        depends_on: [inventory-api, payments-api]
        monitored_metrics: [http.server.duration, http.server.errors]
      - name: inventory-api
        depends_on: []
    ```

11. Frontend: `useServices()` hook (react-query, same conventions as
    `useIncidents`), delete `lib/services.ts`, drive `Timeline.tsx` lanes off
    the fetched list ordered by `sort_order` then `name`. `Timeline.tsx`'s
    existing `knownServices` guard (which drops anomalies from unknown
    services) must be kept — an anomaly can legitimately arrive from a service
    that was disabled a second ago.
12. `SettingsServices.tsx` at `/settings/services`: table of services, add
    form, dependency multi-select, key list with "issue new key" and "revoke".
    The one-time key display must be unmissable and must say plainly that it
    won't be shown again.

### Acceptance criteria

- On a *fresh* database with none of `ORDER_SERVICE_API_KEY` /
  `INVENTORY_SERVICE_API_KEY` / `PAYMENTS_SERVICE_API_KEY` set,
  `alembic upgrade head` completes and `services` is empty.
- On the live database, after `alembic upgrade head`, the three demo services
  and their four adjacency edges (order↔inventory, order↔payments) exist, all
  three existing API keys still authenticate, and the dashboard is unchanged
  visually.
- `POST /services` with a new name returns a key; that key authenticates
  against `/v1/metrics` **within 10 seconds and without restarting any
  container**.
- Two anomalies on two newly-registered, declared-adjacent services within
  5 minutes correlate into one incident, with no code change and no restart.
- `DELETE /services/{id}` (soft) stops new ingest for that service while
  `GET /incidents` still returns its historical incidents intact.
- `GET /services` never contains a `key_hash` or a plaintext key, asserted by
  a test that searches the raw response body.
- `just check-schema-drift`, `just lint-imports`, `just lint`, `just typecheck`,
  `just test` all pass; CI green; deploy health check passes.

### Tests

This is the phase to introduce the first real integration tests — the logic is
DB-shaped and unit tests will not catch the interesting failures.
`testcontainers[postgres]` is already a dev dependency in both `api` and
`worker` and `.github/workflows/ci-cd.yml` already notes that the runner can
support it. Add:

- `api/tests/conftest.py` — a session-scoped Postgres container fixture that
  runs `alembic upgrade head` against it. Keep the existing `load_dotenv()`
  at the top of the file; it is there for a real reason (import-time env reads
  in `app/auth/config.py`) and removing it breaks unrelated tests.
- `api/tests/test_registry_api.py` — create/list/patch/soft-delete/purge,
  duplicate name rejection, name validation, one-time key exposure, and the
  no-key-material-in-responses assertion.
- `api/tests/test_ingest_gateway_key_refresh.py` — a key created after
  `ApiKeyStore.load()` authenticates after the refresh interval; a revoked key
  stops authenticating; a disabled service's key stops authenticating.
- `worker/tests/test_correlation_graph.py` — EDIT the existing tests to pass
  adjacency explicitly. Add a case proving two non-adjacent services in the
  same time window do *not* correlate — that assertion is the entire point of
  the adjacency condition and it must survive the refactor.
- `worker/tests/test_anomaly_metric_allowlist.py` — empty list scores
  everything; a populated list scores only its members.

### Rollback

The migration's `downgrade()` must restore the `api_keys` unique constraint and
drop the new tables. Verify `downgrade` on a copy of production data *before*
merging, not after. If the deploy fails post-merge, `deploy.sh` will have
already run `alembic upgrade head`, so rollback is: redeploy the previous image
tag **and** run `alembic downgrade -1` on the VM by hand. Write that exact
two-command sequence into the PR description.

### Known traps

- **Trap 1 — the one deliberate exception to "never edit an applied
  migration."** `48c0b29fa215_create_api_keys_table.py` raises
  `RuntimeError` if any of the three demo `*_API_KEY` env vars is unset. On a
  fresh third-party install that is a hard stop demanding three secrets for
  services they will never run. Change the loop body to skip a service whose
  env var is absent (`if not plaintext: continue`) instead of raising, and
  update the docstring to record that this is a *loosening*, dated, with the
  reason. This is safe specifically because Alembic never re-runs an applied
  revision, so no existing database can be affected, and because the change can
  only ever make the migration insert *fewer* rows. It is not a precedent for
  editing migration logic that changes rows already written.
- **Trap 2.** The `api_keys.service_name` unique constraint's actual generated
  name must be read from the live schema (`\d api_keys`) before writing
  `DROP CONSTRAINT` — do not guess it from the SQLAlchemy model.
- **Trap 3.** `frontend/src/lib/services.ts` is imported by `EmptyState.tsx`,
  `Timeline.tsx`, and typed as a const tuple (`ServiceName` is derived from
  it). Deleting the file turns `ServiceName` into a compile error in places
  the grep for `SERVICES` won't show. Search for `ServiceName` too.
- **Trap 4.** `worker/app/db.py`'s `raw_events` table deliberately omits
  `autoincrement=True` for a documented privilege reason. Do not "tidy" it
  while adding the new tables.
- **Trap 5.** Adding a router to `api/app/main.py` also changes the OpenAPI
  schema, which regenerates `frontend/src/lib/api-types.generated.ts` in CI
  before the frontend Docker build. If the new schemas fail to serialise
  (e.g. a bare `dict` field), the *frontend* build breaks with an error that
  looks unrelated to the API change.

---

## Phase 15 — Public ingest path and instrumentation guide

### Goal

A third party's services run somewhere else and currently have no network path
to `ingest-gateway` at all — only ports 80/443 on the `frontend` container are
published. Expose the OTLP endpoints over the existing TLS domain, hardened,
and ship a copyable instrumentation guide that does not reference the demo
services.

### Depends on

Phase 14. Exposing ingest before keys can be issued through an API means the
only way to onboard is still editing a migration.

### Out of scope

- mTLS or IP allowlisting. Per-service bearer keys over TLS is the security
  model; note the trade-off in the docs and move on.
- A hosted OpenTelemetry Collector. The custom gateway stays (`CLAUDE.md`
  Architecture step 1).
- Accepting traces. `/v1/traces` arrives in Phase 19, not here.
- SDKs or client libraries. A documented endpoint plus config snippets.

### Files touched

| Path | Action |
| --- | --- |
| `frontend/Caddyfile` | EDIT — `handle_path /ingest/*` |
| `infra/docker-compose.prod.yml` | EDIT — `frontend` depends_on `ingest-gateway` |
| `api/app/ingest_gateway/main.py` | EDIT — rate limit, body cap, health endpoint |
| `api/app/ingest_gateway/limiter.py` | NEW — per-API-key slowapi limiter |
| `docs/INSTRUMENTATION.md` | NEW |
| `examples/instrument_python.py` | NEW |
| `examples/otel-collector-config.yaml` | NEW |
| `infra/.env.prod.example` | EDIT — `INGEST_RATE_LIMIT`, `INGEST_MAX_BODY_BYTES` |

### Caddy configuration

```caddyfile
{$DOMAIN:localhost} {
	encode gzip

	handle_path /ingest/* {
		request_body {
			max_size {$INGEST_MAX_BODY_BYTES:5MB}
		}
		reverse_proxy ingest-gateway:8010
	}

	handle_path /api/* {
		reverse_proxy api:8000
	}

	handle {
		root * /srv
		file_server
		try_files {path} /index.html
	}
}
```

`handle_path` strips the prefix, so a client configured with
`OTEL_EXPORTER_OTLP_ENDPOINT=https://culprit.example.com/ingest` sends to
`/ingest/v1/metrics` and the gateway sees `/v1/metrics` — no application
change. Order matters in a Caddy site block only for `handle` vs `handle_path`
matchers of overlapping paths; `/ingest/*` and `/api/*` don't overlap, but keep
the catch-all `handle` last regardless.

The `ingest-gateway` container still must not publish a host port. It becomes
reachable only through Caddy.

### Hardening steps

1. **Rate limit per API key, not per IP.** Every service behind one NAT shares
   an IP; `slowapi`'s default key function would throttle them collectively.
   Add `api/app/ingest_gateway/limiter.py` with a key function that returns the
   authenticated `service_name` (falling back to the client IP for
   pre-authentication rejections). Default `INGEST_RATE_LIMIT=600/minute` —
   generous for a 10-second OTel export interval across a handful of services,
   tight enough to matter. Mirror `api/app/incidents/limiter.py`'s structure so
   there is one recognisable pattern.
2. **Body size cap at Caddy** (above) *and* a defensive check in the gateway,
   because the gateway is also reachable directly on the compose network.
   `_maybe_decompress` gzip-decompresses before decoding — cap the
   *decompressed* size too, or a small gzip bomb turns into a large allocation.
   This is a real hole in the current code, not a hypothetical.
3. **A `GET /healthz` on the gateway** returning 200 with no auth, so
   `deploy.sh` can check the ingest path independently of the dashboard API.
   It must not touch the database or Redis — a health endpoint that fails when
   a dependency is slow tells you less, not more.
4. **Log rejected authentications with the presented key's *prefix* only**
   (first 12 characters, e.g. `clp_live_ab…`), never the whole key. Reuse the
   structured-logging conventions already in `main.py`'s access log.
5. **Extend `infra/deploy.sh`'s health check** to poll
   `https://${DOMAIN}/ingest/healthz` as well. Keep the same 12-attempt/5s
   retry loop and the same reasoning about cold Let's Encrypt issuance.

### `docs/INSTRUMENTATION.md` contents

Written for someone who has never seen this repo. It must cover:

- What Culprit accepts today: OTLP/HTTP **metrics** and **logs** over protobuf,
  at `POST {base}/v1/metrics` and `POST {base}/v1/logs`, `Authorization:
  Bearer <api key>`, optional gzip. Traces are not accepted yet — say so
  plainly rather than letting someone configure them and see nothing.
- That `service.name` in the OTel `Resource` must exactly match the registered
  service name, and what happens if it doesn't: nothing breaks, but attribution
  comes from the API key, so the data lands under the *key's* service. That is
  deliberate (`ingest_gateway/auth.py`: the key is the tenancy boundary, not
  the payload) and worth stating.
- Which metrics are worth sending. Anomaly scoring is metric-agnostic — it
  builds a rolling z-score per `(service_name, metric_name)` — so recommend
  starting with request duration and error count and adding more via
  `monitored_metrics` once the baseline is trusted. Recommend the OTel
  semantic-convention names (`http.server.request.duration`,
  `http.server.request.count`); note that the demo services use
  `demo.http.server.*` precisely so demo data is distinguishable from real
  data.
- That a scorer needs history before it can flag anything — a service that has
  been reporting for 30 seconds will produce nothing, and that is correct
  behaviour, not a broken install.
- Language-agnostic path: point `OTEL_EXPORTER_OTLP_ENDPOINT` and
  `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<key>` at Culprit and use
  any OTel SDK.
- `examples/otel-collector-config.yaml`: for teams already running a Collector,
  an `otlphttp` exporter block pointing at Culprit — the lowest-friction
  adoption path for anyone who already has telemetry.
- `examples/instrument_python.py`: a genuinely standalone ~60-line file. It
  must **not** import `culprit_shared` — that is the exact flaw in
  `demo-services/shared/otel.py` that makes it uncopyable.

### Acceptance criteria

- From a machine outside the VM, a Python service configured only with the
  documented env vars gets its metrics into `raw_events` under the right
  `service_name`.
- `curl -X POST https://<domain>/ingest/v1/metrics` with no auth header
  returns 401, and the log line contains no key material.
- A 20MB body is rejected by Caddy before reaching the gateway.
- Exceeding `INGEST_RATE_LIMIT` for one service returns 429 and does not
  affect a second service's ingest.
- `https://<domain>/ingest/healthz` returns 200; `deploy.sh` checks it.
- Port 8010 is not reachable on the VM's public IP (`nmap`/`curl` from
  outside).

### Tests

- `api/tests/test_ingest_gateway_limits.py` — oversized decompressed payload
  rejected; rate limit keyed by service not IP (two keys, one IP, independent
  buckets).
- Manual, and documented in the PR: the external-machine end-to-end check
  above. This is the acceptance criterion that actually matters and it cannot
  be unit-tested.

### Rollback

Revert `frontend/Caddyfile` and redeploy — the ingest path disappears and
nothing else is affected. The gateway hardening is independently safe to keep.

### Known traps

- **Trap 1.** Caddy will attempt certificate issuance for `$DOMAIN` on start.
  A Caddyfile syntax error means the container restarts in a loop and the
  *dashboard* goes down too, because one container serves both. Validate with
  `docker run --rm -v $PWD/frontend/Caddyfile:/etc/caddy/Caddyfile caddy caddy validate --config /etc/caddy/Caddyfile`
  before deploying.
- **Trap 2.** `request_body max_size` is a Caddy v2 directive inside a route
  block; putting it at the site level applies it to the dashboard's own
  requests too. Keep it inside `handle_path /ingest/*`.
- **Trap 3.** `slowapi` in the gateway needs the same `SlowAPIMiddleware` +
  exception-handler wiring `api/app/main.py` already has. Adding the decorator
  without the middleware silently does nothing.
- **Trap 4.** The gateway's rate-limit key function runs *before* the auth
  dependency in some slowapi configurations. Verify empirically which runs
  first rather than reasoning about it; if the limiter can't see the
  authenticated service, key on the raw `Authorization` header's SHA-256
  instead (never the header value itself, which would land in limiter state).

---

## Phase 16 — Multi-user auth and roles

### Goal

Replace the single hardcoded operator (`OPERATOR_USERNAME` /
`OPERATOR_PASSWORD_HASH` env vars, `api/app/auth/config.py`) with a `users`
table, two roles (`admin`, `member`), user management for admins, and password
change for everyone. Existing deployments keep working across the upgrade with
no manual step.

### Depends on

Phase 14 (admin endpoints exist and currently sit behind the single-operator
`require_auth`; this phase gives them a real authorisation model). Phase 13 for
the settings routes.

### Out of scope

- SSO, OAuth, SAML, magic links. Username and password.
- Per-service or per-incident permissions. Two roles, globally scoped.
- Email. No password-reset-by-email, no invitations by email. An admin
  creates a user and hands over the initial password out of band.
- Sessions/refresh tokens. The existing short-lived JWT model stands, including
  the deliberate decision that a browser refresh means logging in again.

### Schema changes

```sql
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,           -- argon2, via argon2-cffi (already a dep)
    role           TEXT NOT NULL DEFAULT 'member',
    disabled_at    TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT ck_users_role CHECK (role IN ('admin', 'member'))
);
```

Backfill in the same migration: if `OPERATOR_USERNAME` and
`OPERATOR_PASSWORD_HASH` are both present in the environment, insert that user
with `role='admin'`. If they are absent (fresh install), insert nothing — Phase
17's setup script or `just create-user` creates the first admin. This is what
makes the live deployment survive the upgrade untouched.

New role, following the established pattern:

```sql
CREATE ROLE "auth-service" LOGIN PASSWORD :auth_service_db_password;
GRANT USAGE ON SCHEMA public TO "auth-service";
GRANT SELECT, INSERT, UPDATE ON users TO "auth-service";
```

`api-reader` gets `SELECT` on `users` (to resolve a token's subject to a role
on read paths) but never `UPDATE`.

### API surface

```
POST   /auth/login          <- {"username", "password"}  -> {"access_token", "user": UserOut}
GET    /auth/me                                          -> UserOut
POST   /auth/change-password <- {"current_password", "new_password"} -> 204

GET    /users               (admin)  -> {"items": [UserOut, ...]}
POST   /users               (admin)  <- {"username", "password", "role"} -> 201 UserOut
PATCH  /users/{id}          (admin)  <- {"role"?, "disabled"?}          -> UserOut
POST   /users/{id}/reset-password (admin) <- {"new_password"}           -> 204
DELETE /users/{id}          (admin)  -> 204 (soft: disabled_at)
```

JWT payload gains `uid` (user id) and `role` alongside the existing `sub` and
`exp`. Keep `sub` as the username — dropping it would invalidate every token
issued before the deploy for no benefit.

`require_auth` returns an `AuthenticatedUser` dataclass instead of a bare
username string. Add `require_admin` as a thin wrapper. Swap the Phase 14
registry router and the new `/users` router onto `require_admin`; leave
`/incidents` on `require_auth`.

### Steps

1. Migration + backfill. Verify against a copy of the live database that the
   existing operator lands as an admin.
2. `api/app/auth/repository.py` (NEW) — user lookup, creation, password
   update, `last_login_at`. Uses the `auth-service` engine.
3. Rewrite `api/app/auth/security.py::verify_credentials` to look the user up
   in the database. **Keep the timing-attack defence**: on an unknown username,
   still run `PasswordHasher.verify` against a fixed dummy hash so a wrong
   username and a wrong password cost the same. The current code does this
   deliberately and it is easy to drop while refactoring.
4. Also keep the deliberate split between the specific failure reason (logged,
   structured, per `app/auth/router.py`) and the generic client-facing message.
   Add `disabled` as a third internal reason with the same generic response.
5. Rate-limit `POST /auth/login` with the existing `slowapi` limiter —
   `10/minute` keyed on client IP. There is no rate limit on login today; a
   multi-user system with real passwords needs one.
6. Argon2 parameters: use `argon2-cffi`'s defaults, as the current code does.
   Do not hand-tune them.
7. Password policy: minimum 12 characters, rejected if identical to the
   username. Nothing more — complexity rules make passwords worse, and this
   codebase should not pretend otherwise in a comment either.
8. `api/scripts/create_user.py` (NEW) + `just create-user` — prompts for
   username/password/role, writes the row. This is the only way to create the
   *first* admin, and it deliberately runs on the host rather than being a
   public bootstrap endpoint, so there is no window in which an unauthenticated
   endpoint can create an admin.
9. Frontend: user menu in `Nav.tsx` (username, role, change password, log out),
   `/settings/users` admin route, and hide admin-only nav items for members.
   Hiding is UX only — every admin route is enforced server-side, and a test
   must prove a member's token gets 403 from `POST /services`.
10. `OPERATOR_USERNAME` / `OPERATOR_PASSWORD_HASH` become optional everywhere:
    `api/app/auth/config.py` stops reading them at import time (they are
    migration-time inputs now), `.github/workflows/ci-cd.yml` can drop the
    dummy values from both the `pytest (api)` and the OpenAPI-dump steps, and
    `infra/.env.prod.example` marks them "first-install bootstrap only."
    Removing the import-time read is what unblocks the CI simplification —
    make sure `api/tests/conftest.py` still works without them.

### Acceptance criteria

- After deploy, the existing operator logs in with their existing password and
  lands with `role: admin`.
- An admin creates a member; the member logs in, sees incidents, and receives
  403 (not 401, not 500) from `POST /services` and from `GET /users`.
- A disabled user's existing token stops working within its remaining lifetime
  — i.e. `require_auth` re-checks `disabled_at`, it does not trust the token
  alone. Say so explicitly in a comment; it is a deliberate extra read.
- Password change invalidates nothing (short-lived tokens make revocation
  unnecessary) — but document that, don't leave it ambiguous.
- 11 failed logins in a minute from one IP return 429.
- CI passes without `OPERATOR_*` dummy env vars.

### Tests

- `api/tests/test_auth.py` — EDIT. It currently substitutes its own hash
  against `OPERATOR_PASSWORD_HASH`; rewrite against the DB fixture.
- `api/tests/test_users_api.py` — NEW. Admin CRUD, member 403s, self-service
  password change, disabled-user rejection, username uniqueness.
- A timing-parity test is not worth writing (it will be flaky in CI). Assert
  instead that the unknown-username path calls the verifier — a structural
  test of the defence, not a statistical one.

### Rollback

The migration's `downgrade()` drops `users` and the `auth-service` role. As
long as `OPERATOR_*` remain in `infra/.env.prod` (do not remove them from the
live VM in this phase — that is Phase 20 cleanup), reverting the image restores
single-operator auth immediately.

### Known traps

- **Trap 1.** `infra/.env.prod`'s argon2 hash is `$$`-escaped for Docker
  Compose's interpolation. When the migration reads `OPERATOR_PASSWORD_HASH`
  from the environment it receives the *un*escaped value (Compose un-escapes on
  injection) — verify this on the VM before trusting the backfill, because a
  double-escaped hash backfills a user who can never log in, and the failure
  looks exactly like a wrong password.
- **Trap 2.** `require_auth` is applied as a router-level dependency in
  `api/app/main.py` (`include_router(..., dependencies=[Depends(require_auth)])`).
  Changing its return type doesn't automatically make the value available to
  handlers — handlers that need the user must declare
  `user: AuthenticatedUser = Depends(require_auth)` themselves. FastAPI caches
  the dependency per request, so this costs nothing.
- **Trap 3.** Adding a DB read to `require_auth` puts a query on *every*
  authenticated request. Cache the user by id in-process with a short TTL
  (30s), and make sure the disabled-user acceptance criterion is written
  against that TTL rather than "instantly."

---

## Phase 17 — One-command setup and local quickstart

### Goal

Getting this deployment running took roughly ten hand-generated secrets, a
hand-built argon2 hash, manual VM provisioning, and manual DNS/security-group/
GitHub-secret wiring. After this phase: `git clone`, one command, a working
local Culprit with demo data and a visible incident inside five minutes; and a
second documented command for a real VM install that generates every secret
itself.

### Depends on

Phases 14 and 16. The script generates a service registry and an admin user; it
cannot do either before those exist.

### Out of scope

- Kubernetes, Helm, Terraform, or any cloud-provider automation. Docker Compose
  on one host is the deployment model.
- A hosted/managed offering.
- Automatic DNS or TLS for the local quickstart — localhost over plain HTTP,
  which Caddy already handles.

### Files touched

| Path | Action |
| --- | --- |
| `scripts/bootstrap_env.py` | NEW — generates `infra/.env.prod` |
| `infra/docker-compose.quickstart.yml` | NEW — local, no domain, includes demo profile |
| `demo-services/Dockerfile` | NEW — demo services have no image today |
| `justfile` | EDIT — `just quickstart`, `just quickstart-down`, `just bootstrap-env` |
| `README.md` | EDIT — currently 6 bytes; becomes the actual front door |
| `docs/INSTALL.md` | NEW — the real-VM path |
| `infra/.env.prod.example` | EDIT — `signalstack` → `culprit` defaults; see Trap 2 |
| `infra/deploy.sh` | EDIT — clearer failure when `.env.prod` is missing |

### `scripts/bootstrap_env.py`

Runs on the target machine, never in CI. Behaviour:

1. Refuses to overwrite an existing `infra/.env.prod` without `--force`.
2. Generates every password with `secrets.token_urlsafe(32)`: `POSTGRES_PASSWORD`,
   `INGESTION_WRITER_PASSWORD`, `API_READER_PASSWORD`,
   `INGEST_GATEWAY_DB_PASSWORD`, `ANOMALY_DETECTOR_DB_PASSWORD`,
   `CORRELATION_ENGINE_DB_PASSWORD`, `ROOT_CAUSE_WRITER_DB_PASSWORD`,
   `REGISTRY_ADMIN_DB_PASSWORD`, `AUTH_SERVICE_DB_PASSWORD`, `JWT_SECRET_KEY`.
3. Composes every `*_DATABASE_URL` from those, so they cannot drift from the
   role passwords by hand-editing one and not the other — the most tedious and
   error-prone part of the original setup.
4. **Escapes `$` as `$$` automatically** on every generated value. This is the
   footgun that already corrupted an argon2 hash during Phase 11 and it should
   never be a human's job again. `token_urlsafe` output contains no `$`, but
   the escaping must be applied unconditionally so it also covers any value the
   user supplies.
5. Prompts for `DOMAIN` (or `--domain`), `LLM_PROVIDER`, and the relevant API
   key (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`) plus `VOYAGE_API_KEY`, and
   states plainly that RAG root-cause narratives do not work without the
   embedding key.
6. Writes the file `0600`, prints a summary of what was generated with no
   secret values in it, and prints the exact next commands.
7. `--local` mode: `DOMAIN=localhost`, `IMAGE_REGISTRY` pointing at locally
   built images, no LLM keys required — degrading to "no narrative generated"
   rather than failing.

### `infra/docker-compose.quickstart.yml`

Differences from `docker-compose.prod.yml`:

- Builds from local Dockerfiles instead of pulling from `ghcr.io`, so it works
  before any images are published and on a machine with no registry access.
- `DOMAIN=localhost` — Caddy serves plain HTTP locally.
- A `demo` Compose profile containing `order-service`, `inventory-service`,
  `payments-service`, and the load generator, all built from the new
  `demo-services/Dockerfile` and pointed at `ingest-gateway` over the compose
  network. `docker compose --profile demo up` starts them; without the flag,
  they don't run. Production compose still has no demo services, on purpose.
- A one-shot `bootstrap` service that runs migrations, then
  `apply_services.py` against a `demo-services.yaml` (registering the three
  demo services and their edges and printing their generated keys), then
  `create_user.py` with credentials from the environment.

`just quickstart` sequences: `bootstrap_env.py --local` → build → up →
`--profile demo up` → print the login URL and credentials → print "an incident
should appear within about two minutes; run `just demo-fault latency
inventory-service --delay-ms 800 --duration-s 30` to force one."

### `README.md`

The repository's front door and currently 6 bytes. It needs: one-paragraph
what-this-is, a screenshot, the five-minute quickstart, a link to
`docs/INSTALL.md` for the real deployment, a link to `docs/INSTRUMENTATION.md`
for pointing real services at it, an explicit statement of what this is *not*
(not a replacement for Datadog/Grafana; it correlates and explains, it does not
store or graph everything), the license, and a note that the repo is named
`View` while the product is named Culprit — that mismatch is intentional but
looks like a mistake to a stranger, which is a different problem from looking
like a mistake to its author.

### Acceptance criteria

- On a clean machine with only Docker and `just`: `git clone && just quickstart`
  produces a working dashboard at `http://localhost` with login credentials
  printed to the terminal, and a real correlated incident with a root-cause
  narrative within ~5 minutes (narrative requires an LLM key; without one, the
  incident still appears and the UI says why there's no narrative).
- `just quickstart` is idempotent — running it twice does not regenerate
  secrets, does not duplicate services, does not error.
- `scripts/bootstrap_env.py --domain example.com` produces an `infra/.env.prod`
  that `docker compose -f infra/docker-compose.prod.yml --env-file
  infra/.env.prod config` parses with no empty interpolations.
- `docs/INSTALL.md` is followable end to end by someone who has never seen the
  repo, on a fresh Oracle Cloud / Hetzner / DigitalOcean VM, including the
  security-group and DNS steps.
- No secret is ever printed by CI, and `bootstrap_env.py` has no code path that
  runs in a GitHub Actions job.

### Tests

- `api/tests/test_bootstrap_env.py` (or a top-level `tests/`) — generated
  values are `$`-escaped; refusal to overwrite without `--force`; every
  `*_DATABASE_URL` embeds the matching generated password; output file mode is
  `0600`.
- The quickstart itself is verified manually on a clean VM and the transcript
  pasted into the PR. There is no honest way to unit-test "a stranger can
  install this."

### Rollback

Purely additive — new files plus a README. Nothing in the live deployment
changes. `.env.prod.example`'s default *values* changing (Trap 2) affects only
fresh installs.

### Known traps

- **Trap 1.** `demo-services/` has no Dockerfile and its `pyproject.toml`
  depends on `culprit-shared` by path, so its build context must be the repo
  root — exactly like `api/` and `worker/`. This has already cost this project
  a CI debugging session once ("Distribution not found").
- **Trap 2.** `infra/.env.prod.example` still defaults `POSTGRES_USER`,
  `POSTGRES_DB`, and every `DATABASE_URL` to `signalstack`. Change these to
  `culprit` for fresh installs — but the *live* database is named
  `signalstack` and renaming it is a data migration, not a config edit. Do not
  change the live VM's values. Note the split in `docs/INSTALL.md`.
- **Trap 3.** The one-shot `bootstrap` service must not run on every
  `docker compose up`. Guard it: exit 0 immediately if a user row already
  exists.
- **Trap 4.** `just quickstart` printing an admin password to a terminal is
  acceptable for a local demo and is *not* acceptable for `docs/INSTALL.md`'s
  real-VM path, where the admin password must be prompted for. Keep the two
  paths visibly separate in the script, not distinguished by a flag buried in
  the middle.
- **Trap 5.** Voyage AI's free tier caps at 3 requests/minute, which is why
  `worker/scripts/seed_postmortems.py` sleeps 21 seconds between calls. A
  quickstart that seeds 8 postmortems therefore takes ~3 minutes on the
  embedding step alone. Either say so in the terminal output or seed a smaller
  subset for the quickstart. Silence here reads as a hang.

---

## Phase 18 — Postmortem write path

### Goal

RAG grounding is the product's actual differentiator, and today the corpus is
eight fixture postmortems loaded once by a script. A team can never add their
own. After this phase, a user can write a postmortem — from scratch or attached
to a real incident — and it becomes retrievable context for future incidents.

### Depends on

Phase 13 (routing), Phase 16 (authorship attribution and permissions).

### Out of scope

- **LLM-drafted postmortems.** Explicitly V2 in `CLAUDE.md` and it stays there.
  The human writes it; the machine embeds it.
- Markdown rendering beyond a plain textarea and a preview. No rich editor.
- Versioning or edit history.
- Importing from Notion/Confluence/Google Docs.

### Schema changes

`postmortems` already exists with `title`, `body`, `embedding`,
`incident_candidate_id`, `created_at`. Add:

```sql
ALTER TABLE postmortems ADD COLUMN author_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE postmortems ADD COLUMN updated_at TIMESTAMPTZ;
ALTER TABLE postmortems ADD COLUMN embedded_at TIMESTAMPTZ;
ALTER TABLE postmortems ADD COLUMN embedding_error TEXT;
```

`embedded_at` and `embedding_error` exist so the UI can distinguish "queued",
"embedded", and "failed with this reason" — `embedding IS NULL` alone cannot,
and a postmortem that silently never became retrievable is the worst possible
failure here because it looks like it worked.

New role:

```sql
CREATE ROLE "postmortem-writer" LOGIN PASSWORD :postmortem_writer_db_password;
GRANT USAGE ON SCHEMA public TO "postmortem-writer";
GRANT SELECT, INSERT, UPDATE, DELETE ON postmortems TO "postmortem-writer";
```

The API uses this role for the postmortems router only. `api-reader` stays
read-only; the worker's existing `root-cause-writer` keeps its own access for
writing embeddings.

### API surface

```
GET    /postmortems?limit=&offset=       -> paginated, body truncated in list view
POST   /postmortems <- {"title", "body", "incident_id"?}  -> 201 PostmortemOut
GET    /postmortems/{id}                 -> PostmortemOut
PATCH  /postmortems/{id} <- {"title"?, "body"?}           -> PostmortemOut
DELETE /postmortems/{id}                 -> 204
```

`POST` and `PATCH`-with-changed-body enqueue the arq job `embed_postmortem`
with the postmortem id, exactly as `POST /incidents/{id}/regenerate-root-cause`
enqueues `generate_root_cause_narrative` today. The API never calls Voyage
itself — LLM and embedding calls stay server-side in the worker
(`CLAUDE.md` tech stack: "LLM calls: server-side only, never client-side, so
usage can be metered later"), and the API process must not block on a
rate-limited third-party call.

`PostmortemOut` includes an `embedding_status` field of
`"pending" | "embedded" | "failed"`, derived from the three new columns. Do not
expose the raw 1024-float vector.

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_postmortem_write_path.py` | NEW |
| `api/app/db/models.py`, `worker/app/db.py` | EDIT — new columns, both sides |
| `api/app/postmortems/` (`router.py`, `schemas.py`, `service.py`, `config.py`) | NEW |
| `api/app/main.py` | EDIT — mount router, third engine |
| `worker/app/rag/embed_job.py` | NEW — `embed_postmortem(ctx, postmortem_id)` |
| `worker/app/main.py` | EDIT — register the job in `WorkerSettings.functions` |
| `frontend/src/routes/PostmortemEditor.tsx`, `PostmortemList.tsx` | NEW |
| `frontend/src/hooks/usePostmortems.ts` | NEW |
| `frontend/src/components/incident-detail/IncidentDetailPanel.tsx` | EDIT — "Write postmortem" |
| `frontend/src/components/incident-detail/Evidence.tsx` | EDIT — cited postmortems link to their page |
| `worker/scripts/seed_postmortems.py` | EDIT — set `embedded_at` too |

### Steps

1. Migration, both `db` definitions, `just check-schema-drift`.
2. `worker/app/rag/embed_job.py`: loads the row, calls `embed_document`
   (`app/rag/embeddings.py`), writes `embedding` + `embedded_at`, clears
   `embedding_error`. On failure, write the error string and re-raise so arq
   records the failure. Configure arq retries with backoff — Voyage's free tier
   returns `RateLimitError` at 3 requests/minute and a burst of postmortems
   *will* hit it. Do not copy `seed_postmortems.py`'s unconditional 21-second
   sleep into a live job path; that script's pacing is right for a one-off
   backfill and wrong for an interactive write.
3. This job lives in `app.rag` and must not import `app.anomaly` or
   `app.correlation` — `lint-imports` will catch it, but design it right first.
4. API router with the `postmortem-writer` engine. Enqueue on create and on
   body change; do not re-embed on a title-only edit — a postmortem's embedding
   is computed from `body` alone (`worker/scripts/seed_postmortems.py` calls
   `embed_document(seed.body)`; the *query* side embeds a rendered incident
   summary instead, via `app/rag/context.py::render_embedding_text`, and the two
   are deliberately asymmetric).
5. Frontend: list at `/postmortems`, editor at `/postmortems/new` and
   `/postmortems/:id`, plus `/incidents/:id/postmortem` which pre-fills the
   title and links the incident. Prefill the body with a skeleton matching the
   fixture structure (Summary / Timeline / Root cause / Resolution) — retrieval
   quality depends on the corpus having consistent shape, and the eight
   fixtures already establish that shape.
6. Surface `embedding_status` in the list and editor. "Pending" must be
   visible; "failed" must show the reason and offer a retry that re-enqueues.
7. `Evidence.tsx` currently renders citations as
   `{postmortem_id, postmortem_title, passage}` — make the title a link to
   `/postmortems/{id}`. This closes the loop: a user reads a narrative, follows
   the citation, and sees the postmortem their own team wrote.

### Acceptance criteria

- A user writes a postmortem; within a minute `embedding_status` is
  `"embedded"`.
- A newly written postmortem is retrieved as context for a subsequent incident
  — verify by writing one that closely describes a fault the injector can
  reproduce, triggering that fault, and confirming the postmortem appears in
  the new incident's `root_cause_evidence`.
- Voyage rate-limit failures produce `"failed"` with a readable reason and a
  working retry, not a silently unembedded row.
- Deleting a postmortem that an existing incident cites does not break that
  incident's detail view — `root_cause_evidence` is a JSONB snapshot, so the
  citation text survives; the *link* must degrade gracefully.
- `api-reader` still cannot write to `postmortems` (assert with a role-scoped
  connection in a test).

### Tests

- `api/tests/test_postmortems_api.py` — CRUD, validation, enqueue-on-create,
  no-enqueue on title-only edit, `embedding_status` derivation, api-reader
  cannot write.
- `worker/tests/test_embed_job.py` — success path writes `embedded_at`;
  failure path writes `embedding_error` and re-raises. Mock the Voyage client;
  `worker/tests/test_rag_providers.py` already establishes how this project
  mocks external LLM/embedding calls — follow it.

### Rollback

`downgrade()` drops the four columns and the role. The frontend routes 404
after an image revert, which is acceptable and now renders a real 404 page
(Phase 13). No existing data is lost.

### Known traps

- **Trap 1.** `postmortems.embedding` is `Vector(1024)` matching `voyage-4`'s
  default. Do not let a model change slip in with this phase — a different
  dimension is a schema change and a full re-embed of the corpus.
- **Trap 2.** `worker/app/rag/seed_postmortems.py` (the fixture module) and
  `worker/scripts/seed_postmortems.py` (the script) are different files with
  nearly the same name. The script deliberately never gets imported by the live
  job path. Keep it that way — the new `embed_job.py` imports neither.
- **Trap 3.** `retrieve_similar_postmortems` filters `embedding IS NOT NULL`,
  so a pending postmortem correctly can't be retrieved. Don't "fix" that by
  relaxing the filter.
- **Trap 4.** Adding a third engine to `api/app/main.py`'s lifespan means three
  connection pools in one process. Cap pool sizes explicitly
  (`create_async_engine(..., pool_size=5, max_overflow=5)`) — the VM is an
  Always Free shape and Postgres's default `max_connections` is not generous.

---

## Phase 19 — Topology inference from traces

### Goal

Replace hand-declared service dependencies with edges observed from real trace
data, proposed to an admin for confirmation. This is the most speculative phase
here and the only genuinely optional one — a hand-declared graph is a
legitimate permanent answer.

### Depends on

Phase 14 (there must be a registry to write inferred edges into) and Phase 15
(the ingest path must be public before real traces arrive).

### Out of scope

- **Automatically applying inferred edges.** Inference *proposes*; a human
  confirms. Silently changing what correlates is precisely the "wrong automated
  correlation" failure mode `CLAUDE.md` names as the thing that makes the
  product untrustworthy.
- Storing full spans. This project's own rule is not to keep high-volume raw
  data it doesn't need.
- Distributed-trace visualisation. Tempo/Jaeger exist and do this well.
- Latency-based dependency weighting.

### Approach — two options, in preference order

**Option A (preferred): attribute-based, no join.** Client spans emitted by an
OTel-instrumented service usually carry `peer.service` or, failing that,
`server.address` / `http.request.method` + `url.full`. For every span with
`kind == CLIENT` and a resolvable peer, record the directed edge
(`resource.service.name` → peer). No cross-service correlation needed, no span
storage, one pass in the gateway. Fails when peers are addressed by hostname
rather than logical service name — mitigate with an admin-editable
hostname→service alias map on the `services` row.

**Option B (fallback): parent-span join.** Store
`(trace_id, span_id, parent_span_id, service_name, start_time)` with short
retention (24h), and derive edges by joining a span's `parent_span_id` to a
span from a different service. Correct in more cases, but requires a real table
of spans and a periodic aggregation job.

Build Option A first. Only reach for B if A's edge coverage on real data is
poor — and measure that, don't assume it.

### Schema changes

```sql
CREATE TABLE observed_service_edges (
    from_service   TEXT NOT NULL,
    to_service     TEXT NOT NULL,
    observations   BIGINT NOT NULL DEFAULT 0,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    dismissed_at   TIMESTAMPTZ,
    PRIMARY KEY (from_service, to_service)
);
```

Names, not FKs to `services.id`: an edge can legitimately be observed pointing
at something not yet registered, and that is *useful* information ("you're
calling a service Culprit doesn't know about"), not an error to reject at
insert time.

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_observed_service_edges.py` | NEW |
| `api/app/db/models.py`, `worker/app/db.py` | EDIT |
| `api/app/ingest_gateway/otlp_decode.py` | EDIT — `decode_traces_request` |
| `api/app/ingest_gateway/main.py` | EDIT — `POST /v1/traces` |
| `api/app/ingest_gateway/streams.py` | EDIT — `TRACES_STREAM` (edges only) |
| `worker/app/consumer.py` | EDIT — drain the new stream, upsert edges |
| `api/app/registry/router.py` | EDIT — `GET /services/topology/suggestions`, accept/dismiss |
| `frontend/src/routes/SettingsServices.tsx` | EDIT — suggestions panel |
| `docs/INSTRUMENTATION.md` | EDIT — traces are now accepted, and what for |

### Steps

1. Extend `otlp_decode.py` with `decode_traces_request`, but have it emit
   **edge observations, not spans** — the decoded output is a list of
   `(from_service, to_service)` pairs. This is what keeps the "don't store
   high-volume raw data" rule intact: the volume reduction happens at the
   gateway, before anything is queued.
2. New Redis stream for edges. The consumer upserts into
   `observed_service_edges` with `observations = observations + 1` and
   `last_seen_at = now()`.
3. `GET /services/topology/suggestions` returns observed edges that are not
   already in `service_dependencies` and not dismissed, ordered by
   `observations` descending, each annotated with whether both endpoints are
   registered services.
4. `POST /services/topology/suggestions/accept` inserts into
   `service_dependencies`; `.../dismiss` sets `dismissed_at`.
5. Settings UI: a "Suggested dependencies" panel showing "`order-service` →
   `inventory-service`, seen 4,281 times since 3 August" with Accept and
   Dismiss. Nothing changes correlation until Accept is pressed.
6. Document in `docs/INSTRUMENTATION.md` that traces are now accepted, that
   they are used *only* for topology inference, and that they are not stored —
   a user needs to know Culprit is not a tracing backend before they point
   100% of their spans at it.

### Acceptance criteria

- With the three demo services running, the gateway observes and proposes
  order→inventory and order→payments, and does not propose
  inventory→payments (they have no direct relationship — this is the
  discriminating case).
- Accepting a suggestion changes correlation behaviour on the next tick.
- No table grows proportionally to span volume — `observed_service_edges` has
  at most one row per service pair.
- Correlation still works identically for anyone who never enables traces.

### Tests

- `api/tests/test_otlp_decode_traces.py` — a recorded protobuf payload decodes
  to the expected edges; spans with no resolvable peer produce none.
- `worker/tests/test_edge_upsert.py` — repeated observations increment rather
  than duplicate.
- `worker/tests/test_correlation_graph.py` — confirm accepted-edge behaviour
  flows through the Phase 14 adjacency parameter with no change to `graph.py`.

### Rollback

Traces are additive and opt-in on the client side. Revert the image; the
gateway stops accepting `/v1/traces` and clients log export errors but continue
sending metrics and logs normally. Confirm that claim before merging.

### Known traps

- **Trap 1.** `raw_events.event_type` has a check constraint of
  `('metric', 'log')`. Traces must not be written there at all under this
  design — if anything ever tries, that constraint will reject it, which is the
  correct outcome and a signal the design was violated.
- **Trap 2.** Accepting an inferred edge whose target isn't a registered
  service must either auto-register it or refuse clearly. Silently creating a
  half-registered service with no API key is the worst of the three options.
- **Trap 3.** Trace volume is far higher than metric volume. The gateway must
  reduce to edges *before* pushing to Redis, and the ingest rate limit from
  Phase 15 must account for traces being a much chattier stream.

---

## Phase 20 — Release engineering, docs, and the upgrade path

### Goal

Everything that turns "a repo you can run" into "a thing you can depend on":
public versioned images, an upgrade path that doesn't lose data, backups,
honest documentation of limits, and a license.

### Depends on

All of the above.

### Out of scope

- A marketing site.
- A plugin/extension system.
- Telemetry-about-Culprit phoning home. If usage analytics are ever wanted,
  that is a separate decision with a separate consent conversation.

### Steps

1. **Versioning.** Adopt semver tags. `.github/workflows/ci-cd.yml` currently
   pushes `:latest` and `:${{ github.sha }}`; add `:vX.Y.Z` on git tags.
   `infra/.env.prod.example` should recommend pinning `IMAGE_TAG` to a version,
   not `latest` — a third party silently getting a new major version on
   restart is a bad default even though it is convenient for the author's own
   VM.
2. **Make the `ghcr.io` packages public.** They default to private under
   `GITHUB_TOKEN`, which is exactly why this deployment needed a one-time
   `docker login` with a classic PAT on the VM. A downloadable product cannot
   ask that of its users. Verify from a machine with no GitHub credentials.
3. **Upgrade path.** `docs/UPGRADING.md`: always `docker compose pull` then
   `alembic upgrade head` then restart (the order `infra/deploy.sh` already
   encodes and the reason it encodes it), what to back up first, and a
   documented statement that downgrades are supported one version back and no
   further.
4. **Backups.** A `scripts/backup.sh` doing `pg_dump` of the compose
   `postgres` volume, plus documentation of what is and isn't worth restoring
   (`raw_events` is voluminous and mostly disposable; `postmortems`,
   `services`, `users`, and `incident_candidates` are the corpus that actually
   matters and cannot be regenerated).
5. **License.** Add one. This affects whether anyone can use it at all and it
   is currently unstated.
6. **`docs/LIMITS.md` — honest constraints.** Roughly how many services and how
   many metrics per service one Always-Free-shaped VM handles; that anomaly
   scoring needs history before it flags anything; that Redis Streams is the
   ingestion transport and Kafka is deliberately not (with the throughput
   implication stated, not hidden); that the LLM narrative is a hypothesis,
   grounded but not authoritative. A product that states its limits is more
   trustworthy than one that implies it has none.
7. **Name reconciliation.** The repo is `View`, the product is Culprit, the
   images live at `ghcr.io/josh-heath123/view/*`. `CLAUDE.md` records this
   mismatch as intentional-by-inertia, and it is harmless internally — but a
   stranger cloning `view` to run `culprit` will assume they cloned the wrong
   thing. Decide here, once, with the decision written down: rename the repo
   (GitHub redirects the old URL, but every image path changes and the VM's
   pinned tags need updating), or keep it and explain it in the README's first
   paragraph. Do not leave it undecided a third time.
8. **`CLAUDE.md` and `docs/IMPLEMENTATION_PLAN.md` maintenance.** The
   implementation plan's title still says "SignalStack" and its Phase 3 and
   Phase 6 scope notes ("three fixed keys", "no UI for writing postmortems")
   are now false. Mark them superseded with a pointer to this document rather
   than editing history — and update `CLAUDE.md`'s status line, which its own
   philosophy says is worse stale than absent.

### Acceptance criteria

- A machine with no GitHub account can `docker compose pull` every image.
- `docs/INSTALL.md` followed literally on a fresh VM produces a working install
  with no step requiring the repo author.
- Upgrading from the previous release tag to the current one preserves all
  incidents, postmortems, services, and users, verified on a restored backup
  rather than asserted.
- `README.md`, `docs/INSTALL.md`, `docs/INSTRUMENTATION.md`, `docs/UPGRADING.md`,
  `docs/LIMITS.md`, and a license all exist and are mutually consistent.

---

## Appendix A — Environment variable changes across the programme

| Variable | Phase | Change |
| --- | --- | --- |
| `ORDER_SERVICE_API_KEY`, `INVENTORY_SERVICE_API_KEY`, `PAYMENTS_SERVICE_API_KEY` | 14 | Become optional; demo-only |
| `REGISTRY_ADMIN_DB_PASSWORD`, `REGISTRY_ADMIN_DATABASE_URL` | 14 | NEW |
| `INGEST_RATE_LIMIT`, `INGEST_MAX_BODY_BYTES` | 15 | NEW |
| `AUTH_SERVICE_DB_PASSWORD`, `AUTH_SERVICE_DATABASE_URL` | 16 | NEW |
| `OPERATOR_USERNAME`, `OPERATOR_PASSWORD_HASH` | 16 | Become first-install bootstrap only; no longer read at import time |
| `POSTMORTEM_WRITER_DB_PASSWORD`, `POSTMORTEM_WRITER_DATABASE_URL` | 18 | NEW |
| `POSTGRES_USER` / `POSTGRES_DB` defaults | 17 | `signalstack` → `culprit` **for fresh installs only** |
| `IMAGE_TAG` | 20 | Recommendation changes from `latest` to a pinned version |

Every new `*_DATABASE_URL` is generated by `scripts/bootstrap_env.py` (Phase 17)
from its matching password, so the two cannot drift.

## Appendix B — Deliberately not in this plan

Recorded so they get flagged rather than quietly built:

- Kafka, or any ingestion transport other than Redis Streams.
- Trained/learned anomaly models, or per-service learned baselines.
- Slack, PagerDuty, or any alerting integration.
- LLM-drafted postmortems.
- Multi-tenancy (one install serves one team).
- SSO/OAuth/SAML.
- A tracing UI, log search, or metric graphing. Culprit correlates and
  explains; it is not an observability platform and should stop short of
  pretending to be one.
- Any LLM involvement in anomaly detection or correlation, in any phase, for
  any reason.
