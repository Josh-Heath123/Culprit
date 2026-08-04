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

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile alone — cached across builds as
# long as pyproject.toml/uv.lock don't change, regardless of app code churn.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app
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
ENV PATH="/app/.venv/bin:$PATH"
USER app

# No default CMD: infra/docker-compose.prod.yml sets `command:` per
# service (dashboard API vs ingest-gateway) — this image is the same
# artifact for both.
