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
