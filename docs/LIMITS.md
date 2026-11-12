# Limits

Honest constraints, not hidden ones — a product that states its limits is
more trustworthy than one that implies it has none. These are the ones
worth knowing before you depend on this for something real.

## Scale

This project targets one self-hosted VM on the shape of an Oracle Cloud
Always Free instance (2 OCPU / 11 GB, `docs/ARCHITECTURE.md`'s Production
deployment section) — not a cluster, not autoscaling. Rough guidance, not a
guarantee, since actual headroom depends heavily on traffic shape:

- **A handful of services** (the demo ships three) — dozens, not hundreds.
  Every registered service's metrics get their own persistent scorer
  state in Redis (`worker/app/anomaly/`), and every service is a lane in
  the dashboard timeline; neither is designed to page or paginate at
  large counts.
- **Ingestion defaults to `INGEST_RATE_LIMIT=600/minute` per service**
  (`infra/.env.prod.example`) — generous for a service exporting metrics
  every 10-30s, a hard ceiling if you point something chattier at it.
  Raise it if you need to, but that's directly more load on the single
  shared Postgres instance everything else also depends on.
- **One Postgres instance, fourteen least-privilege roles sharing it.**
  `api` opens a pool per role it uses (`api-reader`, `registry-admin`,
  `auth-service`, `postmortem-writer`, `fact-writer`, `capture-writer`,
  `probe-writer`, `investigation-writer`), the ingest gateway one
  (`ingest-gateway`), `worker` five (`ingestion-writer`, `anomaly-detector`,
  `probe-writer`, and `correlation-engine` and `root-cause-writer` for the
  change-link and embedding jobs, which kept those roles when the jobs they
  were named after were removed), and `mcp_server` adds `mcp-reader` if you
  run it. More services and more worker cron activity means more concurrent
  connections against Postgres's own `max_connections` (100 by default,
  unraised here). This is the first thing to look at if connections start
  getting refused under real load.
- **`raw_events` is designed to be pruned, not to grow forever** — see
  `api/migrations/versions/e2cab79bcc93_raw_events_compression_and_retention.py`
  for the compression/retention policy already in place: 1-day chunks,
  compressed after **7 days**, dropped after **30**. It's still the
  highest-volume table in the system by a wide margin; don't be surprised
  by its size relative to everything else.
- **`readings` keeps 90 days, not 30.** The evidence table added in Phase
  26 uses 1-day chunks, compression after 7 days and retention of **90
  days** — deliberately longer than `raw_events`, because a reading is the
  evidence behind a verdict rather than raw telemetry. It stays empty until
  Phase 31 puts probes behind it.

## Anomaly detection needs history

The z-score scorer (`worker/app/anomaly/scorer.py`) needs
**`MIN_OBSERVATIONS = 30`** data points for a given `(service, metric)`
pair before it will flag anything at all — a service that's been
reporting for a minute will correctly show nothing, not a broken install.
There is no learned baseline across restarts beyond what's persisted in
Redis (`MetricScorer.to_dict()`/`from_dict()`); a Redis wipe means every
scorer starts its warm-up over.

## Redis Streams, not Kafka — deliberately

Ingestion transport is Redis Streams (`CLAUDE.md`'s scope
ceilings), not Kafka. This is the right choice for the scale this project
targets and the wrong one if you need durable multi-consumer-group
fan-out, partition-level ordering guarantees at real throughput, or
retention measured in weeks rather than however long the stream stays
unacked. If ingestion volume ever outgrows what Redis Streams can hold,
that's a real architecture change, not a config tweak — see
`docs/SELF_HOSTED_PLAN.md`'s own invariants for why this wasn't reached
for prematurely.

## Topology inference sees only what you instrument

