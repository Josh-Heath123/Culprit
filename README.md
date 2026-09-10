# Culprit

Culprit finds the places where your system disagrees with itself.

It has two halves. **`culprit check`** compares everything your
repository says about itself — route tables, specs, call sites,
migrations, config keys — and reports the contradictions, in CI, with no
environment access and no account. That is the half you can use sixty
seconds after installing it, and it is what most of this README is about.

The other half is an **incident-correlation copilot** for small teams
without a dedicated SRE function: point your services' telemetry at it
and it flags statistical anomalies in error rate and latency, correlates
them across services in time, and — grounded in your own team's past
postmortems, never a raw guess — suggests a likely root cause instead of
a wall of unrelated alerts.


## `culprit check` — find faults in a repository, in CI, in seconds

Culprit reads everything your repository already says about itself — the
route table your application registers at startup, the `openapi.json` you
committed, the calls your frontend makes, the columns your ORM declares,
the columns your migrations create, the keys your code reads out of the
environment, the keys your `.env.example` declares — and reports where
two of them disagree.

No agent, no telemetry, no account, no environment access. It runs in a
pull request on a fork with no secrets.

```console
$ culprit check
5 divergence(s)

  [breaks_request_path] config:billing-api/BILLING_WEBHOOK_SECRET
      billing/config.py refers to BILLING_WEBHOOK_SECRET, which billing/.env.example does not describe
      true                                       billing/config.py L9 (rank 60)
      false                                      billing/.env.example (rank 80)
      why breaks_request_path: billing-api is an entry point, and the key is read

  [breaks_request_path] http:orders-api/GET /api/v1/orders/{}
      orders_api.main:app and openapi.json disagree about status_codes
      ["200","422"]                              orders_api.main:app $.paths./api/v1/orders/{order_id}.get (rank 90)
      ["200","404"]                              openapi.json $.paths./api/v1/orders/{order_id}.get (rank 80)
      why breaks_request_path: orders-api is on the request path from web

  [breaks_request_path] http:orders-api/GET /api/v2/orders/search
      src/api/orders.ts refers to GET /api/v2/orders/search, which orders_api.main:app does not describe
      {"method":"GET","path":"/api/v2/orders/se… src/api/orders.ts L33 (rank 40)
      false                                      orders_api.main:app (rank 90)
      why breaks_request_path: orders-api is on the request path from web

  [breaks_request_path] schema:billing-api-db/public.invoices
      main:app and migrations/versions disagree about columns
      ["created_at","id","reference","total_cen… main:app public.invoices (rank 90)
      ["created_at","id","reference"]            migrations/versions public.invoices (rank 80)
      why breaks_request_path: billing-api-db backs a component on the request path

Not checked (17) — these are gaps, not clean results
  billing-api        http_routes      no OpenAPI or Swagger document found under .
  billing-db         *                billing-db has no source root: nothing was extracted for it.
  orders-db          *                orders-db has no source root: nothing was extracted for it.
  web                http_routes      no app.get/router.post-style route definition with a literal path found
  …
```

That is real output, not a mock-up. It comes from `cli/testdata/demo`, a
three-component repository in this tree: a FastAPI service, a React
frontend and a small billing service with two faults planted in it. Run
it yourself with `just cli-test` (it is an assertion in the test suite)
or reproduce it directly:

```bash
cd cli && go run ./cmd/culprit check -f testdata/demo/culprit.yaml
```

### And on a repository nobody planted anything in

Culprit checks itself on every pull request. This one is a real
multi-language system — a FastAPI API, a React dashboard, an arq worker,
a 24-revision migration chain:

```console
$ just self-check
No divergences. 983 fact(s) compared across 432 subject(s).

Not checked (9) — these are gaps, not clean results
  culprit-api    client_calls   culprit-extract-python@0.1.0 does not extract client_calls
  culprit-api    config_keys    no docker-compose file found
  culprit-api    http_routes    no OpenAPI or Swagger document found under .
  culprit-db     *              culprit-db has no source root: nothing was extracted for it.
  …

$ just self-check-coverage
Unverifiable surface (349)
  Subjects only one source describes, so nothing could ever contradict them.
  Not defects — places where a mistake would go uncaught (§0.1).
```

Getting that zero honestly took two rounds of fixing the tool rather than
the repository — five false positives, each a case where two facts that
were both true had been given the same name. It also found one real
defect in this repo on its first run: two config keys the ingest gateway
reads and `api/.env.example` never declared, correctly ranked `degrades`
rather than `breaks_request_path`, because the code supplies defaults.

The "983 facts" number is worth one more sentence. An earlier version of
that command printed **484** and also said zero — because the FastAPI
route table and the ORM schema had failed to extract, and nobody noticed
that "no findings" meant "nothing looked". That is the failure mode this
whole tool exists to make impossible, caught in its own dogfooding gate.
It is why the "Not checked" list below is not decoration.

### The "Not checked" list is not filler

A tool that reports four problems and stays silent about the nine things
it could not look at is telling you your system is fine when it does not
know. Every gap is named, with the reason, and a route table that could
not be read never produces "that route does not exist" — it produces a
line saying nobody looked.

### Getting started on your own repository

```bash
# Describe your system. Components, and which of them talk to which.
cat > culprit.yaml <<'YAML'
version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path   # this is what makes severity mean something
  - name: api
    kind: service
extract:
  components:
    api: { root: api }
    web: { root: frontend, calls_to: api }
YAML

culprit check                       # human-readable
culprit check --unverifiable        # plus: where nothing could catch a mistake
culprit check --format sarif -o culprit.sarif   # GitHub pull-request annotations
```

Exit codes: `0` clean, `1` findings at or above `--fail-on`
(`breaks_request_path`, `degrades` — the default — or `any`), `2` the
command could not run.

`culprit.yaml` names config **keys** and never values, and the loader
refuses anything credential-shaped. No report in any format can print a
config value; there is a test that greps every rendered format for one.

Its limits are written down, in detail, in [docs/LIMITS.md](docs/LIMITS.md).

## The incident-correlation half

Everything below is the second half: the running system that watches
telemetry. It needs a deployment, and it is the older of the two — see
`docs/DIAGNOSTIC_PLAN.md` for how the two fit together.

### What it is not

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
