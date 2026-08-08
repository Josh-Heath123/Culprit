# Instrumenting your own service

This is the copyable guide for pointing a real service — yours, not the
three fixture ones this repo ships for demos — at a running Culprit
instance. It assumes nothing about this repo beyond a base URL and an
API key.

## 1. Register the service and get a key

Every service needs a row in Culprit's service registry before it can
authenticate at all — there's no open/anonymous ingest path. Either:

- **Settings → Services** in the dashboard: register a service, copy the
  API key it shows you once (it is never shown again), or
- `POST {base}/services` with an admin session token (see
  `api/app/registry/router.py`), or
- a declarative YAML file applied with `just apply-services` (see
  `api/scripts/apply_services.py` — useful if you're onboarding several
  services at once).

Pick a `name` that matches your service's real name — see step 2 for why
that match matters. You'll get back a key that looks like
`clp_live_<43 characters>`. Store it the way you'd store any other
credential; Culprit only ever stores its hash.

## 2. What Culprit accepts today

- `POST {base}/v1/metrics` — OTLP/HTTP, protobuf-encoded
  (`application/x-protobuf`), optionally gzip-compressed
  (`Content-Encoding: gzip`).
- `POST {base}/v1/logs` — same encoding.
- `POST {base}/v1/traces` — same encoding, but see the next section:
  traces are used differently from metrics and logs, and nowhere near as
  much of what you send actually gets kept.

Every request needs `Authorization: Bearer <api key>`.

`{base}` is:

- **A production deploy behind Caddy:** `https://<your-domain>/ingest`
  (Caddy strips the `/ingest` prefix before proxying — see
  `frontend/Caddyfile` — so your SDK never needs to know the gateway's
  own paths are `/v1/metrics` and `/v1/logs` without that prefix).
- **Local/dev, talking to `ingest-gateway` directly:**
  `http://localhost:8010`.

### `service.name` is the payload, but the API key is the tenancy boundary

Set your OTel `Resource`'s `service.name` to *exactly* the name you
registered in step 1 — same case, same punctuation. If it doesn't match,
nothing breaks and you won't get an error: the telemetry still gets
accepted, but it's attributed to whichever service *the API key* belongs
to, not whatever `service.name` the payload claims. That's deliberate
(`api/app/ingest_gateway/auth.py`'s `authenticated_service_name` is what
actually decides attribution) — the key is the real multi-tenant
boundary, the payload's own claim about itself is not trusted. Practical
effect: a mismatched `service.name` means your data quietly lands under
the wrong service's timeline lane instead of its own, which is a
confusing thing to debug if you don't know to check for it.

### Traces are for topology inference only — Culprit is not a tracing backend

Culprit never stores a span. A trace export is decoded into edge
*observations* — which service called which, nothing else — the moment
it arrives, and only that pair of names survives. No span IDs, no
attributes, no timing, no trace ID. If you're expecting to search or
visualize traces here, you won't be able to: point Tempo, Jaeger, or
whatever you already use at your real tracing backend for that, and
point Culprit at it in parallel if you also want topology inference.

What those edge observations are *for*: today, the services one incident
correlates across are declared by hand (Settings → Services, or the
registry API). Sending traces lets Culprit propose dependencies it
actually observed instead — a "Suggested dependencies" panel under
Settings → Services shows each one with how many times it's been seen,
with Accept and Dismiss buttons. Nothing changes correlation until you
accept a suggestion; an unaccepted suggestion sitting there does nothing.

For this to produce anything, your own instrumentation needs to create a
`CLIENT`-kind span around each outbound call, with a `peer.service`
attribute set to the callee's registered name — the OTel auto-
instrumentation packages for most HTTP clients do this for you. Context
propagation alone (an inbound span that happens to nest under an
upstream caller's span) is not enough; Culprit reads the `CLIENT` span's
own attributes, not the parent/child relationship. If a peer can't be
resolved from `peer.service` or a `server.address` attribute, that span
just doesn't produce an edge.

## 3. Which metrics are worth sending

Anomaly scoring (`worker/app/anomaly/`) is metric-agnostic — it builds an
independent rolling z-score per `(service_name, metric_name)` pair, so it
has no built-in opinion about which metric names matter. Start with:

- Request duration (a latency metric)
- Request/error count (a volume or error-rate metric)

The OTel semantic-convention names are a reasonable default:
`http.server.request.duration`, `http.server.request.count`. The demo
services in this repo deliberately use `demo.http.server.*` instead,
specifically so demo traffic is never confusable with real traffic in
shared environments — you don't need to follow that convention yourself.

Once you trust the baseline, add more metrics via that service's
`monitored_metrics` (Settings → Services, or the registry API) — an empty
list means "score every metric this service sends," which is the
simplest starting point and exactly what you get by doing nothing.

## 4. A quiet dashboard for the first minute is expected

The z-score scorer needs history before it can flag anything as
unusual — a service that's been reporting for 30 seconds will show
nothing, and that is correct behavior, not a broken install. Give it a
minute or two of steady traffic before deciding nothing's working.

## 5. Any OTel SDK, any language

Culprit's ingest path is standard OTLP/HTTP, so any language's OTel SDK
works without a Culprit-specific client library. Point the standard env
vars at it:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://<your-domain>/ingest"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20clp_live_your_key_here"
```

(The `%20` is a URL-encoded space — `OTEL_EXPORTER_OTLP_HEADERS` is a
comma-separated `key=value` list per the OTel spec, and a literal space
in a value has to be encoded.)

See `examples/instrument_python.py` for a complete, standalone Python
example — copy it, don't import anything from this repo. If you already
run an OpenTelemetry Collector, see
`examples/otel-collector-config.yaml` for an `otlphttp` exporter block
instead of instrumenting each service directly.
