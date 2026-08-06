# Same uv+Docker pattern as api/Dockerfile and worker/Dockerfile (see
# api/Dockerfile's comments for the full reasoning) -- demo-services/
# didn't have an image at all before Phase 17 (docs/SELF_HOSTED_PLAN.md
# Phase 17, Known Trap 1) because nothing needed one until the local
# quickstart wanted to run all three demo services + the load generator
# in Compose instead of by hand in separate terminals.
#
# Build context is the REPO ROOT, not this directory -- demo-services/
# pyproject.toml declares `culprit-shared = { path = "../shared" }`
# (relative to demo-services/), which is invisible to a `docker build
# demo-services` (context = demo-services/ alone). See
# infra/docker-compose.quickstart.yml's `build: {context: ., ...}`.
#
# One image, five possible commands (order/inventory/payments-service via
# uvicorn, plus load_generator.py and fault_cli.py) -- distinguished only
# by `command:` per docker-compose.quickstart.yml service, same pattern
# as api/Dockerfile's dashboard-API-vs-ingest-gateway split. No default
# CMD for the same reason.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=demo-services/uv.lock,target=uv.lock \
    --mount=type=bind,source=demo-services/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=shared,target=/shared \
    uv sync --frozen --no-install-project --no-dev

COPY demo-services/ /app/
COPY shared/ /shared/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN groupadd --system app && useradd --system --gid app app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /shared /shared
ENV PATH="/app/.venv/bin:$PATH"
USER app
