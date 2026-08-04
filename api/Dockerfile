# Multi-stage build for both of api/'s deployable processes — the
# dashboard API (app/main.py) and ingest-gateway (app/ingest_gateway/
# main.py). One image, two containers in production (see
# infra/docker-compose.prod.yml), distinguished only by CMD/command —
# same pattern as running them as two separate `uv run uvicorn` processes
# locally (see justfile's `dev` and `ingest-gateway` recipes).
#
# Follows Astral's documented uv+Docker pattern: a builder stage that
# resolves/installs dependencies with uv (cached separately from the app
# source so a code-only change doesn't reinstall dependencies), then a
# slim runtime stage with no build tooling.
#
# Build context is the REPO ROOT, not this directory — see .github/
# workflows/ci-cd.yml's build job (context: ., file: api/Dockerfile).
# api/pyproject.toml declares `culprit-shared = { path = "../shared" }`;
# that path is relative to api/, so from a plain `docker build api`
# (context = api/ alone) shared/ is outside the context entirely and
# unreachable — which is exactly what broke here originally (uv failing
# with "Distribution not found at: file:///shared"). Root context makes
# shared/ visible; see .dockerignore at the repo root for what's excluded
# from it (api/'s and worker's old per-directory .dockerignore files are
# gone now that their context isn't their own directory anymore).

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile alone — cached across builds as
# long as neither api/pyproject.toml, api/uv.lock, nor shared/'s source
# change, regardless of api's own app code churn. shared/ is bind-mounted
# at /shared specifically because "../shared" relative to /app (this
# WORKDIR) resolves to exactly that path — matching what uv already
# expects without needing to touch pyproject.toml's path.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=api/uv.lock,target=uv.lock \
    --mount=type=bind,source=api/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=shared,target=/shared \
    uv sync --frozen --no-install-project --no-dev

COPY api/ /app/
COPY shared/ /shared/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim
# Picks up whatever Debian security patches have landed since this
# base image tag was last published — same reasoning as
# frontend/Dockerfile's apk upgrade step.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN groupadd --system app && useradd --system --gid app app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /shared /shared
ENV PATH="/app/.venv/bin:$PATH"
USER app

# No default CMD: infra/docker-compose.prod.yml sets `command:` per
# service (dashboard API vs ingest-gateway) — this image is the same
# artifact for both.
