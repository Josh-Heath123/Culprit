# Same uv+Docker pattern as api/Dockerfile — see that file's comments,
# including why the build context is the repo root rather than this
# directory (culprit-shared's path dependency needs shared/ visible).
# Unlike api/, worker/ only ever runs one process (the arq worker), so
# this image does set a default CMD.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=worker/uv.lock,target=uv.lock \
    --mount=type=bind,source=worker/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=shared,target=/shared \
    uv sync --frozen --no-install-project --no-dev

COPY worker/ /app/
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

CMD ["arq", "app.main.WorkerSettings"]
