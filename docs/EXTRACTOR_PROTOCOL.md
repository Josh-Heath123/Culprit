# The Culprit extractor protocol

**Version 1.** This document is the contract. Anything conforming to it
is a Culprit extractor, whatever language it is written in and whoever
wrote it — you do not need to touch this repository to add support for
Go, Ruby, Java or anything else.

---

## 1. What an extractor is

An executable that reads **one JSON object on stdin** and writes **one
JSON object on stdout**.

That is the whole interface. It is this dull deliberately.

Introspecting a FastAPI application means importing it, which means
having that project's virtualenv and its dependencies available. No
external process can do that correctly, and pretending otherwise is how
a tool ends up with a static analyser per language that is subtly wrong
in every one of them. Accepting the subprocess boundary up front turns
"we must write a parser for every framework" into "each ecosystem
contributes a small extractor in its own language" — which is also the
extension point you are reading about.

The `culprit` binary orchestrates. It never parses application code
itself.

---

## 2. The request

Written to your stdin, as one JSON object:

```json
{
  "protocol": 1,
  "root": "/abs/path/to/component/source",
  "want": ["http_routes", "db_schema", "config_keys",
           "client_calls", "test_assertions", "dependencies"],
  "environment": null,
  "component": "orders-api"
}
```

| Field | Meaning |
|---|---|
| `protocol` | The protocol version the orchestrator speaks. **If it is not a version you understand, skip everything and say so** — see §5. |
| `root` | Absolute path to the source root for this component. Also your working directory. |
| `want` | The classes of fact being asked for. Answer the ones you can; skip the rest. |
| `environment` | `null` for `INTENT` extraction. A named environment only when capturing what a live environment is configured to do. **In protocol 1 it is always `null`** — do not go looking for a running system. |
| `component` | The component name these facts are about. Use it verbatim when building subject URIs; it is what makes your facts comparable with everyone else's. |

### The `want` vocabulary

| Want | What it means |
|---|---|
| `http_routes` | HTTP endpoints this component *serves*. |
| `db_schema` | Tables and columns the code expects, and the migration revision it heads at. Not a reading of any live database. |
| `config_keys` | Configuration keys this component reads. **Names and shapes only** — see §6. |
| `client_calls` | HTTP endpoints this component *calls*. |
| `test_assertions` | Claims the test suite makes about behaviour. |
| `dependencies` | Declared dependency versions. |

A `want` you have never heard of is not an error. Skip it with
`unsupported want` — that is exactly what a newer orchestrator talking to
an older extractor should produce.

---

## 3. The response

Written to your stdout, as one JSON object:

```json
{
  "protocol": 1,
  "extractor": "culprit-extract-python@0.1.0",
  "facts": [ ... ],
  "skipped": [
    {"want": "client_calls", "reason": "no supported framework found"}
  ]
}
```

`extractor` is `name@version` and is required. It ends up in every fact's
provenance, which is what makes a wrong fact traceable to the build that
produced it.

**Nothing but this object may reach stdout.** If a library you import
prints on load — Django does, and plenty of application modules do — you
must capture that and send it to stderr, or you will corrupt the document
the orchestrator is parsing. The Python extractor does this with
`contextlib.redirect_stdout` for the whole extraction.

Anything on stderr is diagnostic and is ignored unless you fail.

---

## 4. A Fact

```json
{
  "plane": "INTENT",
  "subject": "http:orders-api/POST /api/v1/orders",
  "predicate": "exists",
  "value": {"path": "/api/v1/orders", "method": "POST"},
  "environment": null,
  "provenance": {
    "source_kind": "introspection",
    "extractor": "culprit-extract-python@0.1.0",
    "artefact": "app/main.py",
    "locator": "L142",
    "confidence_rank": 90
  },
  "captured_at": "2026-01-01T00:00:00Z",
  "capture_id": "00000000-0000-5000-8000-000000000000"
}
```

- `plane` is `INTENT` in protocol 1, and **every fact in one response
  must be on the same plane** — the orchestrator rolls your facts into a
  capture that declares one, and a fact disagreeing with it is refused
  by the control plane rather than stored on the wrong plane. `INTENT`
  and `CONFIGURED` are different captures, not different facts in one.
- An `INTENT` fact **must not** carry
  an `environment`; a `CONFIGURED` or `OBSERVED` one must.
- `capture_id` is **re-stamped by the orchestrator**. You have no way to
  know which capture your run is part of, so emit any valid UUID (or the
  nil UUID) and let it be replaced.
- `captured_at` is likewise normalised if you leave it empty.

### Subject URIs

The join key of the entire model. Two sources describing the same thing
must produce a **byte-identical** subject, or nothing will ever be
compared:

```
component:orders-api
connection:orders-api->payments-api
http:orders-api/POST /api/v1/orders
http:orders-api/POST /api/v1/orders#request.body
config:orders-api/DATABASE_URL
schema:orders-db/public.orders
schema:orders-db/public.orders.total_cents
dep:orders-api/stripe
image:orders-api
auth:orders-api->payments-api/audience
```