Phase 19's trace-based dependency suggestions (`docs/INSTRUMENTATION.md`)
only produce an edge for a `CLIENT`-kind span carrying a resolvable
`peer.service` or `server.address` attribute. Context propagation alone
(a downstream span nesting under an upstream caller's span) isn't
enough — if your instrumentation only propagates trace context without
creating its own `CLIENT` spans, topology inference will silently
observe nothing, correctly, not incorrectly.

## Incidents are history, and nothing writes them any more

Phase 32 removed the engine that grouped anomalies into incidents and the
job that asked an LLM to write a root-cause narrative over each one
(`docs/DIAGNOSTIC_PLAN.md` D5). The incident tables are kept, read-only: no
role can insert or update `incident_candidates` or `incident_anomalies`, and
the dashboard's timeline shows what that engine concluded before it was
retired, labelled as history. Nothing was migrated out of them and nothing
new arrives in them. An incident still marked `pending` will stay that way —
there is no job left to write its narrative, and the "Regenerate" button is
gone with it.

Diagnoses are investigations now: `culprit diagnose`, run where the
environment is, posted to `POST /investigations`. No step of that path calls
a model, so it is complete with `LLM_PROVIDER=none` and no keys at all. The
optional narrator (Phase 35 part 2, "Narration" below) writes prose beside a
stored investigation and changes nothing in it.

The anomaly scorer still runs and still writes `anomalies` and impedance
readings; it is the grouping into incidents that stopped.

## Postmortem search has no relevance floor

Postmortems, architecture decisions and change records are still embedded
when written, and the MCP server's search returns the `top_k` most similar
(5 by default, at most 50) by embedding distance, with no relevance floor.
With a small corpus, or one whose postmortems don't share a consistent
structure, "most similar" can still mean "not very similar at all." Since
Phase 32 nothing in the worker retrieves from the corpus — the narrative job
that did is gone. Voyage's free tier also caps at 3 requests/minute
(`docs/SELF_HOSTED_PLAN.md` Phase 18) — a burst of postmortem writes
degrades to a visible "failed, retry" state rather than hanging, but it does
mean a burst takes real wall-clock time to fully embed.

## A revoked ingest key keeps working for up to 10 seconds

`api/app/ingest_gateway/auth.py` serves an in-memory map of active API key
hashes and refreshes it from the database at most once every
**`_MIN_RELOAD_INTERVAL_S = 10` seconds**, because the alternative — a
database round trip per request — is a throughput cliff on a
telemetry-ingestion hot path. Revoking or disabling a key therefore takes
effect within 10 seconds, not instantly.

Before Phase 26 it could take *forever*: the refresh fired only on a
lookup miss, and a revoked key still matches the stale map, so it always
hit and never triggered the refresh that would have removed it. If you
have revoked a key on an older deployment and want certainty rather than a
10-second window, restarting the gateway still clears the map outright.

**While Postgres is unreachable, the window is as long as the outage.** A
failed refresh is logged and swallowed rather than failing the request,
so ingest keeps working from the last map it successfully loaded. That is
the deliberate trade: the alternative is that a database blip stops
telemetry from every correctly-authenticated service. A key revoked
during an outage starts being rejected once the database comes back.

## Route matching erases parameter names, and will not guess at them

Comparing what two sources say about the same HTTP route only works if both
produce the same subject URI, so `shared/culprit_model/canonical.py`
normalises route templates before anything is compared. Four consequences
worth knowing:

- **Parameter names are erased.** `/orders/{id}`, `/orders/:orderId`,
  `/orders/<int:pk>` and `^orders/(?P<pk>[0-9]+)/$` all become
  `/orders/{}`. This is what lets a Django view and an OpenAPI document
  describe the same route; the cost is that two genuinely different routes
  with identical shapes would collide, which cannot happen within one
  component because a router carrying both would itself be ambiguous.
- **A concrete path is never guessed to be a template.** `/orders/12345`
  stays `/orders/12345`. Treating a numeric segment as an id is how
  `/orders/count` silently merges with `/orders/{}`, so route templates
  have to come from the server, not from a URL that happened to be seen.
- **A nested regex group is left alone.** `(?P<a>(x|y))` in a Django
  `re_path` does not normalise. The result is a subject that will not match
  its counterpart from another source — a missing comparison rather than a
  wrong one, but a gap all the same.
- **A quoted mixed-case Postgres identifier is not round-trippable.**
  Schema subjects lower-case identifiers to match Postgres's own folding of
  unquoted names. If your schema uses `"Orders"` with quotes, its subject
  will still say `orders`.

## An unparseable telemetry message is quarantined, not retried forever

If the stream consumer cannot parse an entry — truncated JSON, a payload
shape that no longer validates — it copies the entry to a Redis stream
called **`dead-letter`** and acknowledges the original, rather than failing
the batch. Before Phase 26 that single message wedged the drain
permanently, and every valid message behind it stopped arriving with no
error anywhere a user would see.

Three things this means in practice:

- The `dead-letter` stream is capped at about **10,000 entries**
  (approximate trimming, so the real figure sits a little above that) and
  older entries are dropped past it.
- Nothing surfaces it in the dashboard. `XLEN dead-letter` in `redis-cli`
  is how you find out whether anything has been quarantined; the drain
  job also reports a `quarantined` count in its result and trace span.
- **If every entry in a batch fails to parse, nothing is quarantined and
  nothing is acked** — the drain raises and stalls instead. A whole batch
  failing is not a corrupt message, it is systemic (a version skew
  between the gateway and the worker, say), and quarantining real
  telemetry into a 10,000-entry ring buffer would destroy it within
  minutes at any real ingest rate. Stalling is recoverable: fix the cause
  and the backlog drains. So a stalled drain with a loud, repeating parse
  error in the worker log is the intended behaviour for that case, not a
  regression.

## A historic narrative's citations were checked for existence, not relevance

Incident narratives written before Phase 32 had every citation verified
before it was stored: the quoted passage had to appear in the postmortem it
was attributed to. That shows a citation is genuine, not that it is
relevant, or that the narrative around it was right. They are shown as they
were stored.

## Incident-to-change linking is a 30-minute window and a substring match

`worker/app/memory/link_job.py` links an incident to a recent AI change
record when one plausibly preceded it. Both halves of that judgement are
deliberately crude, fixed, and not configurable:

- **The window is 30 minutes** (`AI_CHANGE_LOOKBACK`). A change links only
  if it was committed at or before the incident opened, and no more than 30
  minutes before it. A regression that takes an hour to surface will not be
  linked.
- **The file match is a plain substring test.** A change counts as related
  to `order-service` if any changed file path contains `order_service`
  (hyphens normalise to underscores, since file paths are the haystack). A
  service whose name does not appear in its own file paths will never
  match; a path that happens to contain another service's name will.
- The job re-scans incidents opened in the last hour
  (`INCIDENT_RESCAN_WINDOW`) on every tick, so a delayed tick does not lose
  a link.

The bias is deliberate: a heuristic that occasionally misses a real
correlation is a much smaller problem than one that confidently links
unrelated things. Treat a link as a lead, not as a cause.

Since Phase 32 nothing creates incidents, so the job still runs and finds
nothing new to link; existing links are kept. Linking a change record to an
investigation is not built.

## Every service now refuses to start without its database URL

As of Phase 26, `api` and `worker` fail at import — with a message naming
the missing variable — if any `*_DATABASE_URL` is unset. They used to fall
back to a `<role>-dev-password` connection string committed to this
repository, which turned a missing variable into a confusing connection
failure much later instead of a refusal to start.

If you are upgrading and your `.env.prod` predates the `registry-admin`,
`auth-service`, `postmortem-writer` or `mcp-reader` roles, the container
will now crash on boot rather than start in a broken state. Compare against
`infra/.env.prod.example`, which lists every variable, or regenerate with
`just bootstrap-env`. See `docs/UPGRADING.md`.

**The local quickstart hits the same wall, and re-running it does not
help.** `just quickstart` generates `infra/.env.prod` only if the file does
not exist, and `just quickstart-down` keeps it (and the database volume).
So a quickstart first run before Phase 28 keeps an `.env.prod` without the
`fact-writer`, `capture-writer` and `probe-writer` passwords or
`CULPRIT_PROJECT_TOKEN`. On the next run the bootstrap migration aborts
with `FACT_WRITER_DB_PASSWORD must be set in the environment to run this
migration`, and `api` and `worker` restart in a loop. Found running Phase
31.1 on a machine that had last run the quickstart in September. Add the
missing lines by hand, with names from `infra/.env.prod.example`. Do not
regenerate the file with `--force` while the volume still exists: the
Postgres superuser password is fixed when the volume is first created, so
a regenerated file no longer matches it. Removing the volume and the file
together starts clean, at the cost of the local data.

**`infra/.env.prod` holds every secret in plain text, on purpose** — Docker
Compose reads nothing else — so `just bootstrap-env` creates it readable by
your user alone (`0600`) from the first byte, and anyone who can read it
anyway (root, a backup, a copy) has every credential.

## A config value cannot be stored without naming an explicit grant

`configured_facts` — the table that holds what an environment is actually
set up to do — records the *shape* of a config key, not its contents.
`value_shape` carries type, length class and format class (e.g.
`{"type": "string", "length_class": "medium", "format": "dsn",
"present": true}`), and `value` is NULL unless `grant_ref` names the
per-key grant that permitted storing the literal. A database CHECK
constraint (`ck_configured_facts_value_requires_grant`) enforces that, so
a carelessly written extractor is rejected by Postgres rather than trusted
to behave.

What this costs you: **a divergence over a config key can tell you the two
environments differ, and how the shape differs, without being able to show
you the two values.** That is the intended trade. This is the one table
whose whole purpose is being safe to attach to a bug report, and a
free-form value column would have become a `DATABASE_URL` sitting in
Postgres the first time an extractor was written in a hurry.

Three consequences worth knowing before you depend on it:

- **~~The constraint covers `value`, not the whole table.~~ Closed in
  Phase 28.** `value_shape` was free-form JSONB, and
  `{"type": "url", "sample": "postgresql://u:hunter2@db/orders"}` inserted
  happily with no grant — the column the design steers extractors
  *towards* was the unconstrained one. It is now a closed type:
  `culprit_model.ValueShape` has exactly four fields (`type`,
  `length_class`, `format`, `present`), every one a closed enum or a
  bool, so there is no field a string can be put in. A CHECK constraint
  (`ck_configured_facts_value_shape_is_closed`) matches the key set
  exactly — not a minimum, so an extra key alongside the four is refused
  too. **The type is the primary guarantee and the constraint is defence
  in depth**, because the artefact this promise is really about is a
  capture bundle serialised to a file and attached to a bug report, which
  never reaches Postgres at all.
- **One deliberate exception: a `bool`.** A fact about a config key may
  carry `true`/`false` without a grant, so an extractor can assert things
  *about* a key that are not its value — `read_by: true`, `required:
  true`. A bool has two inhabitants and cannot carry a credential. Every
  other type needs a grant, numbers included: a numeric API key is a real
  thing.
- **The shape is coarse, and that costs you real findings.** Phase 30
  added `scheme` (docs/HANDOFF.md §2, resolving Q7), from a closed list —
  `postgresql`, `mysql`, `redis`, `rediss`, `https`, … and `other` — so a
  `DATABASE_URL` pointing at `postgresql://` in staging and `mysql://` in
  production is now a visible difference. A hostname change, a port
  change, a different database name on the same server, or any two
  secrets of similar length still have the *same shape*. Shape comparison
  catches set versus unset, empty versus populated, a different kind of
  value, a different scheme and a credential baked into a URL — not
  "pointing at a different host". An unrecognised scheme is `other`, so
  two different unrecognised schemes compare equal.
- **Length is compared only as empty-or-not.** Two environments' URLs
  differ in length because they name different hosts, so "short against
  medium" is never a finding. A key that is set but blank against one
  that is populated is.
- **A shape from before Phase 30 has no `scheme`**, and compares equal to
  any scheme — "did not say" is not "disagrees". Stored rows are not
  backfilled. An extractor emitting `scheme` cannot be read by a
  pre-Phase-30 `culprit` binary (it refuses the unknown field and drops
  that extractor's whole answer); neither side has been released, so no
  published pair is affected, but keep the CLI and the extractors on the
  same release.
- **`intent_facts` carries the same three constraints now.** Phase 28
  gave it `value_shape` and `grant_ref` too, because an INTENT extractor
  reading `.env.example` or an `os.environ.get("PORT", "8000")` default
  genuinely has a shape to report about what a key is *supposed* to
  hold — 32 of the 64 config facts a capture of this repository produces
  are exactly that. Without the columns they were accepted and stored
  with the shape discarded while the response reported them saved. That
  matters more than the `configured_facts` version: `intent_facts` is the
  table an unattended CI credential can actually INSERT into today.
- **A `grant_ref` is checked against the capture's own grants — on
  `POST /captures` only.** Phase 30 made every CONFIGURED fact name the
  grant that permitted reading it (`db.metadata.read` for a column list,
  `config.read.values:orders-api/LOG_LEVEL` for a value), and `POST
  /captures` refuses a fact whose grant the capture does not list, or a
  config value whose grant is not its own key's. That is checked against
  the grant list *in the capture*, which the capture's signature covers
  when there is one; nothing checks that list against the `culprit.yaml`
  the capture claims to have run under. `intent_facts` (`POST
  /facts/captures`) has no grant list to check against, so there
  `grant_ref` is still only required to be non-blank. Phase 28 closed the
  cheapest half of that — a blank or whitespace-only `grant_ref` is now
  refused by both the type and a second CHECK
  (`ck_configured_facts_grant_ref_not_blank`) — but any *non-blank*
  string still satisfies it. Today the column is the structural place for
  that check, not the check.
- **Downgrading past this migration loses data, one half of it loudly and
  one half silently.** `downgrade()` drops `grant_ref`, so a granted
  literal value that goes down and comes back up is indistinguishable from
  an ungranted one, and the CHECK refuses to be recreated until you
  resolve those rows — a loud failure with a remedy, which beats silently
  deleting operator data or silently keeping a value whose grant no longer
  exists. It also drops `value_shape`, and *that* loss is silent: after
  Phase 27 `value_shape` is the payload of a CONFIGURED fact, so a down/up
  cycle succeeds and leaves contentless facts behind. Back up first
  (`scripts/backup.sh`). Rows with no stored value round-trip cleanly.

`configured_facts` is written for the first time in Phase 30, by `POST
/captures`. Downgrading past its migration (e4c1b7a9d2f0) strips every
stored `scheme` from both fact tables and drops the captures' grant sets
and refusal lists, silently — back up first.

## `culprit.yaml` export is a canonical form, not your file back

`just apply-model <file>` then `just apply-model --export` gives you a
manifest describing the same system — but not, in general, the same bytes.
Two of the three normalisations below are unavoidable for anything backed
by a database; the third is a design choice, and it is marked as such.

- **Comments are gone.** YAML comments live in the parser, not the
  document, so nothing can carry them through a database round trip. If
  your `culprit.yaml` explains *why* an edge is on the request path, that
  explanation does not survive an export. Keep the file you wrote under
  version control and treat `--export` as a way to see what the model
  currently holds, not as a replacement for it.
- **Fields left at their default are omitted.** A connection written as
  `kind: http` comes back with no `kind:` at all, because `http` is the
  default; the same goes for `kind: service` on a component and
  `criticality: unknown` on a connection. The model is identical; the text
  is shorter.
- **Each component's connections are sorted** by target then kind. This
  one is a *choice*, not a necessity: component order is preserved,
  because `apply` records each component's position in the file as its
  `sort_order`, and the same mechanism was available for connections and
  was not used (`connections` has no `sort_order` column). So the
  top-level shape of your document survives while the edge lists within
  it may be reordered. Giving connections an authored order is a real
  option if the reordering turns out to matter in review.

**Export omits edges the manifest does not own.** A connection whose
`declared_by` is `inferred` or `accepted_suggestion` is deliberately left
out of an exported `culprit.yaml`. Writing it in would transfer ownership
to the manifest — `apply` treats every edge in the file as
manifest-declared — and the next apply that dropped the line would delete
an edge a human had explicitly accepted. Those edges are still real, and
still visible in `GET /model/connections` and in **Settings → Services**;
they are simply not part of the declarative document.

What is guaranteed: no manifest-owned component, connection, kind or
criticality is lost or invented, and the export is a fixed point — exporting an exported file
gives identical bytes, and re-applying one reports no changes. Phase 27's
acceptance criterion "apply, export, diff is empty" is true of a file
already in canonical form, and true *semantically* of any file.

## The `/services` API is gone

Phase 27 kept `/services*` for one release as a translation layer over
`components`/`connections`; Phase 30 removed it, and every path under it
now returns 404. Anything written against it — a script, an old copy of
`docs/INSTRUMENTATION.md` — needs `/model/*` instead: `POST
/model/components` to register (it still returns the first ingest key,
once), `POST /model/components/{id}/keys` and `DELETE
/model/components/{id}/keys/{key_id}` for key rotation, `POST
/model/connections` where you used `depends_on`, and `GET
/model/topology/suggestions` plus `.../accept|dismiss` for trace-inferred
edges. A component's keys are listed on `ComponentOut.keys` (metadata
only — never a hash or a plaintext key).

The removal also retired the alias's three distortions: `depends_on`
showing only `http` edges, a legacy `depends_on` PATCH rewriting only
`http` edges, and that PATCH flattening an accepted suggestion's
`declared_by` to `culprit_yaml`. An accepted suggestion is still created
as an `http` connection — trace inference cannot tell the kind — so
reclassify it with `PATCH /model/connections/{id}`, which keeps its
provenance.

## Migrated connections are `http`, declared, and unclassified

Upgrading an existing deployment turns every `service_dependencies` row
into a `connections` row. Three fields have to be filled in that the old
table never recorded, and only one of them is a guess:

- **`kind` becomes `http`.** A guess, and the right one: the registry's
  only consumer was HTTP-service correlation. If a declared dependency was
  really a database or a queue, re-declare it with the correct kind —
  nothing detects this for you.
- **`declared_by` becomes `culprit_yaml`.** Not a guess. Every row in
  `service_dependencies` got there because a human declared it, through
  the API, the UI or `apply_services.py`.
- **`criticality` becomes `unknown`.** Also not a guess, and deliberately
  not the flattering answer. Nothing ever classified these edges, and
  `unknown` is a first-class value: an unclassified connection still
  counts as on the request path (see below), so the honest label costs you
  nothing in coverage and stops Phase 29 computing severity from an
  invented fact.

**`unknown` connections are treated as on the request path.** Only an edge
explicitly marked `background` is excluded from
`GET /model/graph?symptom=`. That is the safe direction — excluding
unclassified edges would silently hide the real cause on any topology
nobody had finished labelling — but it means the request path is wider
than reality until you classify your edges.

## `api_keys.service_id` still points at `components.id`

Phase 27 renamed `services` to `components` rather than copying rows into
a new table, so every foreign key and every GRANT followed the rename
intact. The column on `api_keys` kept its old name. It is not a dangling
reference and nothing is broken; it is one name that did not change with
the others, and renaming it would have reached into
`api/app/ingest_gateway/` for no behavioural gain. Expect to see it in
`\d api_keys` and in `api/app/db/models.py`.

## Downgrading past the system model collapses typed connections

`alembic downgrade` below `7c2e94b1f0aa` recreates
`service_dependencies`, whose primary key is the untyped `(from, to)`
pair. Several connections of different kinds between the same two
components therefore collapse into one row, and `kind`, `criticality`,
`declared_by` and `contract_id` are dropped outright — as are a
component's `kind`, `environment_scope` and `labels`.

The downgrade succeeds; it does not warn. A subsequent re-upgrade produces
one `http` connection per surviving pair, `declared_by = culprit_yaml`,
`criticality = unknown`. Back up first (`scripts/backup.sh`). The round
trip is verified in CI (`scripts/check_migration_round_trip.py`) — what is
verified is that it *runs*, not that it is lossless, because it is not.

## `culprit.yaml`'s credential check is a heuristic

The loader refuses a manifest that looks like it carries a secret: a key
matching `password|secret|token|api_key|...`, or a value matching a DSN
with inline credentials, a PEM block, an AWS key id, a GitHub token or a
JWT. This is a blunt guard against the obvious mistake, not a secret
scanner.

It will miss a credential that looks like ordinary text — a bare password
in a field called `note`, an internal token format it has never seen. It
will also refuse things that are not secrets: a component legitimately
labelled `auth_token_issuer` is rejected on its key name. Both directions
are deliberate. A manifest is a committed file, so the cost of a false
positive is renaming a label, and the cost of a false negative is a
credential in git history forever.

The refusal never echoes the offending value, so a rejected manifest does
not leak the secret into a CI log.

## A topology suggestion is dropped once any connection joins the pair

An edge observed in traces is suggested in **Settings → Services** only while
no connection of *any* kind joins that pair. If `orders-svc -sql-> orders-db`
is declared, an observed HTTP call between the same two components is not
suggested. (Until Phase 32 this section also described the correlation
engine grouping incidents across every connection kind; that engine is
gone.)

## "Safe to attach to a bug report" covers values, not every field

The guarantee is precise and narrower than it sounds. A `Fact` cannot
carry a config **value** without a grant, its `value_shape` is a closed
four-field type, and its `subject` must be canonical. Those are enforced
by the model, by the API and by three CHECK constraints.

`provenance.artefact`, `provenance.locator` and `predicate` are **free
text, stored verbatim**. An extractor that put a matched source line into
`locator` — the natural place for "here is what I matched" — would put
whatever that line contained into the capture, and nothing would stop it.
The shipped extractors write a file path and a line number (`L142`,
`$.paths./orders.post`), never content, but a third-party extractor is
not bound by that.

So: a capture bundle is safe to attach *because of what the shipped
extractors put in it and what the model refuses*, not because every
field is validated. If you write an extractor, put locations in
`locator`, not excerpts. (Raised by the Phase 28 invariant audit.)

## A malformed capture tells you which fact, not which subject

Validation errors name the position (`facts.3`) and the rule, and
deliberately never quote the subject, the value or the canonical form
the subject should have had.

That is because a subject is attacker-controlled text on this path and is
exactly where a value would be hidden — `opaque:postgresql://u:pw@db/x`
is a perfectly good way to smuggle a DSN into an error message, and an
error quoting it would put that DSN in the 422 body and the access log.
The audit found precisely this in the first version of the check that was
added to prevent it.

The cost is real: debugging a rejected bundle means looking at the index
the error names rather than reading the subject out of the response.

## A capture is one plane's worth of claims

`POST /facts/captures` refuses a bundle whose facts are on a different
plane than the bundle declares, or stamped with a different environment.

That is not fussiness. `intent_facts` has no `plane` column and no
`environment` column — the plane *is* the table — so an INTENT bundle
carrying a CONFIGURED fact used to be accepted and stored with the
environment and the grant silently discarded. A reading of production
became a claim about what the system is supposed to do, and the
comparator in Phase 29 would have compared production against itself and
called the result intent. It is refused by request validation now, so no
code path can route around it. (Found by the Phase 28 invariant audit.)

The practical consequence: **one capture per plane, per environment.**
A tool that gathers both at once must post two bundles.

## A 422 does not tell you which value it refused

The API's validation errors carry the field path, the message and the
error type — never the offending value. FastAPI's default handler
includes it, and for a capture bundle that means writing the credential
you were refused for into this API's access log and your CI log.

So a rejected bundle tells you *`facts.3` failed because a config fact
needs a `grant_ref`*, and you look at `facts.3` yourself. That is a
genuine loss of debugging convenience, taken deliberately: it would be
strange to hold extractors to "never carry a config value" while the
error path published one.

## `culprit intent` extracts only what you point it at

A component is extracted only if `culprit.yaml`'s `extract.components`
gives it a `root`. A component with no entry produces **no facts at all**,
and the report names it and says so.

That is deliberate, and the first version did the opposite. Defaulting an
undeclared component's root to the manifest directory meant every reader
ran once per component over the same tree, so a database with no source of
its own was credited with the API's routes, config keys and Alembic head —
every fact in the capture existed twice, attributed to two components, one
of them wrongly. Comparison is subject equality and nothing else, so a
wrongly-attributed fact is a subject that will be compared against
something it has nothing to do with. A named gap beats a confident wrong
answer.

Practically: if your report is emptier than you expected, read the
`SKIPPED` section before concluding anything. It is not decoration. Every
line names a component, a class of fact, and why that fact is missing.

## An extractor is only as good as what it can import

Runtime introspection means importing your application. Three things
follow, and all three are visible in the report rather than silent:

- **An app that reads required config at import time cannot be
  introspected without that config.** This repository's own API raises
  `KeyError: JWT_SECRET_KEY` on import, so `culprit intent` run bare skips
  `http_routes` and `db_schema` with exactly that reason. `just intent`
  sets placeholders. Those values are deliberately **not** in
  `culprit.yaml` — a manifest names config keys and never carries values,
  and its loader refuses anything credential-shaped, which it did when
  placeholders were first tried there.
- **Schema facts need your models to be reachable from the app you
  name.** `culprit-extract-python` reads SQLAlchemy metadata out of
  modules already imported as a side effect of importing your app. An app
  that never imports its models yields no schema facts and says so.
- **Importing runs your code**, at the same trust level as running your
  test suite. `--no-import` degrades to static extraction only. See
  `docs/EXTRACTOR_PROTOCOL.md`.

## Static extraction sees literals, and skips the rest

Every static reader in this phase requires a literal. A route path built
from a variable, a config key read as `os.environ[name]`, a `fetch(url)` —
none of them produce a fact. This is not a gap waiting for a cleverer
parser: a subject built from a guess never matches anything and becomes a
permanent phantom in every report, which is worse than an absence the
report tells you about.

What is and is not seen:

- `os.environ["K"]`, `os.environ.get("K", default)` and `os.getenv("K")`
  are read. A computed key is not.
- `fetch('/x')`, `axios.get('/x')`, and a template with interpolation
  (`fetch` of a backtick string `/users/${id}` becomes `/users/{}`) are
  read. A bare variable is not, and an absolute URL to a third party is
  deliberately not — that belongs to a `dep:` subject, and inventing a
  component name for `api.stripe.com` would produce a subject nothing
  else can match.
- **A trailing interpolation glued to a path segment is skipped, not
  resolved.** A backtick string ending in `graph${query}` — no `/`
  before the expression, nothing after it — could be a query string, a
  suffix or a path fragment, and the template cannot say which. The
  call site is dropped.

  This is a deliberate false negative, traded for a false positive that
  was worse. Appending the parameter placeholder produced the subject
  `/model/graph{}`, which can never match any route a server declares:
  a permanent, unfixable finding against a repository that is correct.
  Culprit reported exactly that about its own frontend, where `query`
  holds `?symptom=…`. Truncating instead would be the opposite error —
  a path ending in `orders${rest}` where `rest` is `/42/refunds` is not
  a call to `/orders` — and choosing between them by reading the
  variable's *name* is the implementation-level inference D6 rules out.

  A literal `?` does end the path, so a template written
  `graph?symptom=${s}` reads as `/graph`. An interpolation after a `/`
  is unambiguously a segment, so `/users/${id}` is unaffected — that is
  most call sites in a React codebase.
- A project-local HTTP wrapper is invisible unless you name it:
  `culprit-extract-node --client-fn request`. Almost every real codebase
  has one and no generic tool can recognise it. Guessing — treating any
  one-string-argument call as a request — would flood the report with
  routes that do not exist.
- **Test-derived route facts are a proximity heuristic.** Within one test
  function, every asserted status code is paired with every path that
  function calls. A test exercising two endpoints and asserting two codes
  produces four facts, two of them wrong. They are rank 50 (§2.4), so
  they lose to the app's own route table wherever the two overlap, and a
  wrong pairing surfaces as a visible `intent_conflict` rather than a
  silent wrong answer. Tracking which response came from which call is
  dataflow analysis, which D6 rules out.

## Byte-identical output needs the clock pinned

`culprit intent` stamps `captured_at` on every fact and derives the
capture id from the capture's content *and its time*. Two runs seconds
apart therefore differ in exactly those fields — legitimately: they are
two different captures of the same tree.

Set `SOURCE_DATE_EPOCH` to pin it:

    SOURCE_DATE_EPOCH=0 culprit intent --format json > a.json
    SOURCE_DATE_EPOCH=0 culprit intent --format json > b.json
    diff a.json b.json     # empty

Everything else is deterministic by construction: map iteration is
drained and sorted, fact order is total (subject, predicate, extractor,
artefact, locator), and a plugin's own clock is overwritten with the
run's.

## The extraction walk is bounded, and skips vendored trees

The Go readers and the Python extractor stop six directory levels below a
component's root (the Node extractor, eight), and none of them descend
into `node_modules`, `.venv`, `dist`, `build`, `vendor`, `.git` or the
usual caches. A repository keeping real source deeper than that, or inside
a directory named like a vendor tree, is not fully read — and nothing
tells you, because once a directory is skipped "found nothing here" and
"did not look here" are indistinguishable.

The bound exists because an unbounded walk over a checked-out
`node_modules` turns a sub-second command into a minute, and because a
dependency's own `openapi.json` is not your system's intent.

## Dependency facts merge runtime and dev dependencies

A `dep:` subject has no slot for which group a dependency came from, so
`package.json`'s `dependencies` and `devDependencies` — and the
equivalents in `composer.json` and `Cargo.toml` — land in one namespace,
runtime winning a name collision. `pyproject.toml` is read only for PEP
621's `[project] dependencies`: Poetry's `[tool.poetry.dependencies]` is a
different shape and is deliberately not half-read, because a partial
dependency set looks exactly like a complete one.

Version specifiers are kept verbatim, range syntax and all — `^4.18`, not
`4.18`. That is the point: the difference between "any compatible 4.x" and
"exactly 4.18" is what a comparison against a deployed version turns on.

## Three implementations of subject construction now exist

§2.3 anticipated two, Python and Go. There are three: `extractors/node/`
carries its own, because it runs inside a user's npm project where neither
a Python module nor a Go binary is available.

They agree only because all three read the same two fixtures —
`shared/tests/subject_conformance.json` and `canonical_conformance.json` —
and each language's suite fails if its implementation drifts. Add a case
to the fixture, never to one language's tests. A fourth implementation
would raise this cost again and should be weighed against emitting facts
through one of the three that exist.

## `--export` cannot reproduce your `extract:` section

The control plane does not store it. Extraction runs in the `culprit`
binary against a checkout, so nothing in the database knows what your
extractor commands are, and `just apply-model --export` cannot put them
back.

Pass your current file and the section is carried through:

    just apply-model --export culprit.yaml > culprit.yaml.new

Run it without one and stderr says plainly that the section is being
dropped. It is never lost silently — that was the defect the Phase 27
audit found in `declared_by`, and the documented
`apply-model --export > culprit.yaml` workflow walks straight into it.

## The extractor plugins are not published, and the CLI is not released

`culprit-extract-python` is not on PyPI and `culprit-extract-node` is not
on npm; both install from this repository as path dependencies. No
`vX.Y.Z` tag has been cut, so `scripts/install.sh` has nothing to download
— the release workflow exists and is exercised on every push, but cutting
a release is a human pushing a tag.

Until then: `just cli-build` produces the binary, and the extractors
install with `uv add --dev --editable extractors/python` and
`npm install --save-dev ./extractors/node`.

## Three copies of the DB role-password list

Adding a Postgres role means adding its password to
`api/tests/conftest.py`, `scripts/check_migration_round_trip.py` **and**
`mcp_server/tests/test_mcp_reader_role.py`, because every migration's
`_require_env` must be satisfied for `alembic upgrade head` to run at all,
and those are three separate uv projects that cannot import each other's
fixtures. Miss one and that project's tests fail at container setup with a
`CalledProcessError` that does not name the missing variable.

Same root cause as `worker/app/db.py` hand-mirroring `api`'s ORM. Unlike
that one, there is no drift checker for it yet.

## `culprit check` compares intent against intent

Every fact `culprit check` reads is on the INTENT plane, so every finding
it reports is an `intent_conflict`: two things your repository says about
itself that do not agree. What an environment is actually configured to
do is `culprit diff`'s question (Phase 30), and what actually happened in
production is Phase 31's. `check` never reads an environment, and a
manifest growing an `environments:` section does not change that.

That is a real limit and it is also most of the value. Two sources of
intent disagreeing is usually itself the bug, and it is detectable in a
pull request before anything is deployed, with no environment access and
no account.

## Absence is only judged against a source that enumerates

"The frontend calls a route the backend does not expose" is a finding
only when something *complete* described that backend's routes — a
running application's own route table, or a committed `openapi.json`
(confidence rank 80 or above, §2.4). A scrape of call sites is not a
complete list of anything, and its silence is never treated as evidence.

Two consequences worth knowing:

- **If extraction was skipped, no absence is reported at all.** A
  component whose route table could not be read produces skips, not
  findings, and the report lists them under "Not checked". A clean report
  with nine skips is not a clean system.
- **A hand-written `invariants:` entry is never a reference either.** It
  is rank 100 — above every extractor — but rank says how much to
  *believe* a source, not whether it was surveying a surface. An
  invariant says "this route must exist"; it never says "and these are
  all of them".

## The migration-chain reader understands literal Alembic operations only

`schema:` facts from your migrations are produced by reading the
migration files with Python's `ast` — never by running them, which would
need a database this phase deliberately has no access to.

It follows `create_table`, `add_column`, `drop_column`, `drop_table`,
`rename_table` and `alter_column ... new_column_name`, with literal
arguments. A migration that builds its columns in a loop, or issues raw
`op.execute("ALTER TABLE ...")`, is invisible to it, and the resulting
column list will be missing whatever those did.

It also **declines entirely** rather than guessing when the revision
chain does not form a single line — a merge revision, two roots, a cycle,
or an unreachable file. A partially replayed chain would produce a
confident column list that is simply wrong, and every difference against
it would be a false positive.

Emitted at rank 80, below the ORM's runtime introspection at 90, so when
the two disagree the report treats the models as the reference.

Since Phase 37 part 1 it also follows indexes, for one question: whether
each column *leads* an index (an index on (a, b) serves a filter on a, not
on b). It reads a column's `primary_key=True`, `unique=True` and
`index=True`, `PrimaryKeyConstraint` and `UniqueConstraint` in
`create_table`, `create_index`, `create_unique_constraint`,
`create_primary_key`, `drop_index` and a named `drop_constraint` — with
literal arguments, as for columns. A partial index (`postgresql_where=`)
and an index on an expression are not counted, on either side. An index
created by `op.execute("CREATE INDEX ...")`, or a constraint dropped by a
name the reader never saw, is invisible to it, and the report will say
the database has an index the migrations do not declare. The ORM's models
are not read for indexes.

## A test assertion says a route is exercised, not what it returns

Phase 28's extractor recorded the status codes a test asserted. Phase 29
removed that, because it produced false positives on Culprit's own
repository: one test asserts 201 for `POST /services` and another asserts
403, and the comparator reported them as disagreeing. They do not — a
route answers 201 to an admin and 403 to a member.

What survives is `exercised_by_test`, which still catches a test calling
a route the application does not serve, and still tells the coverage
report which parts of your surface no test touches. "The test expects 200
and the app returns 404" is not detectable this way and is not claimed.

## A config key's example and its default are not compared

`.env.example` gives the shape of a *placeholder somebody wrote*;
`os.environ.get("KEY", "")` gives the shape of a *default the code falls
back to*. These are different claims, so they carry different predicates
(`example_shape` and `default_shape`) and never compare against each
other.

The cost: a genuine type disagreement between the two — `PORT=8000` in
the example, `"localhost"` as the default — is not currently detected.
The alternative was reporting every key whose placeholder is longer than
its default, which is nearly all of them.

## Severity is only as good as your `culprit.yaml`

`breaks_request_path` means "reachable from an entry point along an edge
you marked `on_request_path`". A manifest with no `connections:` gives
the classifier nothing to work with, and it says so — findings come back
`unknown` rather than being quietly filed as trivial.

`unknown` deliberately ranks *above* `cosmetic`, so `--fail-on=any`
includes it. "We could not work out how bad this is" must not be quieter
than "we worked it out and it is trivial".

## The fault corpus evaluates the engine, not extraction

`cli/testdata/faults/` is the eval suite: each fixture is a committed
fact bundle plus the exact divergence set it must produce, and an
unexpected finding fails the build as a false positive. What it exercises
is comparison, severity, suppression and invariants — given facts.

Extraction has its own corpus (`cli/testdata/fixtures/`, plus the Python
and Node extractors' test suites). The seam between the two is the
subject URI, held by a conformance fixture both languages read.

The gap this leaves is real: if an extractor changes what it emits, the
fault bundles go stale silently, because nothing regenerates them from a
live extraction. Splitting the evals this way keeps them hermetic and
fast enough to run on every commit, which a corpus needing `uv` and
`npx` per fixture would not be.

## The CLI does not upload anything

`POST /divergences/captures` and `POST /captures` exist and store
history, but no version of the `culprit` binary calls either: it links no
HTTP client at all, and a test asserts that its check pipeline links no
networking package whatsoever. Phase 29 deferred uploading "to Phase 30,
where network access arrives with the capability model"; Phase 30's plan
listed the endpoints and not an uploader, and adding an HTTP client to
the binary was not something to do by implication. It is still deferred.

Until then, history is populated by posting yourself:
`culprit check --format json` for findings, and for a capture the
envelope `culprit env capture` writes, verbatim:

    curl -X POST https://culprit.example.com/api/captures \
      -H "Authorization: Bearer $CULPRIT_PROJECT_TOKEN" \
      -H "Content-Type: application/json" --data @production.capture.json

## Findings are never closed automatically

A divergence that stops appearing is not marked resolved. This run may
have checked a subset of components, or extraction may have been skipped
for one entirely. Inferring "it is fixed" from "I did not see it" is the
same mistake the comparator refuses to make about facts. Resolution
arrives with verification, in Phase 32.

## `culprit diff` reads environments through `docker` and `kubectl`

The Compose and Kubernetes adapters run the `docker` and `kubectl` you
already have, with your own contexts and credentials, rather than
linking Docker's SDK or client-go into the binary. The released binary can
therefore capture a Compose project or a cluster with nothing extra built
in — and cannot without those two commands on `PATH`. The JSON that
`docker inspect` and `kubectl get -o json` print is a contract Culprit now
depends on; a field those tools rename is a capture that silently has
less in it, and the recorded-output tests are what would notice.

Deliberately different from the plan, which named the SDKs behind
optional build tags: behind build tags the downloadable binary would have
captured nothing, and both SDKs are HTTP clients in a binary whose tests
assert it links none.

## The `exec` adapter needs `env -0` or JSON, not `printenv`

A command read by the `exec` adapter must print NUL-delimited `KEY=VALUE`
pairs (`env -0`, `printenv -0`) or a JSON object of strings. Plain
line-delimited output — what `printenv` and `heroku config --shell` print
by default — is refused, with a reason, and nothing from it is kept. A
multi-line value such as a PEM key prints across several lines, and the
last line of a base64 block (`QUJDREVGRw==`) is indistinguishable from an
assignment: read line by line, a fragment of a secret became a variable
*name*, and names are never masked. Found by the Phase 30 invariant
audit. Keys that are not valid variable names are dropped from every
adapter, and when that happens in `exec` output the environment is
marked incompletely enumerated, so nothing is judged missing from it.

## What an environment has that the code never mentions is not a finding

`PATH`, `HOSTNAME`, `KUBERNETES_SERVICE_HOST`, a table an old migration
left behind: an environment always holds more than the repository
declares, and reporting every extra would bury the one missing
`DATABASE_URL` under forty that are fine. So absence is judged in one
direction only — something INTENT says must exist, missing from an
environment. The cost is real: a genuinely stray production table, or a
variable set in production that nothing reads any more, is not reported.

Between two environments, a key one sets and the other does not *is*
reported — but only for keys INTENT does not mention (those are judged
against INTENT instead), and ranked `cosmetic` when nothing reads the
key, because nothing can break for want of it.

## Where the code has an answer, environments are compared with the code, not with each other

If the migrations say the head is `0003` and production says `0002`, that
is one finding — production against the code. "Staging and production
disagree about the migration head" is not reported as well: it is the
same fault said worse, because it no longer says which side is wrong.
Environments are compared directly only on questions the repository does
not answer — image digests, installed package versions, the shape of a
key nothing declares.

## An environment that could not be seen whole is never evidence of absence

When a Kubernetes Deployment loads variables with `envFrom` from a
ConfigMap or Secret that `kubectl` cannot read, the capture records that
the environment was not enumerated completely, and **no key is reported
missing from it** — including one that genuinely is. "I could not see
all of it" must never become "it is not there". A variable set by
`valueFrom` is known to exist but has an unknown shape, and an unknown
shape compares on presence alone.

A Secret loaded with `envFrom` contributes its key names only: Culprit
lists them through a `kubectl` template that never prints the data, so
it cannot say whether a secret-sourced key is empty or what kind of value
it holds.

## Only the first replica is read

When a Compose service runs several containers, the one first by name is
read and the capture records how many there were. Replicas that disagree
with each other — a rolling deploy caught halfway — are not detected.
For Kubernetes the Deployment's own spec is read, so every replica is
described by the same template; the image digest comes from the first Pod
by name that reports one.

## Live schema: columns, nullability and leading indexes, Postgres and Alembic only

`db.metadata.read` compares which tables and columns exist and whether
each column is nullable. It does **not** compare column types:
`information_schema` says `character varying` where SQLAlchemy says
`VARCHAR(255)`, and every column would be a false disagreement. A column
that changed type is invisible here.

Only Postgres is read, and only Alembic's `alembic_version` is understood
as a migration version. The table list comes from `pg_catalog`, so any
role can read a complete schema; the version needs `SELECT` on
`alembic_version`, and without it the capture says the version was not
read. Views, partitions and the TimescaleDB catalogues are not listed.
The database a component's tables are compared under is `<component>-db`
unless `database.name` says otherwise — the name the Python extractor
uses on the INTENT side, which is what makes the two meet.

Since Phase 37 part 1 each column also says whether it leads a valid index
(`leads_index`, true or false), compared with what the migrations declare:
an index dropped by hand is reported as declared but missing, one created
by hand as live but undeclared. A partial index, an expression index and
an index still being built (`indisvalid` false) are not counted. Whether
an index *helps* a query is not judged here — that needs the planner,
Phase 37 part 2.

### What Culprit sends a database, and what holds it

Four layers, each holding something different (Q27, ruled 2026-11-12):

- **The package.** The session lives in `internal/capture/dbsession`, a
  package with one non-test file, the only one in the binary that imports
  the database driver. Its exported surface — a reader, the schema it
  returns, a classified error — names no driver or network type, so no
  code outside it can hold a connection to send something through. Go's
  visibility is per package, not per file: Phase 37 part 1 held this with
  "one file imports the driver", and its audit sent `EXPLAIN ANALYZE` from
  a sibling file with no import at all. That file, planted in
  `internal/capture` today, does not compile, and a test plants it to show
  so. What the package does *not* hold is a change to the package itself:
  code added to `dbsession` can do anything the driver can, which is why it
  is one file and a test fails if a second appears.
- **The templates.** Inside the package, the statements it can send are a
  closed set — four today: three catalogue reads and the Alembic version
  row — checked by a `switch` that must list exactly the template
  constants (a test fails on a constant the switch does not list, or on a
  map of statements another file could extend). Anything else, an
  `EXPLAIN ANALYZE` included, is refused before it leaves, and a test
  counts what reaches the driver.
- **The read-only session.** Every session is opened with
  `default_transaction_read_only = on` and a ten-second
  `statement_timeout`, so Postgres itself refuses a write (a test against a
  real Postgres sends one). It does not refuse what is not a write: an
  `EXPLAIN ANALYZE SELECT …` runs the query, and `pg_stat_statements_reset()`
  is a function call. The two layers above are what keep those from being
  sent.
- **The role.** What the server lets the role do is the last bound, and the
  one a stolen credential carries (docs/PERMISSIONS.md, "The recommended
  database role"). The recommended role holds no `EXECUTE` on
  `pg_stat_statements_reset`, which is how Postgres ships it.

Culprit never resets `pg_stat_statements`.

## Installed versions are compared between environments, not against what you declared

`pip freeze` says `fastapi==0.115.4`; `pyproject.toml` says
`fastapi>=0.115`. Deciding whether one satisfies the other means PEP 440
and semver ranges inside a comparator that knows nothing about any
domain, so installed versions are a separate claim, `installed_version`,
compared only environment against environment. "Production runs a
version your constraint forbids" is not detected.

## Network checks: one endpoint per component, and a class rather than a date

A component may declare one `endpoint`. Its certificate is reported as
`valid`, `expires_within_30_days`, `expired`, `untrusted` or
`handshake_failed` — never the expiry date, because two environments'
certificates expire on different days as a matter of course. The 30-day
threshold is fixed. These checks stop at a DNS lookup, a TCP handshake or
a TLS handshake: whether the application behind the port actually
answers is Phase 31's probes, not this.

## A signature says the capture is unaltered, not who made it

`culprit env capture --sign-key` signs the envelope with Ed25519, and
`culprit diff` and `POST /captures` refuse one that does not verify. The
public key travels in the envelope, so a signature proves the capture has
not changed since whoever held that key signed it — not who that was.
Culprit keeps no list of trusted keys; `captures.signed_by` stores the key
id so you can check it against yours. An unsigned envelope still carries
a SHA-256, which catches corruption and nothing more.

**Signing is optional, which is a deviation from the plan.** Phase 30
field 7 says "a capture is a signed, timestamped bundle"; a capture is
signed only when you pass `--sign-key`, because a signature needs a key
the user holds and Culprit will not invent one for them. By default an
envelope is hashed, not signed — so it can be edited (refusals dropped, a
fact changed) and re-hashed, and `culprit diff` and `POST /captures` will
accept it. Neither can be told to require a signature yet.

## `GET /captures/diff` is a snapshot diff, not the engine

The API compares two stored captures fact by fact: which answers differ,
which exist on one side only. It has no INTENT, no severity and no
suppressions — those need the repository, and live in `culprit diff`. The
two share the shape-equivalence rule and the rule that a config value is
never rendered, held by `shared/tests/shape_conformance.json`.

## The capture agent sees the api's configuration, and through the api's own role

The optional agent in `docker-compose.prod.yml` uses the `process`
adapter with the same `.env.prod` the api reads, so what it captures is
the api's configuration; the worker's and ingest-gateway's differ only by
the two variables the compose file remaps. It reads the live schema as
`api-reader`, which has no `SELECT` on `alembic_version`, so a production
capture reports the migration version as unread until you give it a role
that can. It is one-shot and prints to stdout: there is no agent daemon
in this release.

It is given all of `.env.prod`, because the `process` adapter reads the
environment it runs in — so its capture lists the *names and shapes* of
every variable in that file (the superuser password, every role
password, the JWT key) and attributes them all to `culprit-api`. Values
are never read without `config.read.values`, and the root `culprit.yaml`
grants none; the names are what `config.read.names` means.

## The Go CLI needs Go 1.27 or later to build

`cli/go.mod` declares the version CI builds with — Go 1.27, in every job,
the release workflow and `cli/Dockerfile` — because a floor CI never
exercises is not one anyone can rely on (Phase 32.2; it said 1.25 until
then). The lowest version the dependencies themselves need is lower: the
patched releases of pgx (a memory-safety CVE, fixed in 5.9.0) and of
`golang.org/x/text` need 1.25. An older Go is past its support window, and
a binary built with it carries standard-library CVEs that will not be
fixed, which the image scan catches.

## Where a stored value is guarded by code rather than by the database

Four places the Phase 30 invariant audit named, each a real residual risk
rather than a defect, and each a design decision for later rather than a
patch:

- **`api-reader` can read a granted literal.** It has `SELECT` on
  `configured_facts`, including `value`, because non-config facts (a
  digest, a column list) keep their payload there. What stops a granted
  config value reaching the dashboard is the API's one serialiser,
  `fact_out`, and the test that plants a value and asserts no endpoint
  returns it — not a column grant or a masking view.
- **"A config value's grant is its own key's" is checked by `POST
  /captures`, not by Postgres.** Every CONFIGURED fact names *some* grant,
  so `ck_configured_facts_value_requires_grant` is always satisfied; a
  writer that bypassed the endpoint could store a config value under the
  `config.read.names` grant.
- **Non-config values are not type-checked on upload.** A capture built by
  hand — by someone holding the project token — could put arbitrary text
  in `dns_resolves` or `digest`, and `GET /captures/{id}` would render it.
  The CLI never produces one.
- **Grant items are compared exactly.** An allowlist item names
  `<component>/<KEY>` as written in `culprit.yaml`; a component written
  in a different case from the model's canonical (lower-case) name is
  refused on upload rather than matched. It fails closed.

## The dashboard's Caddy is built from source, and pinned by hand

The `frontend` image no longer ships the `caddy` binary from the published
`caddy:2-alpine` image. On 2026-09-11 that binary carried 12 CRITICAL/HIGH
CVEs (Go stdlib, `golang.org/x/crypto`, `golang.org/x/net`, grpc) with no
newer upstream image to move to, so `frontend/Dockerfile` rebuilds the same
Caddy release with `xcaddy` on the Go toolchain `cli/` uses, with those
three modules pinned forward by `--replace`.

The cost is that Caddy security fixes no longer arrive by themselves. A
new Caddy release, or a new CVE in a module it depends on, reaches the
image only when someone bumps `CADDY_VERSION` or a `--replace` line. The
image scan in CI is what tells you it is time, and `.trivyignore` is not
the answer when it does. The `--replace` pins also override whatever
versions the Caddy release itself asked for, so a pin that is later
*older* than Caddy's own requirement would silently downgrade it —
drop each pin once the Caddy release you are on already satisfies it.

The pin set therefore changes with each bump, and the list above is a
snapshot of 2026-09-11, not the current one. As of 2026-11-03 the image
builds Caddy v2.11.7, whose own `go.mod` satisfies the original
`x/crypto` and grpc pins (both dropped), and pins only `golang.org/x/net`
v0.60.0 and `github.com/go-jose/go-jose/v4` v4.1.6. `frontend/Dockerfile`
is the record of what is pinned and why. To see what a release asks for
before deciding a pin, read its `go.mod`
(`go mod download -json github.com/caddyserver/caddy/v2@<version>`).

## SARIF annotations on Culprit's own pull requests

`culprit check --format sarif` writes a valid file, and the `self-check` CI
job uploads it to GitHub code scanning (`github/codeql-action/upload-sarif`,
category `culprit`), which is what turns a finding into an annotation on the
changed line of a pull request. The upload failed while the repository was
private and was replaced by a build artifact (`63cea12`); Phase 32.1 part 2
restored it once the repository was public and code scanning enabled. The
artifact, `culprit-sarif`, is still kept beside it. Annotations appear only
for findings on lines a pull request changes; a finding elsewhere is in the
repository's code-scanning alerts and in the job's log. Since `60e53fd` a
self-check finding at `breaks_request_path` also fails the job.
## Probes run what you name them to run

`culprit probe` executes the probes you ask for, against the target you
give it. It does not choose probes, order them, stop early when one
answers the question, or build a fault tree from the results. That is
`culprit diagnose` (Phase 32), which chooses each probe by what it rules
out — the `discriminates` field of its manifest — and has its own limits,
below.

Practically: if you do not pass `-p`, every probe in the catalogue runs
against your target, and most of them will return `inconclusive` because
their inputs were not supplied. That is honest but noisy. Name the probes
you want.

## One probe has no data source in the CLI, and that is deliberate

Until Phase 31.1, five probes had no data source behind them from the
command line. Four now do, through the Phase 30 capture machinery
(`cli/internal/probe/sources.go`): `probe.db.connect` and
`probe.db.schema_conformance` read the database with
`capture.PostgresReader`, `probe.config.present` reads the environment
through its capture adapter, and `probe.dep.version` runs the
component's declared packages command. Each needs `--env`, and each
reaches only what that environment declares and grants.

`probe.edge.impedance` still has none, and is not meant to: reading
impedance from the CLI would mean calling the API, and only
`internal/probe` may link an HTTP client (D8, amended) — which it does
for outbound probes of the system under test, not for reading Culprit's
own store. Its readings are produced by `worker/app/anomaly/job.py`,
which has the telemetry. From `culprit probe` it is `refused` unless the
environment grants `telemetry.metrics.read` (the demo's `local` does not),
and with that grant it returns `inconclusive` saying the worker produces
it. Neither is a measurement. No endpoint serves stored readings yet
(`POST /readings` only), so today those worker readings are visible in the
database, not from the CLI or the dashboard. Phase 31.1's field 17 keeps
impedance's production where it is.

## Reading installed packages needs a second grant

`probe.dep.version`'s manifest declares `repo.read`. Reading what is
*installed* in an environment means running that component's `packages:`
command, and running a command needs it on `process.exec.allowlist` —
the same rule `culprit env capture` follows. So the probe needs both,
and with only `repo.read` it returns `refused` naming the command. The
manifest was not changed to declare the second capability, because
manifests list what a probe needs regardless of environment and the
command is per environment; the source asks the ledger for it instead,
and the refusal is recorded like any other.

## Declared version ranges are reported, not judged

`probe.dep.version` compares the installed version against the declared
one only when the declaration is an exact pin (`1.2.3`, `==1.2.3`). A
manifest usually declares a range — `fastapi>=0.115`, `react: ^18.2.0` —
and deciding whether a version satisfies a range means PEP 440 and
semver semantics that D7 keeps out of a generic comparator (the same line
`culprit env capture` draws between `version` and `installed_version`).
Against a range the probe returns `inconclusive` with both values, so on
most real projects this probe will not reach a verdict unless you pass
`--input expect_version=` yourself.

## Probe expectations are only as good as the extraction behind them

`culprit probe` resolves each reading's expectation from the same
extraction `culprit check` runs, which has three consequences:

- **It costs an extraction.** Every `culprit probe` invocation runs the
  extractors first, including the language plugins, which import the
  application. `--no-plugins` skips them, at the price of every
  expectation the plugins would have supplied.
- **No declaration, no verdict.** A probe measured against INTENT whose
  subject nothing declares returns `inconclusive`, even when the
  measurement looks healthy: "this route answers 200" is a measurement,
  and only a declaration turns it into conformance. A repository whose
  routes are not extractable gets measurements, not conformance.
- **A concrete URL is matched to a template by segments.** `/orders/42`
  matches a declared `/orders/{id}`, and a literal route beats a
  parameterised one. Matching is per segment and exact: a route
  registered with a trailing slash, a different prefix, or a mount point
  the extractor did not see will not match, and reads as undeclared.

`--capture <envelope>` supplies CONFIGURED expectations, from a capture
of the same environment. In this release the only probe measured against
CONFIGURED whose predicate a capture could supply is none:
`probe.db.connect` produces `database_connects`, which a capture does not
record, so `--capture` changes nothing about any built-in reading yet.
The path exists, and is tested, so the next probe that needs it does not
need an engine change.

## Probes run from wherever you run them, not from where the caller sits

`docs/PROBES.md` opens by framing the question as "can A actually reach B,
*from where A sits*". The shipped CLI answers a narrower question: can
**this process, on this host**, reach B.

That distinction matters as soon as the network is not flat. A probe run
on a laptop against two containers reaches both through their published
ports, so a partition *between* them is invisible to it. A probe run on
a CI runner sees CI's network, not production's. Nothing in
`probe.Request` names a vantage point, and no probe shells into a
container to run from inside it.

The vantage point is therefore wherever you put the binary, and the
reading records it in `agent_id` (decided 2026-11-03, Phase 31's
criterion 2 reworded to say so). Phase 31.1 demonstrated it by running
the static linux binary *inside* order-service
(`infra/docker-compose.probe-demo.yml` mounts it there): with a firewall
rule in order-service's own network namespace rejecting its traffic to
inventory-service, A's reachability probes for B went to `fail` while
both services' health probes, run from the host, stayed `pass`. Culprit
does not put itself in the container for you — you `docker exec` it.

Two ways to break a path between containers do **not** demonstrate this,
and both were tried. Disconnecting A from the shared network on Docker
Desktop also kills the host's port forward to A, even with a second
network attached and made A's gateway network, so A's own health probe
from the host stops passing too. And dropping packets rather than
rejecting them produces a timeout, which every network probe reports as
`inconclusive`, not `fail` — correctly, since a timeout does not prove
the path is closed.

## A probe's inputs come from you, not from the model

The endpoint a network probe dials, the URL an HTTP probe requests and
the token an auth probe inspects arrive as `--input key=value`. Culprit
does not derive them from `culprit.yaml`'s component definitions, so a
probe whose input you did not supply returns `inconclusive` rather than
guessing a hostname. Wiring the system model into probe inputs
automatically is worthwhile and is not done.

A database's connection string is the exception, and on purpose: since
Phase 31.1 it is **never** an input. It is read from the variable a
component's `database: dsn_env:` names, in the environment `culprit` runs
in, so it never appears in shell history, a process listing or a
reading.

## Refused, filtered and slow are not the same, and only one is a failure

`probe.net.tcp_connect` returns `fail` when a connection is **actively
refused**, because that is definitive. When the connection times out —
a dropped packet, a firewall that blackholes, a host that is simply slow
— it returns `inconclusive`, because none of those prove the port is
closed.

This is deliberate and it has a cost: a genuinely dead service behind a
packet-dropping firewall reads as "I could not tell" rather than "this is
broken". Reporting it as a failure would be a guess, and a guess that
reads like a measurement is the failure mode this whole architecture
exists to avoid. Raise `--timeout` if your network is slow enough that
this is a nuisance.

## The same three network checks exist twice

`culprit env capture` reads DNS, TCP and TLS for a component's declared
endpoint and records them as CONFIGURED facts. `probe.net.dns_resolve`,
`probe.net.tcp_connect` and `probe.net.tls_validity` do the same three
operations and return OBSERVED readings with a verdict.

Both are kept on purpose — `docs/PROBES.md` explains what each is for,
and the deciding difference is that a probe must be able to answer
"inconclusive" where a capture answers yes or no. But the consequence is
that the low-level resolve, dial and handshake code now exists in two
packages, `cli/internal/capture` and `cli/internal/probe`. That is two
places to audit and two places a change has to be made. Collapsing them
means changing `internal/capture`'s interface, which Phase 31 did not own.

## The `culprit` binary can now make HTTP requests

Until Phase 31 the binary linked no HTTP client at all, and a test
asserted it on the grounds that it had nothing to talk to. Probes make
that false: `probe.http.*` and `probe.auth.propagation` exist to ask a
running service a question, under the `net.http.outbound` grant.

What replaced that assertion is narrower but sharper, and since Phase
31.1 it is an allowlist (`TestTheNetworkBoundaryIsAnAllowlist`): only
`internal/probe` may link `net/http`, only `internal/probe` and
`internal/capture` may link `net` or `crypto/tls`, and every other package
under `internal/` — including one added tomorrow, with no edit to the
test — may link none of them, so the packages that *compute findings*
still cannot open a socket. `internal/probe` is the one package permitted
a client, its
client has no method that can send a body or use a verb other than `GET`
and `OPTIONS`, and none of it runs without a grant. But the honest
statement is that the binary's network posture changed in this release,
and a reader who trusted the old blanket claim should know it.

## HTTP probes read field names, never bodies

`probe.http.schema_conformance` reports which declared top-level fields
are present in a JSON response. It does not compare types, nested
structure, arrays' element shapes, or any value. A response body on a
real system is user data, so nothing beyond the top-level key set reaches
a reading.

Also: responses are parsed only up to **1 MiB**, only when the
`Content-Type` mentions JSON, and redirects are followed at most **3**
times. A service that answers with a larger document, a non-JSON
content type, or a longer redirect chain yields `inconclusive`.

## Route conformance asks with OPTIONS for anything but GET

`probe.http.route_conformance` issues a `GET` when the declared method is
`GET`, and an `OPTIONS` otherwise — because issuing the declared method
would mean sending a `POST`, `PUT` or `DELETE` at somebody's running
system, which this plan forbids outright.

Many services do not implement `OPTIONS` meaningfully. Against those, a
non-GET route reports `inconclusive` rather than confirming the route
exists. That is the correct answer and it is also a real gap: Culprit
cannot verify a write route's existence without writing, and it will not
write.

## Route conformance proves a path is routed, not that it works

`probe.http.route_conformance` fails only on a **404**, or a **405** for
the declared method. Every other status passes, so a route behind
authentication passes on its **401** — Phase 31.1's own demonstration
passed `GET /model/components` that way — and a route that answers 500
on every request passes too. What it establishes is "the running service
knows this path", which is the INTENT-against-OBSERVED question; whether
the route then does its job is `probe.http.schema_conformance`'s and the
auth probes' question.

It also cannot tell *which* server answered. Point `base_url` at the
wrong thing and the verdict is about that thing: on the machine Phase
31.1 was first run on, an unrelated Apache held port 80, answered every
request with its own 404, and every declared route correctly — and
uselessly — read `fail`. A catch-all route (a single-page app's fallback
that answers 200 for any path) has the opposite effect: every route
passes. The reading's `measured.url` is where to look when a verdict is
surprising.

## `probe.auth.token_shape` understands JWTs

It reads a three-segment JWT's payload for `aud`, `iss`, `exp` and `nbf`.
An opaque token, a SAML assertion, a session cookie or a signed token in
any other format is `inconclusive` — it cannot be structurally inspected.
The signature is **never verified**: Culprit does not hold your signing
keys and is not an authentication service. A token with a valid audience
and a forged signature passes this probe.

## Impedance is attributed to a connection by a stated rule

`probe.edge.impedance` reports how far a connection's latency or error
rate is from its own history. But telemetry arrives keyed by *service*,
not by connection, so `worker/app/anomaly/job.py` has to decide which
edge a service's metric describes. The rule, in order:

1. If the metric's `attributes` name a peer (`peer.service`,
   `peer_service` or `server.address`) and that peer is a known
   component, attribute the reading to `service -> peer`.
2. Otherwise, if the service has **exactly one** declared inbound
   connection, attribute it to that one.
3. Otherwise, emit **no** impedance reading.

Rule 2 is an approximation: it credits a callee's aggregate latency to
its single caller, which is right when there is one caller and wrong the
moment a second appears — at which point rule 3 takes over and readings
stop rather than becoming misleading. A service with several callers
produces no impedance readings at all unless its metrics carry peer
attributes. Instrument for rule 1 if you want per-edge impedance on a
fan-in service.

## Impedance needs 30 observations and calls 3 sigma unusual

Below **30 samples** on a connection, `probe.edge.impedance` returns
`inconclusive` rather than a verdict — a z-score over a handful of points
is arithmetic, not evidence. At or above **3.0** standard deviations it
returns `fail`. Both numbers are fixed constants, not configurable, and
the threshold matches `worker/app/anomaly/scorer.py`'s so that "is this
unusual" has one answer in this system rather than two.

Deviation from usual is not the same as wrong. A connection that has been
slow for months is unremarkable to this probe, and a deliberate change
that shifts a baseline reads as a failure until the scorer catches up.

The worker writes **one impedance reading per (connection, metric) per
scoring batch**, not one per metric row. The scorer's state is cumulative,
so a batch of 2000 rows for one metric is 2000 restatements of a single
measurement; storing them all would put your raw metric event rate into a
90-day hypertable. The consequence worth knowing: during a catch-up batch
covering a long window, an intermediate spike does not survive as a
reading. It does survive as an `anomalies` row, which is the record that
exists for that purpose.

## The control plane cannot run a probe

`POST /probes/{id}/run` returns `503`. Probes execute in the `culprit`
binary, where the environment is, and no agent transport exists to reach
one from the API — that is Phase 33's work. The endpoint validates the
probe id and tells you the equivalent local command. It is an honest
not-yet-available rather than a stub that fabricates a reading, but if
you were expecting to trigger probes from the dashboard, you cannot.

Relatedly, `GET /probes` serves the catalogue from a committed JSON file
that mirrors the Go one. The mirror is checked for validity but the two
can still drift in content; the binary is the authority.

## The credential heuristic in a reading is a net, not a proof

A `Reading`'s evidence is refused at construction if it looks like a
credential and is not marked redacted. "Looks like" is
`looks_like_credential`, which matches known shapes — DSNs with inline
passwords, PEM headers, AWS keys, GitHub tokens, JWTs, `sk-` keys, and
since Phase 37 part 1 a `password=`, `passwd=` or `pwd=` outside a URL
(libpq's keyword form, a literal in a statement), Slack tokens (`xox…-`,
`xapp-`) and `user:pass@host` with no scheme. Go and Python are held to
one set of cases (`shared/tests/redaction_conformance.json`). It is
pattern matching, so a novel or unusual key format passes it — and it
errs the other way too: any `word:word@` in free text is removed as if it
were a credential. One known
gap: the `sk-` pattern requires the remainder to be alphanumeric, so a
hyphenated variant such as `sk-live-abcdef0123456789` is not matched.

What is actually true, stated precisely, because an earlier draft of this
section overclaimed it and the Phase 31 audit caught the overclaim:

- The built-in probes never copy a **secret-bearing** input — a `dsn`, a
  `token` — into a reading. `probe.db.connect` reports `connected:
  true|false` and nothing else; the auth probes report audience, issuer
  and expiry, and a test greps their entire serialised output for the
  token and each of its segments.
- They **do** copy a `url`, `host`, `key`, `package` and `table` into
  `measured`, so a human can see what was measured. A URL is the one of
  those that routinely carries credentials.
- So every reading is passed through `RedactCredentials` once, by the
  runner, *before the reading exists as a value* — and again on the
  `POST /readings` ingest path, because that endpoint accepts readings
  from outside the CLI's guarantee. For a `url`, the pattern heuristic is
  therefore load-bearing, not a backstop.

Which means the gap above is real: a credential in a URL in a shape the
pattern does not match reaches a reading, and `api-reader` can read the
90-day store it lands in.

## The last enabled admin cannot be removed — through the API

`PATCH /users/{id}` (demoting or disabling) and `DELETE /users/{id}` answer
`409` when they would leave no enabled admin, and two admins demoting each
other at the same moment cannot both succeed: each change locks every
enabled admin's row before counting them. The guard lives in the API, not
the database, so a direct `UPDATE users` as the `auth-service` role is not
refused. And an admin who forgets their password is still recovered only
from the host, with `just create-user <name> --role admin`.

## A member's timeline has a lane only for services with incidents

The component registry (`/model`) is admin-only, so a member's browser
cannot read which services exist. The timeline draws a member's lanes from
the services the incidents themselves name instead. Two consequences: a
service with no incident has no lane for a member, and a disabled service
that still has incidents keeps its lane for a member while an admin's
timeline drops it. The incidents, bands and anomalies are the same for
both. Before Phase 31.2 a member's timeline drew no lanes at all — the
header counted incidents and the chart was empty.

## The dashboard answers only to the name it was configured with

Caddy routes by host name. The quickstart configures `localhost`, so
<http://localhost> is the dashboard and <http://127.0.0.1> — the same
machine — returns an empty `200` page, which looks like a broken frontend
and is not. On a real install the same applies to the domain in `DOMAIN`.

## The quickstart takes port 80 unless told otherwise, and a clone outside Windows' temp folder

`just quickstart` publishes the dashboard on port 80. If another server
holds it, that server answers instead (on the machine Phase 31.2 was
verified on, an Apache inside WSL did): set `QUICKSTART_HTTP_PORT` to a free
port, and the recipe prints the address with it. Its compose project is
named `culprit-quickstart` unless `COMPOSE_PROJECT_NAME` says otherwise, so a
second checkout's quickstart reuses the first one's database volume — whose
passwords were fixed by the first checkout's `infra/.env.prod`.

Under Git Bash on Windows, a clone inside `%TEMP%` cannot run the
quickstart at all: Git Bash maps that folder to `/tmp`, the recipe hands
`$(pwd)` to `docker run -v`, and Docker reads `/tmp/...` as a path inside
its own VM, which is empty. The secrets step then fails with
"can't open file '/repo/scripts/bootstrap_env.py'". Clone anywhere else.

## The quickstart now builds a database for the demo

Since Phase 37 part 1, `just quickstart` gives inventory-service a database
of its own (`inventory`, in the same Postgres, owned by an `inventory`
role) and fills a table with a million generated products, which adds
roughly ten to thirty seconds. Its role's password is generated into
`infra/.env.prod` with the others (`INVENTORY_DB_PASSWORD`); a file made
before Phase 37's close-out gets one added by the next `just quickstart`,
and the setup job sets the role's password to it on every run. Until then
the demo's database had a fixed password written in the compose file. The same Postgres now starts with `pg_stat_statements` preloaded —
the recipe checks the running value and stops if it is not — which keeps
statement statistics for every database on that server, Culprit's own
included; nothing reads Culprit's.

## The quickstart leaves its fault in place

The quickstart's last step injects a fault — order-service's token for
inventory-service, re-minted for the wrong audience — diagnoses it and
posts the investigation. It does not undo it: `POST /orders` keeps failing
with a 502 until the next `just quickstart`, which mints a fresh secret and
a correct token. The token's signing secret is generated per run and kept
only in the recipe's environment, so a bare `docker compose up` of the demo
services runs with the audience check off.

## The README's captures are regenerated, and vary a little by machine

`just readme-captures` reruns the three commands behind the README's
images. It needs Go, uv and Node, and `npm ci` once in `extractors/node`;
without that last step the Node extractor exits 1 and `culprit check` on
the demo reports 4 divergences and 19 gaps instead of 5 and 17. A
regenerated image differs in small ways that are real rather than drift:
the port the throwaway probe server got, and the number of environment
variables `env capture` counted, which is the size of the environment the
script runs in (11 on the machine that made the committed ones).

## The isolation walk trusts a request probe to exercise what it calls

`culprit diagnose` bisects the request path: if a request entering at a
component succeeds, that one reading rules out the component and
everything it calls; if it fails, the fault is at or below it. That is
what makes a six-hop chain cost three probes instead of six, and a
64-component chain six instead of sixty-three (asserted by counting probe
executions, `cli/internal/isolate`).

The premise holds only if the probe sends a real request through the
component. The walk asks the endpoint's `health_path`. A shallow health
check that answers 200 without touching the component's dependencies
makes the walk rule out a branch it should have searched. The demo
services' `/health` is exactly that — it is exempt from their injected
faults — so the fault library points the walk at `/ready`, which is not.
Point `health_path` at something that exercises the request path.

## The symptom is taken as given, and a write cannot be replayed

Probes never send a request body and never write, so a failing
`POST /orders` cannot be reproduced to confirm it. The walk takes the
symptom as an assertion, tests what lies beneath it, and establishes the
`symptom_of` edge with the readings that establish the cause. The
`reproduced` criterion then means the *cause's* probe failed twice, not
that the user's request was replayed.

## One vantage per run, and some faults are only visible from inside

A probe sees the network from wherever the binary runs. Name that
component with `--from`: only from inside a component can the walk test
its outbound connections, the token it presents, or — under the `process`
adapter — its own configuration. Every such hypothesis about any other
component is recorded as *unexplored*, with the reason, and the diagnosis
is marked partial.

From inside the caller, a refused connection to a callee is equally
consistent with "the path is cut" and "the callee is down". The walk
names the edge as the root, because the edge's own probe failed, but the
rubric's `discriminated` is false, and says so. Separating the two needs a
second vantage, which arrives with the production agent (Phase 33).

## Added latency is isolated only against a declared budget

Slow is not a fault until something declares fast. Under an injected
800 ms delay every error probe passes; the walk then measures each
component's declared latency budget (see "Latency in the walk" below) and
roots at the slow one. Where no budget a `GET` request can measure is
declared, the diagnosis stays *partial* and says so — "no latency budget
… is declared" — rather than blaming the entry by elimination, and a fix
cannot be verified: there is no failing reading to see fixed. Culprit
never chooses a budget for you, and impedance's baseline is not used as
one.

## Contract checks need a route with no path parameter

The walk tests a contract by asking whether each route a caller declares
calling is served (`probe.http.route_conformance`). On a route with a path
parameter (`GET /stock/{sku}`) the probe cannot tell a missing route from a
missing item — both answer 404 — so it is inconclusive, the hypothesis is
unexplored, and the diagnosis is partial. Only parameter-free routes are
checked. (The demo's stock route takes the sku as a query parameter for
this reason.) Contract hypotheses come from `calls` facts; a caller whose
client calls were not extracted contributes none.

## Which auth faults the walk can see

An audience mismatch is tested only when the environment names the
variable holding the token a component presents
(`environments.<env>.components.<caller>.tokens`) *and* something declares
the audience the callee expects — an invariant on
`auth:<caller>-><callee>/audience`. Without both, the edge is treated as
unauthenticated and no auth hypothesis is generated. A downstream that
rejects otherwise-valid credentials (`auth_rejected`) is never tested:
`culprit.yaml` has nowhere yet to say which protected URL to present a
token to. Reading the token is reading a credential, so it needs
`config.inspect.values` naming that exact key —
`config.inspect.values: [order-service/INVENTORY_TOKEN]` (Phase 33; until
then it was `config.read.values`, which no longer counts: a `culprit.yaml`
written for the older binary now has the audience hypothesis refused until
the grant is renamed). Without it the probe
is refused, the audience hypothesis is left *unexplored*, and the diagnosis
is partial and names the missing grant; a grant for any other key does not
count. With it, the token is read from the agent's own environment by the
probe itself and never appears in a reading or an investigation — only its
audience, issuer and expiry do.

## The walk follows one branch, and edges back up the path are ignored

The request path is a tree built breadth first from the entry: an edge
back to a component already reached (the demo declares
`inventory-service -> order-service`) is not followed, because a request
entering at the entry does not travel it. At a fan-out the walk descends
into the first failing child in name order. **It stops at the first root it
can establish and does not look for a second, independent fault**: a second
fault in another branch, at the same time, is not found. A complete
diagnosis means nothing the walk *needed* went unexplored — not that every
hypothesis was tested. The report lists the hypotheses it did not need as
*untested*, apart from the *unexplored* ones it needed and could not test.

## Investigation budgets

One `culprit diagnose` runs at most **40 probes** and **2 minutes** by
default, counting the reproduction and counterfactual runs.
`isolation.max_probes`, `isolation.max_wall_clock` and
`isolation.environments.<env>.max_probes` change that; where both a global
and a per-environment cap are set, the tighter wins. A walk that reaches a
limit stops: the hypothesis it was about to test is unexplored, with the
limit as its reason, and the diagnosis is partial. Hypotheses on branches
it never needed stay `open` — not tested, and not claimed either way.

## An empty variable counts as set

`probe.config.present` — and so the walk's config hypotheses — reads
*membership* of a variable in the environment, not whether its value is
empty. `PAYMENTS_PROVIDER_KEY=` passes. (The fault library's config fault
removes the variable rather than blanking it, for this reason.)

## Locally, `go test` does not notice the catalogue mirror changing

`TestTheAPICatalogueIsGeneratedFromTheBinary` reads
`api/app/readings/catalogue.json`, which is outside the Go module, and Go's
test cache does not track it: after editing that file by hand, a cached
`go test` still reports the old result. CI always runs fresh. Locally, use
`go test -count=1`, or regenerate with `just probe-catalogue` rather than
editing.

## A stored investigation is final

`POST /investigations` stores an investigation once. Posting the same `id`
again answers `409`, and nothing can edit or delete one: `investigation-writer`
has INSERT and nothing else, and no endpoint changes a stored row. Running
`culprit diagnose` again produces a new investigation with a new id; the
older one stays. Every value in it is redacted on the way in by the same
credential heuristic as a reading's — see "The credential heuristic in a
reading is a net, not a proof" — so a credential shaped unlike anything that
heuristic knows would be stored as written.

The upload uses `CULPRIT_PROJECT_TOKEN`, the same token as facts,
divergences and readings. As with `probe-writer`, the new role bounds a
leaked *database* credential, not a leaked API token: anyone holding the
project token can post an investigation, and the dashboard will show it.
What the database does guarantee is the shape: an edge that cites no
reading, or cites a reading from another investigation, is refused however
it is written.

## The dashboard shows the newest 100 investigations

The Investigations page asks for the newest 100 and has no "load more" yet.
The API pages (`limit` up to 200, `offset`), so older ones are reachable
there. The page cannot start an investigation or run a probe — they come
only from `culprit diagnose`, run where the environment is; the control
plane has no agent to run one until Phase 33.

## A partial diagnosis names where the walk stopped, not a cause

When `culprit diagnose` cannot finish — a hypothesis was refused, no probe
could tell, a budget ran out, or nothing it tested failed — its diagnosis is
*partial*. The text output, the Investigations list and the investigation
view then show the subject the walk got to as **where it stopped**, list what
it **could not check** and why, and suggest no fix: that subject is the
deepest one the readings established, not one shown to be at fault. Only a
complete diagnosis is shown under "root". The stored field is still called
`root_subject` in the JSON and the API, for both.

Investigations stored before this wording changed (Phase 32.1) keep the
statement they were stored with — a stored investigation is final, above —
so an older partial one may still read "fails because of …" or "The cause is
inside …" in its statement. The list and the view label it as partial
either way.

The same holds for Phase 32.2's wording pass. Since then the walk names a
hypothesis kind by its label and a subject in words ("the token audience
order-service presents to inventory-service"), and no reason mentions a plan
phase. An investigation stored before then keeps its original text, which
can quote a raw kind (`auth_audience_mismatch on auth:…`) or say
verification "is Phase 34". The subject itself is still shown exactly,
in monospace, wherever the view names one.

## Text on glass is measured over the page, not over what scrolls beneath it

Every text-and-background pair in the interface is checked for WCAG 2.2 AA
contrast (4.5:1) by `scripts/tests/test_design_tokens.py`. The translucent
"glass" surfaces — the header, dialogs, tooltips, the symptom card on wide
screens — are measured composited over the page background, because that is
what is under them at rest. When the header passes over a lighter card as the
page scrolls, what is beneath it is blurred and covered at 72% opacity, which
keeps the difference small but is not separately measured. No glass sits over
the fault tree, the readings or any table.

## Connection kinds are a closed set, in the CLI as well

A connection's `kind` is one of `http`, `grpc`, `sql`, `message`, `cache`,
`dns` or `auth` — no case folding, no aliases. The control plane and the
database always refused anything else; until Phase 32.1 the `culprit` binary
did not, so a `culprit.yaml` saying `kind: queue` loaded for `culprit check`
and `culprit diagnose` and then matched no probe at all, leaving that edge
silently unexamined. It is now refused when the file loads (exit 2), naming
the component and the edge. A queue is `message`. See docs/UPGRADING.md.

## Times are shown in your browser's time zone, without naming it

Every date and time in the dashboard has one format, `4 Nov 2026, 18:18`
(day, month, year, 24-hour clock), from one formatter. It is your browser's
local time, and the zone is not printed: two people in different zones
looking at the same investigation see different clock times for it. The API
stores and returns UTC; the exact instant is in each `<time>` element's
`datetime` attribute and in the API's JSON.

## The incident timeline scrolls sideways on a narrow screen

Below about 576 px of width the timeline's service lanes could not be read
if they shrank further, so the chart keeps that width and scrolls inside its
card on a phone; the page itself never scrolls sideways. Every other page
reflows to one column instead.

## The browser tests need the whole stack, and sign-in is rate limited

`just e2e` runs against a stack `just quickstart` has started; nothing in
it mocks the API. CI builds that stack on every pull request, which makes
the `e2e` job the slowest in the pipeline. Sign-in is limited to 10 attempts
a minute per address (`api/app/auth/router.py`) and the session lives only in
memory, so the suite signs in six times per run and moves between pages
inside the app; running it twice inside a minute fails with a 429 on sign-in.
The tour of every route is one test per route (Phase 32.2) sharing one
signed-in page, so a broken route fails only its own test — but each failing
test costs one more sign-in, because Playwright starts the next test on a
fresh page. Four or more failures in one run can therefore push the rest of
the run into the rate limit, and a 429 on sign-in in a red run is a symptom,
not the cause: read the first failure. Each run also creates two users
(`e2e-member-…`, `e2e-user-…`) and creates and deletes a postmortem in the
stack it runs against — never point it at a stack whose data matters.

## Development-only dependencies still carry moderate advisories

`npm audit` reports no high or critical advisory. It does report moderate
and low ones in two development tools that never reach the dashboard image
or a browser: the `shadcn` component generator (through `deepmerge`) and
`openapi-typescript` (through `minimatch`), which generates the API types at
build time. Each fix available is a downgrade to an older major version;
they are left for the standing dependency task in `docs/HANDOFF.md`.

## A symptom edge can rest on the root's reading

Every edge in a fault tree cites the readings that established it, but not
always a reading on its own two ends. When the symptom was reported rather
than reproduced (a write the walk will not replay), nothing measured the
symptom itself, so the `symptom of` edge from the symptom to the entry
component cites the reading that established the root — the only evidence
that the entry fails. The quickstart's investigation shows this: one reading
(`probe.auth.token_shape`) establishes both its edges. The symptom card says
the symptom was not replayed; "reproduced" in the confidence rubric means the
root's failing reading was taken again and failed again, not that the
symptom was.

## There is no hosted instance, and deploy runs only by hand

The project's own server (`culprit.co.za`) was taken offline on 2026-11-05:
it had been serving an API from before Phase 14 since August. Nothing in the
repository deploys on a push any more. The `deploy` job in
`.github/workflows/ci-cd.yml` runs only when started by hand on `main`, with
its **deploy** box ticked, after every other job has passed; a push to
`main` builds, scans and publishes the images and skips the deploy. If you
run your own instance from a fork (`docs/INSTALL.md`), the same applies to
you: a merge does not reach your server until you start the deploy.

## A new advisory against a pinned dependency is found within a week

Every image is built and Trivy-scanned (CRITICAL and HIGH, blocking) on every
pull request and push, and again every Monday at 04:17 UTC on `main`
(`.github/workflows/images.yml`, which can also be started by hand). An
advisory published between those runs is not seen until the next one, so
`main` can carry a newly-known vulnerable dependency for up to a week. The
scheduled run publishes and deploys nothing; when it is red, the fix is its
own small pull request.

## The agent's audit log is tamper-evident, not tamper-proof

`culprit agent` writes every task and every probe to an append-only,
hash-chained log, and `culprit agent verify` names the first line that was
edited, removed or reordered by someone who did not also recompute the
chain. The chain has no key. Anyone who can write the file can rewrite an
entry and recompute every hash after it, and the log will still verify;
and removing the newest entries together leaves a valid chain too. So the
log catches a careless edit and accident, not a deliberate one by whoever
holds the file. Phase 33 part 2 ships every entry to the control plane's
`agent_audit_log`, which no database role can update or delete; until
then, protect the log's file the way you would any audit record.

An agent refuses to start on a log whose chain is broken. Two agents must
not share one log file: they would fork the chain, and after that neither
would start.

## The agent reads INTENT with the built-in readers only

For every task, `culprit agent` reads the system's INTENT — the
expectations probes are measured against, and the audiences and routes the
walk tests — from `culprit.yaml`, its invariants and the artefacts the
binary reads itself (OpenAPI, `.env.example`, Compose, migrations,
manifests). It never runs an extractor plugin: a plugin imports the target
project's code, which an agent on a production host has no business
running. So a fact only a plugin extracts (a route registered in code, a
client call site) is not known to an agent's walk, and a probe that needs
one says so as inconclusive.

## The agent takes tasks from a local directory, every two seconds

In this release `culprit agent` reads tasks from `<tasks>/inbox` and
answers them in `<tasks>/outbox`, polling every 2 seconds (`--poll`); tasks
run one at a time, in file-name order. There is no transport to the
control plane yet (Phase 33 part 2), so nothing in the dashboard can send
one a task.

## An agent's clock must be within five minutes of the control plane's

Every request a paired agent sends is signed with a timestamp, and the
control plane refuses one more than 300 seconds from its own clock, either
way. An agent on a host whose clock has drifted further is refused on
every request, with the same `401` as a forged one — the refusal does not
say which check failed, by design. Keep both hosts on NTP. Nonces are kept
for twice that window; a request is never accepted twice.

## An allowance can only name what the agent reported when it paired

When an agent pairs it reports the grants its configuration gives, per
environment, and an admin can allow only from that list. If the operator
later adds a grant to the agent's configuration, the control plane does
not learn of it: the agent can use it only once an allowance names it,
and an allowance cannot name it until the agent pairs again — as a new
agent, with a new id and a new key, because the control plane refuses a
second pairing of either. The dashboard says so when an investigation
needs a grant the agent does not hold. Removing a grant from the
configuration needs nothing — the agent re-reads it before every task and
runs without it.

## A revoked agent's task in flight is lost

Revoking an agent refuses its very next request. A task it had already
claimed runs to its end on the agent's host — the probes are local — but
its readings, its investigation and its result are then refused, so the
control plane keeps the task as claimed and never completed, and the
agent's local audit log is the only record of what that task did.

## Agents poll for tasks

A paired agent asks the control plane for its next task every 2 seconds
when it has none (`--poll`), one task at a time. Nothing is pushed to it —
the agent only ever connects out — so a task waits up to that interval
before it starts.

## An agent reaches its control plane over https

`control_plane.url` must be `https`. Plain `http` is refused, naming the
line, except to a loopback address (`localhost`, `127.0.0.0/8`, `::1`) or
when the configuration sets `control_plane.allow_plain_http: true` — which
`culprit agent` and `culprit agent pair` then report on stderr at every
start, and which no recipe in `deploy/agent/` sets. Every request is
signed, so over plain `http` a request still cannot be forged or altered,
but its body — task specs, readings, the pairing code while pairing — can
be read by anything on the path. CI uses `allow_plain_http`, because its
quickstart has no certificate. Give the pairing code as `culprit agent pair
--code -`, on stdin, to keep it out of shell history and the process list.

## An agent that cannot reach its control plane exits

`culprit agent` stops on any error from its task source — the control
plane unreachable, a refusal, a result it could not deliver — rather than
retry inside the process. Every recipe in `deploy/agent/` restarts it
(`restart: unless-stopped`, `Restart=on-failure` after 10 s, a Kubernetes
Deployment), so an outage costs the time to restart. A **revoked** agent
is restarted too, and refused again on its first request each time: its
log fills with `the control plane answered 401` until you remove it. A
Kubernetes pod in that state shows as CrashLoopBackOff, not Ready.

## One agent, one key: the recipes never run two

An agent's key is its identity, and its audit log is one hash chain the
control plane also holds. Two processes with one key would write two
chains under one name, and the control plane refuses the second. So the
Kubernetes recipe is a Deployment of one replica with the Recreate
strategy, not a DaemonSet, and the Compose recipe must not be scaled. An
agent per node, or per host, is one pairing per node: its own id, key and
audit log.

On Kubernetes the key Secret is mounted with `defaultMode: 0600`, but the
kubelet adds group read for the pod's `fsGroup` (65532) so the agent's
non-root user can read it: on disk it is `0640`, owned by root and the
agent's group, which nothing else in the pod shares.

## "Last signed request" is the last one the control plane accepted

The agents screen shows when each agent last made a request its signature
authenticated: the newest nonce it spent, which the control plane keeps for
each agent however old it is. A refused request — a bad signature, a
revoked agent — is logged, never stored, so it never moves that time: a
revoked agent that is still trying shows the moment of its last accepted
request. The screen refreshes every 5 seconds. One nonce per agent ever
paired is kept for good to know this — revoked agents included — so
`agent_nonces` grows by one row per agent, not per request.

## The dashboard starts an investigation only with the reachability grants allowed

"Investigate through an agent" starts nothing unless the chosen agent is
allowed `net.tcp.connect` and `net.http.outbound` in that environment — the
reachability set in `docs/PERMISSIONS.md`, without which the walk cannot
tell whether a connection or a service fails. It checks those two only: a
walk that also needs `config.inspect.values`, `config.read.names` or
`db.metadata.read` still starts, and ends partial, naming the grant it
lacked. Only an admin sees the control; addressing a task is an admin's
action.

## The minimum grant sets are for one hop

`docs/PERMISSIONS.md` lists the smallest grant set that completes each
class of investigation — reachability, schema, auth and audience,
configuration — measured on a service and the one thing it depends on
(`cli/cmd/culprit/grantsets_test.go`). A longer request path needs, in
addition, the grants for every other edge on it: a database behind an HTTP
hop needs the reachability set as well as `db.metadata.read`.

## What a leaked agent database credential could do

The API binds every agent request to the agent whose key signed it; the
database roles do not know which agent is which. Someone holding the
`agent-gateway` role's password — not an agent's key — could delete
recorded nonces (reopening replay inside the five-minute window), claim or
complete any agent's task, and rewrite the allowance stamped on a claimed
task. The last cannot widen what an agent does, which intersects any
allowance with its own configuration. None of them can touch
`agent_audit_log` beyond appending to a chain. Treat the role passwords in
`infra/.env.prod` as you would the control plane's own.

## A modified copy must link to its own source

Every page links to its source code, as AGPL-3.0 section 13 asks of anyone
who runs a modified copy as a network service. The link is set when the
frontend image is built, from `VITE_SOURCE_URL`, and defaults to this
repository. If you change Culprit and serve it, build with your own source
URL; the dashboard cannot know what you changed.

## The quickstart still prints "Password:"

`just quickstart` pipes the generated admin password into `create_user`,
whose `getpass` prints its prompt ("Warning: Password input may be echoed.
Password:") even when it reads a pipe. Nothing waits on it: the bootstrap
step runs without a terminal (`docker compose run -T`), so the password
comes from `infra/.env.prod`, run by a person or by CI.

## Verification

`culprit verify` (Phase 34, part 1) judges whether a fix fixed what an
investigation found. What follows is what it can and cannot see.

### A verification sees names and shapes, not values

The environment before and after is compared through two captures, and a
capture records each config key's name and *shape* — type, length class,
format — never its value, unless `config.read.values` allowlists that key.
A value changed to another of the same shape (one URL for another, one
32-character token for another) is invisible to the comparison, so it is
neither a difference the fix explains nor a change underneath. A key
added, removed, or changed in shape is seen.

### A process capture sees one component's environment

With `adapter: process`, a capture reads the environment `culprit` runs in,
which belongs to the one component it runs inside (the fault library's
vantage). A config key changed on any other component is not in the
capture, so it cannot make a verdict `changed_underneath`; only the
readings can notice it. Compose and Kubernetes captures read every
component the environment lists. Endpoints declared under `endpoints:` are
not captured at all — only an endpoint declared on a component is.

### What a named change explains

`--change` takes four kinds. `config:<component>/<key>` explains a
difference on that key alone. `image:<component>` explains that
component's image and its installed packages, which ship in it — not its
config keys, even ones the image's `ENV` sets: name those too.
`commit:<sha>` explains **nothing** a capture records, because a capture
holds no commits: it identifies the fix, and the verdict then rests on the
readings and on the environment not having changed. A ref is checked for
its form (7 to 40 hex characters), never for whether that commit exists.
`action:<what was done>` is a fix that is none of the others — a firewall
rule removed, a process restarted, an injected fault cleared — in words, at
most 500 characters. It too explains nothing a capture records, and its
words are the operator's: Culprit records them and checks nothing in them.
The fault library names its three runtime fixes this way.

### Two runs is a floor, not a proof

Every reading is run twice in a row, and a result that differs between the
two makes the verdict `inconclusive`. A fault that comes and goes more
slowly than two runs of the full set — seconds, for the demo — can pass
both and be called `verified`. Running `culprit verify` again later is the
check: each verification is kept, and a later one can disagree.

### Verify must run where diagnose ran

The record names the component the walk ran inside (`--from`), and every
probe is re-run with the inputs the walk used. `culprit verify` takes
`--from` too and refuses to run unless it names the same component — but
it cannot see where it is really running, only what it is told: run from
somewhere else and told otherwise, an edge or a token probe measures what
*that* place sees, which could pass where nothing was fixed. Run it in the
same place, as the fault library does. A change to `culprit.yaml`'s endpoints after the diagnosis
does not move the re-run either: the recorded inputs are used, not the
manifest's current ones. The manifest's current *grants* are used: a grant
removed since makes its probe `refused` and the verdict `inconclusive`.

### Only whatever diagnosed an investigation can verify it

`culprit diagnose` keeps what verification needs — the investigation, the
request behind each reading, the capture before — in its state directory
on the machine that ran it; an agent keeps the same for every walk it
runs, in its own. Only that machine's `culprit verify`, or that agent's
`verify` task, can verify the investigation. An investigation stored before
Phase 34, or one only in the control plane, has no record anywhere:
`culprit verify` refuses it, and an agent asked to verify it — or one it
did not diagnose — answers `inconclusive`, saying it holds no record of
before, and measures nothing. An investigation diagnosed where the grants
allow no capture *is* kept, says so in its `verified` criterion, and can be
verified `inconclusive` at best.

### A reference environment is re-measured, not compared

A counterfactual reading taken in a reference environment (`--reference`)
is re-run there, and judged with the rest, but only the investigation's own
environment is captured before and after. A change in the reference
environment is seen only if it changes that reading.

### An agent keeps its record beside its audit log, and a lost one is lost

An agent's state directory is `state/` beside its audit log (`--state-dir`
moves it): the recipes' named volume, which already has to survive a
restart. An agent whose volume is lost, or which is re-paired as a new
agent, can no longer verify anything it diagnosed before: it answers
`inconclusive`. Nothing copies the record to the control plane — it holds a
capture, which can carry values `config.read.values` allowlists.

### An agent's capture before is not an audit entry

Every probe an agent runs is an entry in its hash-chained audit log; the
capture it takes before a walk, and again for a verification, is not. The
capture runs under the same grants as the task's probes (the agent's
configuration, narrowed by the allowance), and a capture refused for a
missing grant is recorded inside the capture, not in the log.

### An agent re-runs a reference environment's reading under no grant

An allowance is per environment, and nothing widens one. A counterfactual
reading the walk took in a reference environment is re-run by a `verify`
task under no grant at all, so it is `refused`, and the verdict cannot be
`verified`. `culprit verify` re-runs it under that environment's grants in
`culprit.yaml`. Agents' walks take no counterfactual readings today, so no
agent investigation has one.

### A diagnosis with no failing reading cannot be verified

A fix is verified by the readings that failed now passing. When the walk
found nothing failing — the demo's added latency slows every request
without failing any — there is nothing to see fixed, and the verdict is
`inconclusive`, whatever was changed.

### `culprit verify` uploads nothing; an agent's verification is stored

A verification `culprit verify` makes is printed and kept beside its
investigation in the state directory (`verifications/<id>.json`); posting
it is a separate step, `POST /investigations/{id}/verifications` with the
project token, as CI posts an investigation. An agent's `verify` task posts
its verification itself, before it reports the task done. The stored
investigation's rubric always says `verified: false` — a diagnosis is never
edited — and the dashboard shows `verified` from the newest verification
instead. Nothing in a state directory is ever deleted by Culprit; it grows
by one directory per diagnosis.

### What the API checks of a verification, and what it cannot

The control plane re-judges every verification it is given with the same
rule `culprit verify` used, and refuses one whose verdict that rule does not
reach, whose re-runs were taken before the investigation closed, whose
`was` disagrees with the stored reading, that skips a reading, or that is
stamped after its server's clock (by more than 300 seconds) or judged before
its own last run. It cannot
tell whether the runs were really measured: a verification is as honest as
the credential that posted it. An agent may post only runs that name it;
the project token, like the one that posts investigations, can post any
verification that is internally consistent.

### Verifications are append-only, and never replaced

No role, the owner included, can change or delete a stored verification: a
trigger refuses it. A wrong one — the source mislabelled, say — stays, and
a later verification is recorded beside it; the newest is what the page and
the accuracy count use. The table grows by one row per verification.

### Whether a fault was planted is whoever asked saying so

`GET /outcomes/accuracy` counts planted faults (a drill, the fault library)
apart from faults on a real system, and that label is the one the person,
the task or CI gave when asking for the verification — required, never
defaulted, and never checked. A drill posted as `real` is counted as real.
The first verification of an investigation fixes its label: a later one
that says otherwise is refused, so one investigation is never counted both
ways.

### Accuracy is counted per investigation, from its newest verification

An outcome is the newest verification of an investigation whose diagnosis
is complete. A wrong fix verified `not_resolved`, then the right one
`verified`, counts once, as `verified`: it measures whether the diagnosis
led to a fix, not how many tries the fix took. Partial diagnoses are never
outcomes; their count is reported beside the others.

### A fault class is the kind of thing the root is

The class is the subject kind of the diagnosis's root — `auth`,
`connection`, `http`, `config`, `component`, and the rest. It is coarse:
every config fault is one class, whatever key; an error rate and a crash
inside the same service are both `component`. Nothing finer is inferred.
And it is the class of the root the walk *diagnosed*: a fault diagnosed at
the wrong root, then fixed, is counted under that root's class. A
`verified` outcome shows the fix for the diagnosed root was seen to fix
what the walk saw failing — not that the diagnosis named the true cause.

### The README's number is five planted faults

The README's accuracy section is rendered by `just accuracy-readme` from
the fault library's committed results (`cli/testdata/faultlib/
results.json`), which CI's fault-library job must reproduce exactly. It is
one fault per class, planted in Culprit's own three demo services, and a
sample that size says the loop works on the faults it was built against —
nothing about faults on anyone's real system. The two partial diagnoses
(`latency`, and the audience fault under narrower grants) are listed and
not counted; the library's deliberate wrong fixes are not outcomes.

### The state directory holds what a capture holds

`$CULPRIT_STATE_DIR`, else `$XDG_STATE_HOME/culprit`,
`~/.local/state/culprit`, or `%LocalAppData%\culprit` on Windows — never
the repository. Its files are created readable by their owner alone
(`0600`, in `0700` directories; Windows applies its own ACLs instead). The
capture before is the same envelope `culprit env capture` writes, so it
carries the literal value of any key `config.read.values` allowlists.

## The agent surface

`culprit mcp` (Phase 35 part 1) serves the binary's diagnostic tools to a
coding agent over MCP. What it does not do, and where it is narrower than it
may look:

### stdio only, one client, one request at a time

The only transport is the process's stdin and stdout: a coding agent starts
the binary, and nothing can reach it any other way — no socket, no HTTP
transport (Phase 35 field 17; the binary opens no listener). Requests are
answered one at a time, in the order they arrive, so a `culprit_diagnose`
that walks for its whole budget holds the next call until it finishes.
`notifications/cancelled` is read and ignored: a call already running is
answered when it ends. Tools only — no resources, prompts or sampling; the
protocol revisions spoken are 2025-06-18, 2025-03-26 and 2024-11-05. One
message is at most 1 MiB.

### The vantage and the state directory are the server's

`--from` and `--state-dir` are set when the server starts, never by a tool's
arguments: probes see what their vantage sees, and a verification is refused
from anywhere but where the diagnosis ran (see "Verify must run where
diagnose ran"). So one server serves one vantage. A fix that recreates the
container the server runs in ends the session with it; a new session
verifies, reading the investigation from the state directory — which must
outlive the container (a volume) for that to work. The fault library copies
it out and back.

### Any declared environment can be named

A tool's `environment` is any environment `culprit.yaml` declares, and its
grants are that environment's, exactly as for the CLI. An agent cannot add a
grant, but it can name the most permissive environment in the file. To bound
what an agent can reach, give its server a `culprit.yaml` that declares only
the environments it may use.

### Grants are fixed when the server starts

A coding agent can usually edit the repository, `culprit.yaml` included. So
the server records the file's digest when it starts, and once the file has
changed it refuses every call until it is restarted: an agent cannot grant
itself a capability by editing the file between two calls. Restarting it is
a person's act — or the agent's, if the agent is the one that starts the
binary. Where that matters, keep the server's `culprit.yaml` somewhere the
agent cannot write.

### Where a probe may go: bound for an agent, not at a terminal

Through `culprit mcp` (Phase 35 part 2, Q23), a probe's address inputs —
`url`, `base_url`, `host` and `port` — must name an endpoint the environment
declares (`endpoints:`, or a component's own `endpoint:`). Anything else — a
cloud metadata address, an undeclared host, an undeclared port on a declared
host, a URL carrying credentials, a port with no host, a scheme other than
`http` or `https` — refuses the whole call before anything is dialled, with
the input and the reason. `culprit_diagnose` already placed its probes from
`culprit.yaml` alone.

A redirect is bound the same way: an HTTP probe run through `culprit_probe`
follows a redirect (at most three) only to a declared endpoint, and stops
at any other — so a declared service that answers 302 cannot carry the
request somewhere undeclared.

What the binding does not hold:
- **It binds names, not addresses.** A declared host is compared as written,
  case aside: `payments.internal.` (an absolute name) or one with a space is
  refused rather than taken for `payments.internal`, because it may be a
  different machine. What a declared name resolves to is DNS's answer at the
  vantage; a hostile record for a declared name is not caught.
- **It binds these four inputs.** Every catalogue probe that dials takes its
  address through them, and a test fails when a catalogue probe takes an
  input name nobody has classified as an address or not one. The catalogue
  `culprit mcp` serves is the built-in one, compiled in: no probe can be
  installed into it, so there is no third-party probe to bind. (Phase 35's
  close-out; `--no-plugins` governs extractor plugins, which read INTENT,
  not probes.)
- **Declare what an agent may reach.** An endpoint declared for the walk is
  also one an agent may probe directly.

`culprit probe` from a terminal is unchanged: its inputs go where they say.
Under `net.http.outbound` it can send a GET to any address the vantage can
reach, and under `net.tcp.connect` open a connection to any port — nothing a
person at that terminal could not do with `curl`.

### An error says what the command would have said

A call that could not run returns the error the command would have printed —
to stderr there, into the agent's context here. That text can name local
paths: the state directory, culprit.yaml's location. It never carries a
config value or a reading's content.

### Read-only means the system under test

Every tool is offered with `readOnlyHint`. `culprit_diagnose` and
`culprit_verify` still write to the server's own state directory — the
investigation, its record, the capture before and each verification — as the
commands do; nothing else.

### Refused before anything is sent is per capability

`culprit_probe` refuses the whole call when the environment does not grant a
capability one of the named probes declares, before any probe runs. A
capability granted per item (`config.inspect.values`, `config.read.values`,
`process.exec.allowlist`) passes that check when any item is granted; whether the
probe's own item is allowed is decided when it runs, and an item not on the
list comes back as a `refused` reading — read from no network, as for the
CLI.

### Answers are JSON, never prose

Each answer is the structured result its command's `--format json` prints;
the text content is that same JSON, for a client that reads content only.
Nothing in the binary calls a model, so there is no prose field to be
missing when there is no model. A diagnosis or verification is kept in the
state directory and uploaded nowhere: posting it to a control plane remains
the CLI's and the agent's job.

## Narration

Phase 35 part 2. An optional narrator writes prose for a stored
investigation, shown beside it on its page, labelled as derived. Off by
default (`LLM_PROVIDER=none`); the README's "Narration, if you want it" says
how to turn it on, and `docs/PERMISSIONS.md` exactly what is sent.

### The check holds identifiers, not meaning

A narration is refused when it cites an item not in its evidence list,
names a subject, reading id, probe id, capability, component or code-form
verdict the investigation does not hold, carries a URL, or holds a
character outside plain text. That is all the check can see. Prose can still say something false about evidence it cites
correctly — "the token was missing" where the reading says its audience was
wrong — and it will be shown. The evidence is beside it, in the record's
own words, for that reason; read the prose as a summary of the page, never
instead of it.

### A component's name is seen only in some forms

The check recognises a component written as a subject
(`component:payments`), in backticks, or as a hyphenated name with a
component word or a digit in it (`billing-service`, `orders-db`, `db-2`).
A component named as one plain word — "payments" — is indistinguishable
from English and is not checked. Ordinary hyphenated English passes
(`read-only`, `re-run`), but a phrase with a component word in it
(`web-based`, `api-driven`) is taken for a name and refuses the narration —
the safe failure.

### A held subject is accepted only whole

`http:order-service/POST /orders` in the investigation does not let
`http:order-service/POST /refunds` through: a subject is matched whole, and
the fragment left over is named. A subject the prose truncates or
reformats is refused, even when a person would read it as the same thing —
`Component:order-service` included: subject kinds and reading ids are
recognised in any case, so a capitalised one the record does not hold
verbatim is refused, and so is an ordinary word shaped like a reading id
(`S3`, `EC2`).
Refusal is the safe failure: the evidence is still on the page.

### What counts as a URL

A scheme (`https://…`), a protocol-relative `//host`, `www.…`, `data:` and
`mailto:`, a dotted host followed by a path, a query or a backslash
(`evil.example/x`, `evil.example?d=…`, `evil.example\x`), and a dotted host
with a port (`evil.example:8080`) are refused. A bare domain
(`evil.example`), one written with a non-ASCII full stop (`evil。example`),
and an HTML attribute that names no URL (`<img src="x">`) are not: none can
carry data anywhere while the prose is shown as text, which it always is.
Faithful prose that repeats a `host:port` from a reading's reason is
refused too — the safe failure.

### Plain text only: English, in ordinary characters

The prose may hold printable ASCII, newline, tab, curly quotes, en and em
dashes, an ellipsis, the two arrows, the signs for times, almost equal, at
most, at least, plus-minus, degree and micro, and the no-break space —
nothing else (`PLAIN_CHARACTERS`, close-out of Phase 35). Any other
character refuses the narration, named "a character outside plain text".
An en or em dash between two letters or digits is read as a hyphen, so
`payment–service` is held to the component rule as `payment-service` is.
This is an allowlist because a list of what to refuse is never finished: a
zero-width character, a combining mark, a blank filler or a look-alike
underscore (U+FF3F, U+02CD, U+2017) can each make `not_resolved` appear on
the page as a verdict the investigation does not hold, and closing one
category leaves the next open.

What this costs:
- **The narrator writes English.** Prose in another script, accented
  letters (`é`), an emoji, or a currency sign other than `$` is refused —
  the safe failure; the evidence is still on the page. The prompt says so.
- **A record that holds such a character cannot be quoted.** A reason or a
  description with a non-ASCII character in it is refused if the prose
  copies it; cited by number (`[12]`) it is shown, because a citation is
  replaced by the record's own text, which the check does not judge.

### What a refusal names is a word, not the model's sentence

A refused narration stores and shows what it named, each item a single
token with no whitespace, in plain characters, or a fixed label ("a URL",
"a character outside plain text", "a name in code form", "a credential",
"a name that cannot be shown"), and at most 80 characters. The API applies
the same rule again to every refused row it serves, so a row the table's
owner inserts naming a sentence, a URL or a key is shown as labels. A
token can still be up to 80 characters of the model's own text joined by
underscores or hyphens. "No credential" means nothing the shared credential
pattern (`redact_credentials`, and its Go twin) recognises: a key of a
shape it does not know — `password=hunter2`, a Slack token, `user:pass@host`
with no scheme — is served as a token like any other word.
For a name written in backticks only its first unknown word is named, so
a sentence in code form is never shown. At most 20 are kept.

### URLs are refused even when the investigation holds one

A symptom description can carry a URL (`POST http://order-service:8001/orders`).
The narrator is told not to write one, and a narration that does is refused
all the same: a link or an image in model output is a way out for data.

### Three attempts, then the last status stands

Each investigation is narrated at most three times. A failed or refused
attempt is retried no sooner than `NARRATOR_RETRY_SECONDS` later (60 by
default); the third's status is final. There is no button to narrate
again. Narrations are append-only — a new provider or model does not
re-narrate what is already complete.

Every call is counted as an attempt. One whose row the database refuses is
stored as failed, "the narration could not be stored", so the provider is
not called again for it; a call goes uncounted only when the database can
take no row at all, and then nothing is narrated. The count and the retry
interval are both read again once an attempt is claimed, so two ticks that
both found an investigation due make one attempt, not two.

### The newest investigations first, a few at a time

The job narrates at most three investigations every 15 seconds, newest
first. Turning narration on narrates the whole stored history, eventually,
starting from the newest; with a slow local model that can take a while,
and each one is a call to the provider. With `anthropic`, every stored
investigation's evidence leaves your machine, not only the next one's.

### Nothing is pending, but "not narrated yet" can last

The page shows off, not narrated yet, complete, failed or refused. "Not
narrated yet" means no attempt has finished: a provider that never answers
holds an investigation there until the attempt times out
(`NARRATOR_TIMEOUT_SECONDS`, 60 by default), then it is failed.

### A failure says little, on purpose

A failure's reason is Culprit's own words: the provider, and the HTTP
status, or that it timed out, answered nothing, answered something that is
not its API's shape, or declined. The provider's own error text is never
read, so a useful detail in it is lost along with any secret.

### One request, no tools, and a fixed budget

Each attempt is one request: no tools, no streaming, no second call to ask
for more. A reply may be at most 4000 tokens — `max_tokens` with
`anthropic`, `num_predict` with `ollama` — the same number as the 4000
characters a narration may hold. A token is usually several characters,
so a reply can still run past 4000 characters and be paid for; the bound
keeps that within a few times what could be kept. English short enough to
keep is not cut off. One cut off at the limit (or, with
`anthropic`, declined) is a failure. A reply longer than 4000 characters is
a failure too, not truncated.

### Prose is shown as text

Markdown and HTML in a narration appear as the characters they are: no
bold, no list, no link, no image. Line breaks are kept.

### Only the worker holds the provider's key

`ANTHROPIC_API_KEY` is set empty for the api service in both Compose files,
so `.env.prod` gives it to the worker alone. A deployment that does not use
these Compose files passes `.env.prod` as it chooses.

### Settings are read when the worker starts

`LLM_PROVIDER`, `NARRATOR_MODEL`, `OLLAMA_URL` and `ANTHROPIC_API_KEY` are
read once, and a half-set provider (no model; anthropic with no key; ollama
with no address) stops the worker at start. Changing them needs a restart
of the worker, and of the api, which reads `LLM_PROVIDER` only to say
whether narration is off. If only one of them is restarted the two can
disagree: an api that thinks narration is on beside a worker that has it
off says "not narrated yet" for ever. Turning narration off does not hide
what was already narrated: a stored narration is still shown, and "off" is
said only for an investigation with none.


## Latency budgets

Phase 36. A latency is a finding only against a declared budget
(`budgets:` in `culprit.yaml`, or `x-culprit-budget` on an OpenAPI
operation), measured by `probe.http.latency` (`docs/PROBES.md`). Since
part 2 the walk asks about latency too; "Latency in the walk" below says
how, and what it cannot tell.

### Only GET routes, and only ones that need no credential

The probe sends `GET` and nothing else. A budget on a `POST`, `PUT` or any
other route is `inconclusive`, with nothing sent: an `OPTIONS` request is
answered by CORS middleware before any handler runs, so its time says
nothing about the route. No probe presents a credential, so a route that
needs a token answers 401, which is not a sample, and its budget is
`inconclusive` too. The demo's `GET /stock` is such a route, which is why
its budget is on `GET /ready`.

### 90% confidence, and what it costs a p95

Each verdict holds at 90% confidence on each side (`CONFIDENCE` in
`culprit_model/latency.py`, `LatencyConfidence` in Go). At 90%, a p95 can
be shown within budget only from 45 samples, so a p95 budget **passes only
when the slowest of its 50 samples is within it**. One slow request or one
timeout leaves it `inconclusive`, not failed. A p50 is judged from 20
samples, between the 7th and 14th slowest. There is no separate limit on
how wide the interval may be: any such limit would be a number Culprit
chose.

### A fixed, small number of requests

50 requests for a p95 budget, 20 for a p50, one at a time, at least 50 ms
apart. Nothing configures the count or the spacing — no input, no
`probes:` setting — and 50 is a hard cap in the probe. Naming the probe
twice (`-p probe.http.latency -p probe.http.latency`, or twice in
`culprit_probe`'s list) runs it once, and two latency runs in one process
take turns, the 50 ms holding between them as within one. Two `culprit`
processes started at once do not know of each other: their requests can
interleave. Each request's
timeout is twice the budget plus 500 ms, cut to what is left of the
probe's own 120 s run; when what is left is no longer than the budget, the
run stops with the samples it has. A route that slow is `inconclusive`
for want of samples, and one that could not be sent a single request says
so. `culprit probe <target>` with no `-p` runs every probe, this one
included, so against a route with a budget it sends those requests.

### A budget is 1 ms to 60 s

A budget is a whole number of milliseconds, 1 to 60 000. A larger one is
refused at load — in `culprit check` and `apply-model` alike — because no
request in a 120 s run could be given a timeout long enough to show it was
slower. One subject and predicate may have one budget in a file: two are
refused at load, not one measured and the other dropped.

`culprit.yaml` is read by two YAML readers, the binary's and the API's, and
since Phase 37 part 1's close-out they read one schema: the API resolves
plain scalars as the binary's YAML 1.2 reader does (`yes` is a string, a date
is left as written, `0o454` and `1e3` are numbers), both refuse a second
document, and both refuse a top-level key the other does not know, naming it
(`shared/tests/manifest_scalar_conformance.json`). For `budgets:` the API is
also held to the binary's rules (`shared/tests/latency_conformance.json`,
`budget_manifests`):

- a key written twice in any mapping — `version:`, `budgets:`, a field of
  an entry, or two merge keys — is refused by both;
- the root's own `budgets:` is read before one a merge (`<<`) brings in, and
  the first merge before a later one; a `budgets:` that is overridden is
  read by neither, so its values are not checked;
- a merge key inside a budget entry is refused by both.

**A top-level key the binary does not know is now refused.** Until the
close-out the binary ignored one, on purpose, so that a CLI older than its
server would still run in CI; the cost was that a mistyped `budget:` was
dropped without a word, and so was a key written as the string `"<<"` or as
a `!!binary` that decodes to `budgets`. Both readers now take their
top-level keys from one list (`shared/tests/manifest_keys.json`), so a key
added to one is added to both; an older binary reading a newer manifest
names the key it does not know and stops. Within a section, fields the
binary does not read are still ignored. `why: 300` is still a number to
both readers, and refused for not being text: quote a `why:` that looks
like a number.

In `culprit.yaml` the value is written as **plain decimal digits**,
unquoted, with no sign and no leading zero: `300`. Every other form is
refused by both readers, with the same reason — `300.0`, `+300`, `0454`,
`0o454`, `0x12C`, `1e3`, `300_000`, `"300"`, a tag (`!!int 300`) or an
alias. The two readers now read those alike (`0454` is octal 300 to both,
as Go reads it), but a budget written `0454` means 454 to most people who
write one, so the form rule stays. An `x-culprit-budget` in an OpenAPI document is read by the
binary alone, as a number.

### What a sample is

A sample is a `2xx` answer or a timeout. A timeout counts as slower than
the budget — dropping it would report a service that has stopped
answering as fast. Any other answer (a 401, a 500, a redirect) or a
connection that fails outright is not a sample; enough of them leave too
few samples, and the verdict is `inconclusive`. Each request is on a new
connection, timed from dialling to the last byte, so it includes name
resolution, the TCP handshake and any TLS handshake (recorded separately as
`connect_us`). A client that keeps connections open will see less. A
response larger than 1 MiB is timed to its first 1 MiB, the read cap every
probe has, not to its last byte.

### One budget, every environment

A budget is INTENT, so a CI runner on a shared machine is held to the same
number as production. Measure where the number means something.

### When a route has both budgets

One run judges both. The route is measured once — 50 requests, as for a
p95 alone — and the run gives two readings, one per budget, each judged by
the rule from the same samples. Each request's timeout is set from the
larger budget, so a timeout is slower than both.

### What `culprit check` reports about budgets

A budget whose subject no other INTENT source declares is listed under
"Budgets that name nothing declared" — a renamed or mistyped route would
otherwise never be measured. The unbudgeted surface (routes declared with
`exists` and no budget) is listed only when the manifest declares
`budgets:` at all. An `x-culprit-budget` entry that is not a budget (an
unknown predicate, a value that is not a whole, positive number of
milliseconds) is reported as a gap under `budgets`, not dropped. A budget
does not count as a second source for the unverifiable surface.

### The probe's URL must be the budgeted route

The budget's own subject fixes the route: a `url` or `base_url` input
whose path is not that route's, or a budget on a route that is not `GET`,
sends nothing and is `inconclusive`. The path compared is the one sent,
byte for byte, segment by segment: a trailing or doubled slash, any `%`
escape, a `.` or `..` segment, a query string or a fragment is not the
route, and nothing is sent. A declared template segment (`/items/{}`)
matches one non-empty segment (`/items/42`). A URL with userinfo
(`http://user:pass@…`) is refused, because it would be sent as a
credential.

A literal route that a declared template also matches is not told apart:
with `/items/{}` budgeted, a `url` of `/items/export` is measured against
that budget even if `/items/export` is a route of its own. The walk never
does this — it asks the budgeted route itself — but a `url` given by hand
can.

Through `culprit mcp`, the address must also be the declared endpoint of
the component whose budget judges the reading (the target's component),
not merely any declared endpoint: a budget on one component is never
judged with another's times.

### What holds the GET-only rule, and what cannot

Two structural facts hold it (Q26, ruled 2026-11-12), each with a test that
shows it red:

- **The client is a package of its own** (Q27, ruled 2026-11-12):
  `internal/probe/guardedhttp`, one non-test file, the only package under
  `internal/probe` that imports `net/http`. Its exported surface names no
  `net/http` or `net` type, so code outside it cannot hold a client, a
  transport or a request — the Phase 37 part 1 audit's file, which reached
  the guard's own transport through a client's fields from a sibling file
  and sent a `DELETE`, no longer compiles in `internal/probe`, and a test
  plants it to show so.
- **Every client that file builds comes from one constructor**, which
  puts a guard under it. The guard refuses anything but a bodiless `GET` or
  `OPTIONS` as each request leaves, before anything is dialled — however
  the request was built, and whatever was done to it afterwards.

Phase 36 part 2 held this with a scan of the package's syntax instead. Three
audits in a row found code shapes it did not know, and the third sent a
`DELETE`; the scan is retired.

**It is a guard against ordinary code, not a proof against deliberate
code.** Raw bytes written to a socket that `net.tcp.connect` opened are
outside it, as is a header such as `X-HTTP-Method-Override` that a server
chooses to honour. And the package holds against code outside it, not a
change to it: code added to `guardedhttp` itself can do what `net/http`
can, which is why it is one file and a test fails if a second appears. The
binary's network allowlist names it and `internal/capture/dbsession`, and
keeps every other package from linking a network package at all.

### Latency in the walk

Phase 36 part 2. `culprit diagnose` asks about latency, and these are its
limits.

- **Only after the errors explain nothing.** The walk runs its error pass
  first, unchanged. Only when that finds no root and nothing failing below
  the entry does it measure budgets. A fault that both errors and slows is
  diagnosed by its errors; its latency is not measured.
- **One vantage.** Every latency request is sent from where the binary
  runs. Nothing is measured from inside another component, and no probe is
  sent to an agent elsewhere.
- **A pass rules out one component.** A budgeted route need not call what
  is below it (`/ready` calls nothing), so a component that keeps its
  budget rules out its own latency and nothing else. The walk measures
  every budgeted component on the request path, depth first, rather than
  bisecting — each a run of 20 or 50 spaced requests. The root is the
  deepest slow component with nothing slow below it; a slow component
  above it is propagation.
- **Hop or component, from the same samples.** The slow reading's
  connection setup alone, and each answer's time less its setup, are each
  judged against the same budget by the same rule. Setup alone over, with
  the binary inside the slow component's caller (`--from`), roots at that
  connection; the server's time alone over roots at the component. Neither
  alone over — or both — is partial and names both. From outside every
  component, slow setup is "reaching X from this agent": a fact about this
  vantage, not a connection of the system, and the diagnosis is partial. A
  timeout after its connection completed counts against the component; one
  before counts against the hop.
- **What an unbudgeted component leaves unknown.** A component with no
  budget a `GET` request can measure is not asked about. When the slow
  root has one below it, the diagnosis is partial and names it, because it
  could be the slower one. A component that is not below the root is named
  in the statement as unbudgeted, without making the diagnosis partial.
  With no budget anywhere on the request path, the diagnosis says none is
  declared.
- **A database below the slow component makes it partial.** A database can
  declare no latency budget yet (statement budgets are Phase 37), so a slow
  component that calls one on the request path is never a complete root:
  the diagnosis names the database as unmeasured, because the time could be
  spent there.
- **Two slow branches at once.** When two components on different branches
  are each slow with nothing slow below them, the first in depth-first
  order (callees in name order) is named the root and the other is listed;
  the diagnosis is partial, because one root does not explain both.
- **It takes time, and the walk's clock bounds it.** Against a route 800 ms
  slow, one run is about 45 s, and the walk takes it twice (to find the
  root, and to see it fail again for the rubric). The walk's wall clock
  (`isolation.max_wall_clock`, two minutes by default) is each latency
  run's deadline: a run cut short is `inconclusive` with the samples it
  has, its hypothesis unexplored, never judged on fewer requests than it
  planned. `culprit verify` runs it twice more.
