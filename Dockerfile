# syntax=docker/dockerfile:1.7
# Multi-stage build: uv for deps, slim Python for runtime.
# Same image serves the web API (default CMD) and the arq worker
# (override CMD). Migrations run as a one-shot before either starts.

# ---- Builder ------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Resolve deps in their own layer so source edits don't bust the cache.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Install the project itself.
# `skills/` lives at the repo root and is loaded at startup by
# app/skills/loader.py via Path(__file__).resolve().parents[2] / "skills".
COPY app ./app
COPY skills ./skills
COPY scripts ./scripts
COPY alembic.ini alembic-brain.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Runtime ------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Non-root user; OS deps kept minimal (libpq for psycopg, curl for healthcheck).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 votf

WORKDIR /app
COPY --from=builder --chown=votf:votf /app /app

USER votf
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default: web API. Worker overrides with:
#   command: arq app.workers.settings.WorkerSettings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
