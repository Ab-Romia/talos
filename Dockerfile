# ── Base stage: shared Python + deps ──
FROM python:3.13-slim AS base

# System deps for python-magic
RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1 && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen lockfile, no dev deps, system python)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY app.py ./
COPY src/ ./src/
COPY config/ ./config/

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

# ── App target: FastAPI server ──
FROM base AS app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Worker target: taskiq background worker ──
FROM base AS worker
CMD ["taskiq", "worker", "broker:broker", "notifications.tasks", "processing.tasks", "--app-dir=src"]