Rules, all of which the reference implementations enforce:

- **Component names** are lower-cased and trimmed. Underscores are *not*
  folded to hyphens: `order_service` and `order-service` are genuinely
  different names.
- **Methods** are upper-cased.
- **Paths are canonicalised, and this is the highest-risk part.** Every
  parameter becomes `{}`, whatever syntax declared it:
  `/orders/{id}`, `/orders/:id`, `/orders/<int:id>` and
  `^orders/(?P<pk>[0-9]+)/$` all become `/orders/{}`. Parameter *names*
  are erased — a Django view calling its capture `pk` and an OpenAPI
  document calling it `id` describe the same route. Query strings and
  fragments are dropped.
- **A part may not contain its own separators.** A component name
  containing `/`, `->`, `#` or a space would produce a subject that
  parses back as something else. Refuse it; do not mangle it.
- **Postgres identifiers** are lower-cased, because Postgres folds
  unquoted ones.

Do not hand-format these. Copy or port one of the reference
implementations, all of which are tested against the same fixtures:

| Language | Implementation | Conformance fixtures |
|---|---|---|
| Python | `shared/culprit_model/subjects.py` | `shared/tests/subject_conformance.json`, `shared/tests/canonical_conformance.json` |
| Go | `cli/internal/model/subjects.go` | the same two |
| JavaScript | `extractors/node/src/subjects.js` | the same two |

Those two JSON files are the specification of subject construction. If
you write an extractor in a fourth language, run it against them.

### Confidence ranks

```
100  an explicit developer assertion
 90  runtime introspection of the app        app.openapi(), app.url_map
 80  a committed machine-readable spec       openapi.json, a migration file
 60  static extraction from framework code   a route decorator
 50  static extraction from tests            assert resp.status_code == 200
 40  static extraction from client call sites  fetch("/api/v2/users")
 20  inference from observed traffic
```

Rank orders reports and picks comparison defaults. **Rank never silently
discards a source.** Two facts about the same subject and predicate that
disagree produce an `intent_conflict` finding — and that disagreement is
very often the bug. Report what you actually saw, at the rank that
honestly describes how you saw it.

---

## 5. The honesty rule

**An extractor that cannot answer says so and exits zero.**

```json
{"want": "http_routes",
 "reason": "importing orders_api.main raised MissingConfigError: DATABASE_URL must be set"}
```

This is the most important rule in the document, so it is worth being
explicit about why.

A person reading a Culprit report is deciding whether to trust it. A
report with a gap in it that says *why* is useful — "I could not check
your routes because your settings module needs `DATABASE_URL`" is
actionable in ten seconds. A report with a silent gap is worse than
useless: fewer findings looks exactly like fewer problems.

So:

- **Never fail the run.** Exit zero even when you skipped everything.
- **Never guess.** A key read as `os.environ[name]` where `name` is a
  variable is not extractable. Skip it. A subject built from a guess will
  never match anything and becomes a permanent phantom in every report.
- **Every skip needs a reason**, in plain language, naming what you
  wanted and what stopped you.

The orchestrator holds the same line from its side. A non-zero exit, a
timeout, unparseable stdout or a missing binary all become `skipped`
entries with a reason, and the run continues. `culprit intent` with
nothing installed still reports everything the committed artefacts
support.

---

## 6. Config values: names and shapes, never values

**A fact about a config key may not carry its value.**

This is not a convention. `culprit_model.Fact` refuses to be constructed
with one, the Go `Fact.Validate` refuses the same, the orchestrator
re-validates every fact it receives from you and drops the ones that
break the rule, and a Postgres CHECK constraint refuses the row. A
capture bundle has to be safe to attach to a bug report *by
construction*, because that is what people do with them.

Instead of a value, send a `ValueShape` — a closed four-field type with
nowhere to put a literal:

```json
{
  "subject": "config:orders-api/DATABASE_URL",
  "predicate": "value_shape",
  "value_shape": {
    "type": "string",
    "length_class": "medium",
    "format": "dsn",
    "present": true
  }
}
```

| Field | Values |
|---|---|
| `type` | `string` `integer` `number` `boolean` `list` `mapping` `null` `unknown` |
| `length_class` | `not_applicable` `empty` `short` `medium` `long` |
| `format` | `opaque` `url` `dsn` `email` `hostname` `ip_address` `port` `path` `duration` `booleanish` `numeric` `uuid` `json` `secret` `list` `not_applicable` |
| `present` | `true` / `false` |

Nothing else. An object with a fifth key is rejected — including by
`encoding/json` on the Go side, which is configured to disallow unknown
fields precisely so a `"sample"` cannot slip through silently.

