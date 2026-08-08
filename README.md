# Culprit

Culprit is an incident-correlation copilot for small engineering teams
running a handful of services without a dedicated SRE/observability
function. Point your services' telemetry at it; it flags statistical
anomalies in error rate and latency, correlates anomalies across services
that happen close together in time, and — grounded in your own team's
past incident postmortems, never a raw guess — suggests a likely root
cause instead of a wall of unrelated alerts.

## What this is not

Culprit is not a replacement for Datadog, Grafana, or any full observability
platform — it does not store or graph everything you send it, has no
long-term metrics retention beyond a bounded window, and no general-purpose
dashboarding. It does one narrow thing: it watches for anomalies, decides
which ones probably belong to the same incident, and explains a likely
cause using your team's own history. Point it at logs and metrics you
already collect elsewhere too, if you want both.

## Five-minute local quickstart

Needs only [Docker](https://docs.docker.com/get-docker/) and
[`just`](https://github.com/casey/just) — no Python or Node install
required on your machine, even to generate secrets.

```bash
git clone https://github.com/Josh-Heath123/Culprit.git culprit
cd culprit
just quickstart
```

This builds every image locally, brings up Postgres/Redis/the API/the
worker/the frontend plus three toy demo services (order, inventory,
payments) and a load generator, registers the demo services, creates an
admin login, and prints the URL and credentials. Steady demo traffic
alone won't trigger anything — it *is* the baseline — so `just quickstart`
also schedules an automatic fault injection about 75 seconds in; a
correlated incident with a root-cause narrative should appear at
<http://localhost> within about 5 minutes. `just quickstart`'s own output
prints the command to trigger another fault yourself at any time.

`just quickstart-down` tears it down; running `just quickstart` again
reuses the same generated secrets and demo data rather than starting over.

## Running it against your own services

The local quickstart above uses fake demo services. To point Culprit at
services you actually run:

- [`docs/INSTALL.md`](docs/INSTALL.md) — deploying to your own VM with a
  real domain, TLS, and CI/CD.
- [`docs/INSTRUMENTATION.md`](docs/INSTRUMENTATION.md) — how to get your
  services' telemetry into a running Culprit instance, with a
  copy-pasteable Python example that doesn't depend on anything in this
  repo.

## A note on naming

This repository was originally named `View` — Culprit's working title
before the product name was decided — and stayed that way for a while
after, which confused more first-time visitors than it was worth. It's
since been renamed to match. If a `.../View` link brought you here,
GitHub's redirect did its job.

## License

MIT — see [`LICENSE`](LICENSE). Use it, fork it, run it against your own
services, no strings attached.
