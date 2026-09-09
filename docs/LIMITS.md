# Limits

Honest constraints, not hidden ones — a product that states its limits is
more trustworthy than one that implies it has none. These are the ones
worth knowing before you depend on this for something real.

## Scale

This project targets one self-hosted VM on the shape of an Oracle Cloud
Always Free instance (2 OCPU / 11 GB, `CLAUDE.md`'s Production deployment
section) — not a cluster, not autoscaling. Rough guidance, not a
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
- **One Postgres instance, ten least-privilege roles sharing it.** `api`
  opens a pool per role it uses (`api-reader`, `registry-admin`,
  `auth-service`, `postmortem-writer`, `ingest-gateway`), `worker` does the
  same (`ingestion-writer`, `anomaly-detector`, `correlation-engine`,
  `root-cause-writer`), and `mcp_server` adds `mcp-reader` if you run it.
  More services and more worker cron activity means more concurrent
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

Ingestion transport is Redis Streams (`CLAUDE.md`'s scope discipline
section), not Kafka. This is the right choice for the scale this project
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

## The root-cause narrative is a grounded hypothesis, not a verdict

The LLM call (`worker/app/rag/`) only ever runs after retrieval has
grounded it in your own team's past postmortems — see `CLAUDE.md`'s
"Where the AI must stay deterministic" section for why anomaly detection
and correlation never touch an LLM at all. Even grounded, it's a
hypothesis a human should read critically, not an authoritative
diagnosis: retrieval can surface a similar-looking but wrong past
incident, and a corpus with only a handful of postmortems in it has
correspondingly little to ground against. Confidence level and cited
evidence are shown specifically so you can judge that for yourself
instead of trusting a bare paragraph.

## RAG retrieval quality depends on your postmortem corpus

`worker/app/rag/retrieval.py` always returns its top 3 most-similar
postmortems by embedding distance — there's no relevance floor. With a
small corpus, or one whose postmortems don't share a consistent
structure, "most similar" can still mean "not very similar at all." Voyage's
free tier also caps at 3 requests/minute (`docs/SELF_HOSTED_PLAN.md`
Phase 18) — a burst of postmortem writes degrades to a visible "failed,
retry" state rather than hanging, but it does mean a burst takes real
wall-clock time to fully embed.

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

## A cited passage is checked for existence, not for relevance

Every citation in a root-cause narrative is now verified before it is
stored: the quoted passage must actually appear in the postmortem it is
attributed to (whitespace-normalised, so a re-wrapped line still counts).
Citations that fail are dropped and counted, not repaired — there is no
correct passage to substitute for a fabricated one.

So a citation you see is genuinely present in the postmortem it names. That
is not a guarantee that the passage is *relevant*, that the postmortem
describes your incident, or that the surrounding hypothesis is right — see
the section above on the narrative being a hypothesis. A narrative may also
arrive with fewer citations than the model offered, or with none.

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
- **The shape is coarse, and that costs you real findings.** There is no
  `scheme` field, so a `DATABASE_URL` pointing at `postgresql://` in
  staging and `mysql://` in production has the *same shape* and no
  divergence is visible. Same for a hostname change, a port change, or
  any two secrets of similar length. Shape comparison catches "set versus
  unset", "empty versus populated", "a DSN where a bare hostname was
  expected" and "credential-shaped where it should not be" — not
  "pointing at the wrong thing". The field set was fixed by decision
  (docs/HANDOFF.md §2, 2026-09-09); widening it is an architecture
  decision, not an implementation one.
- **`intent_facts` carries the same three constraints now.** Phase 28
  gave it `value_shape` and `grant_ref` too, because an INTENT extractor
  reading `.env.example` or an `os.environ.get("PORT", "8000")` default
  genuinely has a shape to report about what a key is *supposed* to
  hold — 32 of the 64 config facts a capture of this repository produces
  are exactly that. Without the columns they were accepted and stored
  with the shape discarded while the response reported them saved. That
  matters more than the `configured_facts` version: `intent_facts` is the
  table an unattended CI credential can actually INSERT into today.
- **The grant mechanism itself does not exist yet.** `grant_ref` is a
  free-text column; nothing validates that the grant it names is real,
  because capability grants are Phase 31's work. Phase 28 closed the
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

The tables remain empty until Phase 27, so none of this affects a running
deployment yet.

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

## The `/services` API is an alias, and it flattens the model

Everything under `/services` still works after Phase 27, and is what the
dashboard's service list, `docs/INSTRUMENTATION.md` and any script you
wrote against it still call. It is a translation layer over
`components`/`connections`, retained for one release and removed in Phase
30.

It cannot express the model, and silently narrows it:

- **`depends_on` shows only `http` connections.** A `sql` connection to a
  database, a `message` connection to a queue or a `cache` connection
  simply does not appear in a `GET /services` response. They exist, they
  are in the graph, and correlation reads them — this surface just has
  nowhere to put them.
- **`PATCH /services/{id}` with `depends_on` rewrites only the `http`
  edges.** That is deliberate: a legacy client that has never heard of
  connection kinds must not delete a `sql` edge it cannot see. The
  consequence is that the old API can no longer fully describe a
  component's connections, so a script that "sets" `depends_on` is setting
  a subset.
- **Everything it creates is `kind: service`.** The old shape has no field
  for a component's kind, and inferring one from the name would be a
  guess. Correct it in **Settings → Services**, via
  `PATCH /model/components/{id}`, or by declaring it in `culprit.yaml`.
- **A legacy `depends_on` write flattens `declared_by` to
  `culprit_yaml`.** `PATCH /services/{id}` rewrites that component's
  `http` edges, and the old shape cannot say where an edge came from — so
  an edge that had been an *accepted topology suggestion* comes back
  labelled as hand-declared. That matters because `apply_model` treats
  `culprit_yaml` edges as owned by the manifest and removes ones the file
  no longer lists, while leaving accepted suggestions alone. An accepted
  suggestion touched by a legacy PATCH can therefore be removed by a
  later `apply` that would previously have spared it. Use
  `PATCH /model/connections/{id}` instead, which preserves provenance.

Use `/model/*` for anything new.

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

## Correlation groups incidents across every connection kind

`worker/app/correlation/job.py` builds its adjacency from `connections`
with **no filter on `kind`**. Two components joined by a `sql`, `cache`
or `message` edge are as "related" for incident grouping as two joined by
`http`.

At upgrade time this changes nothing — every migrated connection is
`http`. It starts to matter the first time you declare a non-HTTP edge:
declaring `orders-svc -sql-> orders-db` makes an anomaly in each of them
correlate into one incident candidate, where before Phase 27 there was no
way to express that edge at all.

This is deliberate for now. `docs/DIAGNOSTIC_PLAN.md` D5 says the
undirected correlation engine is *replaced* in Phase 32, not adapted —
its central data structure is an `nx.Graph`, and teaching it half a
notion of direction and kind would change correlation behaviour in a
phase whose first acceptance criterion is that nothing is lost. The same
applies to topology suggestions: an observed HTTP edge is no longer
suggested once a connection of *any* kind already joins that pair.

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
