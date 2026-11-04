# culprit-extract-node

The JavaScript/TypeScript intent extractor for [Culprit](https://github.com/Josh-Heath123/Culprit).

Install it as a **dev-dependency of the project you want to analyse**:

```bash
# Not published to npm yet: install it from your clone of Culprit.
npm install --save-dev /path/to/culprit/extractors/node
```

Then point `culprit.yaml` at it:

```yaml
extract:
  extractors:
    - name: node
      command: ["npx", "--no-install", "culprit-extract-node"]
  components:
    web:
      root: frontend
      extractors: [node]
      calls_to: orders-api      # whose routes this component's fetch() calls hit
```

## What it reads

| Want | Source | Rank |
|---|---|---|
| `client_calls` | `fetch(...)`, `axios.get(...)`, `api.post(...)` and friends | 40 |
| `http_routes` | `app.get('/x', ...)` / `router.post(...)` — Express, Fastify, Koa-router | 60 |
| `dependencies` | `package.json` `dependencies` and `devDependencies` | 80 |

## What it does not do

**It does not import your application.** Unlike the Python extractor,
this one is purely static: it parses source with `@babel/parser` and
reads the syntax tree. Node has no equivalent of `app.openapi()` to ask,
and importing an Express app to enumerate its router stack means running
your server's startup — including whatever it connects to. So route
facts here are rank 60 (static extraction from framework code), not 90.

That is a real limitation and it is the honest one: a route registered
through a loop, a variable path, or a dynamically-required router is not
seen. When that happens you get fewer facts, never wrong ones.

**It never fails your build.** Anything it cannot read becomes a
`skipped` entry with a reason, and it exits zero.
