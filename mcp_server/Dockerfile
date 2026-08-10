# Unlike api/worker/demo-services, mcp_server has no culprit-shared
# dependency (Step 1, docs/AI_NATIVE_PLAN.md Phase 24) -- context is this
# directory itself, not the repo root. Not wired into
# docker-compose.prod.yml (Out of scope: no shared, multi-client
# deployment in this phase) -- this image exists so a team can build and
# run it themselves, e.g. `docker run --env-file ... culprit/mcp-server`.
#
# mcp_server/ is a *flat* package (pyproject.toml sits beside __init__.py,
# not one level above it, unlike api/app or worker/app's nested layout)
# -- `python -m mcp_server` therefore needs a cwd *above* the package
# directory to resolve `import mcp_server` at all. The build stage
# installs into /app/mcp_server/ (one level nested, deliberately not
# flattened into /app/ directly); the final stage's WORKDIR is /app, one
# level above that, so the runtime CMD's cwd makes `mcp_server` resolve
# as a package. Same reasoning as this phase's own
# docs/AI_NATIVE_INSTRUMENTATION.md, which documents the equivalent
# `uv run --project mcp_server python -m mcp_server` invocation from the
# repo root for local (non-Docker) use.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app/mcp_server

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app/mcp_server/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim
# Picks up whatever Debian security patches have landed since this base
# image tag was last published -- same reasoning as worker/Dockerfile's
# own apt upgrade step.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN groupadd --system app && useradd --system --gid app app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/mcp_server/.venv/bin:$PATH"
USER app

CMD ["python", "-m", "mcp_server"]
