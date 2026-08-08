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
- **One Postgres instance, several connection pools sharing it.** Each of
  `api`'s four DB roles (`api-reader`, `registry-admin`, `auth-service`,
  `postmortem-writer`) and each of `worker`'s roles
  (`ingestion-writer`, `anomaly-detector`, `correlation-engine`,
  `root-cause-writer`) opens its own SQLAlchemy connection pool in the
  same process — more services and more worker cron activity means more
  concurrent connections against Postgres's own `max_connections`
  (100 by default, unraised here). This is the first thing to look at if
  connections start getting refused under real load.
- **`raw_events` is designed to be pruned, not to grow forever** — see
  `api/migrations/versions/e2cab79bcc93_raw_events_compression_and_retention.py`
  for the compression/retention policy already in place. It's still the
  highest-volume table in the system by a wide margin; don't be surprised
  by its size relative to everything else.

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