A length *class*, not a length: an exact length is a small leak and no
comparison needs it. `present: false` is how you say a key is declared
but unset, which is the single most common real finding.

The one exception: a **boolean** value is allowed on a config subject
without a grant, for assertions *about* a key rather than its value —
`read_by: true`, `required: true`. A boolean has two inhabitants and
cannot carry a credential. Every other type needs an explicit per-key
grant naming `grant_ref`, and a numeric API key is a real thing, so
numbers are not exempt either.

---

## 7. Trust

**Runtime introspection imports the user's application, which runs their
code.** That is the same trust level as running their test suite, and it
is why extractors are installed as a dev-dependency of the project rather
than shipped inside Culprit.

Say so in your README. Users are entitled to know before they install.

If your extractor imports, offer a way not to: `culprit-extract-python`
has `--no-import`, which degrades to static extraction only for projects
whose settings module opens a database connection on import.

The orchestrator's side of the bargain:

- Your command is **argv, never a shell string**. `culprit.yaml` is a
  committed file, and a command interpreted by a shell would make it an
  arbitrary-execution vector for anyone who can open a pull request.
- You are run with a **timeout** (90 s by default). Exceeding it is a
  skip naming the timeout.
- Your stdout is **capped** (64 MiB). Exceeding it is a skip, not a
  truncated parse.

---

## 8. Being run

Declare your extractor in the project's `culprit.yaml`:

```yaml
version: 1
components:
  - name: orders-api
    kind: service
  - name: web
    kind: frontend

extract:
  extractors:
    - name: python
      command: ["uv", "run", "culprit-extract-python", "--app", "app.main:app"]
    - name: node
      command: ["npx", "--no-install", "culprit-extract-node"]
      want: [client_calls, dependencies]     # optional; default is everything
  components:
    orders-api:
      root: api
      extractors: [python]
    web:
      root: frontend
      extractors: [node]
      calls_to: orders-api
```

`calls_to` names the component whose routes this one's HTTP client calls
hit. A client-call extractor cannot work that out — it sees
`fetch('/api/v2/users')` and has no idea whose route that is — so it
emits the fact under the *caller*, and the orchestrator rebuilds the
subject against the callee. Without it, those facts are truthful
inventory with nothing to compare against.

A component with **no entry under `extract.components`** is not
extracted, and the report says so by name. That is deliberate: defaulting
an undeclared component's root to the repository root means every reader
runs once per component over the same tree, and a database with no source
of its own gets credited with the API's routes.

---

## 9. Testing yours

1. **Run it against the conformance fixtures.** `shared/tests/subject_conformance.json`
   and `shared/tests/canonical_conformance.json` are the specification of
   subject construction. Every reference implementation reads them.
2. **Use projects you did not write.** This repository's own corpus is
   under `cli/testdata/fixtures/`, and two of its four fixtures are
   vendored from upstream projects for exactly this reason. It paid
   immediately: the Flask tutorial configures itself with
   `app.config.from_mapping` and never touches `os.environ`, so the
   config-key reader found nothing in it — a real limitation, invisible
   against fixtures written alongside the extractor.
3. **Test the failures.** A missing framework, an app that raises on
   import, a malformed request, a protocol version from the future. Every
   one must produce a reasoned skip and exit zero.
4. **Test that no config value escapes.** Serialise a whole response and
   grep it for a real value from your fixture's `.env`.

---

## 10. Reference implementations

| | |
|---|---|
| Python | `extractors/python/` — FastAPI/Flask/Django route tables, SQLAlchemy metadata, Alembic revisions, `os.environ` read sites |
| JavaScript | `extractors/node/` — Express/Fastify/Koa route definitions, `fetch`/`axios` call sites, `package.json` |
| Built-in (Go, no plugin) | `cli/internal/extract/` — OpenAPI/Swagger, `.env.example`, compose files, Alembic version chains, dependency manifests |

The built-in readers are why `culprit intent` is useful with nothing
installed. Extractors add what only the project's own runtime can answer.

---

## 11. Installing the CLI

```
curl -fsSL https://raw.githubusercontent.com/Josh-Heath123/Culprit/main/scripts/install.sh | sh
```

One static binary, no runtime to install, nothing to compile. The script
picks the right build for your platform, verifies the published checksum
when one exists (and says loudly when it does not), and drops the binary
in `~/.local/bin`. Set `CULPRIT_INSTALL_DIR` to put it elsewhere, or
`CULPRIT_VERSION=vX.Y.Z` to pin.

Piping a script from the internet into a shell is a real risk and this
document is not going to tell you it is fine. `scripts/install.sh` is
short and worth reading first; or skip it entirely and take the binary
straight off the releases page — there is nothing else to the
installation.

**As of this writing no release has been cut**, so there is nothing for
that URL to download yet. Build from source in the meantime:

```
git clone https://github.com/Josh-Heath123/Culprit
cd Culprit && just cli-build      # -> cli/bin/culprit
```
