# culprit-extract-python

The Python intent extractor for [Culprit](https://culprit.co.za).

Install it as a **dev-dependency of the project you want to analyse**, not
of Culprit itself. It has to run inside your project's own virtualenv:
introspecting a FastAPI app means importing it, which means having your
dependencies importable.

```bash
uv add --dev culprit-extract-python     # or: pip install culprit-extract-python
```

Then point `culprit.yaml` at it:

```yaml
extract:
  extractors:
    - name: python
      command: ["uv", "run", "culprit-extract-python", "--app", "app.main:app"]
  components:
    orders-api:
      root: api
      extractors: [python]
```

`culprit intent` does the rest. You can also run it by hand — it reads an
extractor request on stdin and writes a response on stdout:

```bash
echo '{"protocol":1,"root":"'"$PWD"'","want":["http_routes"],"environment":null,"component":"orders-api"}' \
  | uv run culprit-extract-python --app app.main:app
```

## What it reads

| Want | Source | Rank |
|---|---|---|
| `http_routes` | `app.openapi()` (FastAPI), `app.url_map` (Flask), the URL resolver (Django) | 90 |
| `db_schema` | SQLAlchemy `MetaData` reachable from the imported app; Alembic `ScriptDirectory` | 90 |
| `config_keys` | `os.environ[...]` / `os.getenv(...)` read sites, via `ast` | 60 |
| `test_assertions` | `assert response.status_code == N` beside a test-client call | 50 |

## What it never does

- **It never emits a config value.** Config facts carry a `ValueShape` —
  a closed four-field type with nowhere to put a literal. Even a default
  written in your source becomes a shape.
- **It never fails your build.** Anything it cannot read becomes a
  `skipped` entry with a reason, and it exits zero.

## Trust

Extraction **imports your application**, which runs your code — the same
trust level as running your own test suite. Pass `--no-import` to skip
that and get static extraction only. See `docs/EXTRACTOR_PROTOCOL.md`.
