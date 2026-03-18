# Phase 5: Docker & Config Consolidation — Implementation Plan

## Goal
Make the entire Talos stack runnable with a single `docker-compose up`. Add Dockerfiles for the FastAPI app and ARQ worker. Update config/env examples to reflect all services added in Phases 1-4.

---

## Current State Analysis

### What exists
- `docker-compose.yaml` — infrastructure only: postgres, adminer, etcd, minio, minio-init, redis, milvus-standalone
- `app.py` — at project root, runs with `PYTHONPATH=src`
- `config/config_.py` — `Config` (pydantic-settings, YAML+env, nested delimiter `__`) with `MinIOConfig`, `RedisConfig`, `AuthConfig`
- `config/config.py` — `RagConfig` (pydantic-settings, env-only) with Milvus, embedding, chunking, LLM config
- `.env` — flat env vars for both config systems
- `.env.example` — **outdated**: missing MinIO, Redis, and auth config vars added in Phases 1-3
- `config/config.yaml` — **does not exist** (referenced by `Config` yaml_file setting, falls back to defaults)
- No Dockerfile anywhere in the project

### What runs on the host today
1. **FastAPI app**: `PYTHONPATH=src uv run uvicorn app:app --host 0.0.0.0 --port 8000`
2. **ARQ worker**: `PYTHONPATH=src uv run arq processing.worker.WorkerSettings`

### Key deployment constraints
- Python 3.13 (requires `>=3.13, <3.15` due to unstructured)
- CPU-only PyTorch (explicit index in pyproject.toml)
- `python-magic` requires `libmagic1` system package
- `PYTHONPATH=src` must be set
- `app.py` is at project root (not in `src/`)
- MinIO two-client pattern: internal endpoint (server-to-server) vs external endpoint (browser presigned URLs)

---

## Files to Create

### 1. `Dockerfile`

Multi-target Dockerfile (single file, two build targets):

```dockerfile
# ── Base stage: shared Python + deps ──
FROM python:3.13-slim AS base

# System deps for python-magic and general build
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

# ── Worker target: ARQ background worker ──
FROM base AS worker
CMD ["arq", "processing.worker.WorkerSettings"]
```

**Design decisions:**
- Single Dockerfile with targets — avoids duplication, both share the same base image
- `python:3.13-slim` — minimal image, matches project's Python requirement
- `uv sync --frozen` — reproducible installs from lockfile
- `libmagic1` — required by python-magic for MIME detection
- Layer caching: `pyproject.toml` + `uv.lock` copied before source code so deps aren't reinstalled on code changes
- No `unstructured` system deps (poppler, tesseract) — fallback text extraction handles this. Can be added later if needed.

### 2. `.dockerignore`

```
.venv/
.git/
.idea/
__pycache__/
*.pyc
*.pyo
.env
.env.local
*.log
logs/
.pytest_cache/
htmlcov/
.coverage
node_modules/
docs/
tests/
frontend/
*.md
.claude/
PHASE*.md
```

Keeps the build context small and avoids leaking secrets (`.env`).

---

## Files to Modify

### 3. `docker-compose.yaml`

**Add two new services:**

```yaml
  app:
    build:
      context: .
      target: app
    hostname: talos-app
    restart: unless-stopped
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-talos_app}:${POSTGRES_PASSWORD:-password}@postgres:5432/${POSTGRES_DB:-talos}
      MILVUS_HOST: milvus-standalone
      MINIO__INTERNAL_ENDPOINT: minio:9000
      MINIO__EXTERNAL_ENDPOINT: ${MINIO_EXTERNAL_ENDPOINT:-localhost:9000}
      REDIS__URL: redis://redis:6379
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      milvus-standalone:
        condition: service_healthy
      minio:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build:
      context: .
      target: worker
    hostname: talos-worker
    restart: unless-stopped
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-talos_app}:${POSTGRES_PASSWORD:-password}@postgres:5432/${POSTGRES_DB:-talos}
      MILVUS_HOST: milvus-standalone
      MINIO__INTERNAL_ENDPOINT: minio:9000
      MINIO__EXTERNAL_ENDPOINT: ${MINIO_EXTERNAL_ENDPOINT:-localhost:9000}
      REDIS__URL: redis://redis:6379
    depends_on:
      postgres:
        condition: service_healthy
      milvus-standalone:
        condition: service_healthy
      minio:
        condition: service_healthy
      redis:
        condition: service_healthy
```

**Key networking details:**
- `DATABASE_URL` uses `postgres` hostname (docker service name)
- `MILVUS_HOST` uses `milvus-standalone` (container name)
- `MINIO__INTERNAL_ENDPOINT` = `minio:9000` (server-to-server, inside Docker network)
- `MINIO__EXTERNAL_ENDPOINT` = `localhost:9000` (browser-facing, outside Docker — configurable via env var for prod)
- `REDIS__URL` uses `redis` hostname
- `__` is the nested delimiter in pydantic-settings — `MINIO__INTERNAL_ENDPOINT` maps to `config().minio.internal_endpoint`

### 4. `.env.example`

**Update to include all vars from Phases 1-4:**

```
# Copy this file to .env and fill in your actual values

# ── OpenAI ──
OPENAI_API_KEY=<YOUR_API_KEY_HERE>

# ── App ──
HOST=localhost
PORT=8000

# ── Auth ──
JWT_SECRET_KEY=<JWT_SECRET_KEY_HERE>
# GOOGLE_CLIENT_ID=<GOOGLE_OAUTH_CLIENT_ID>
# GOOGLE_CLIENT_SECRET=<GOOGLE_OAUTH_SECRET>

# ── PostgreSQL ──
POSTGRES_DB=talos
POSTGRES_USER=talos_app
POSTGRES_PASSWORD=<POSTGRES_PASSWORD_HERE>
DATABASE_URL=postgresql://talos_app:<POSTGRES_PASSWORD_HERE>@localhost:5432/talos

# ── Milvus ──
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=documents_v2

# ── MinIO ──
MINIO__INTERNAL_ENDPOINT=localhost:9000
MINIO__EXTERNAL_ENDPOINT=localhost:9000
MINIO__ACCESS_KEY=minioadmin
MINIO__SECRET_KEY=minioadmin
MINIO__BUCKET_NAME=talos-uploads

# ── Redis ──
REDIS__URL=redis://localhost:6379

# ── RAG Models ──
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# ── Chunking ──
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
CHUNKING_STRATEGY=recursive

# ── Retrieval ──
RETRIEVAL_TOP_K=5
RERANK_TOP_K=3
USE_HYBRID_RETRIEVAL=true
USE_RERANKING=true

# ── Memory ──
CONVERSATION_MEMORY_K=3
```

**What changed:**
- Added `MinIO` section (nested `__` vars matching `Config.minio`)
- Added `Redis` section (nested `__` var matching `Config.redis`)
- Removed `ARGON2_SECRET` (not used anywhere in codebase)
- Commented out Google OAuth (optional)
- Organized into sections

### 5. `config/config_.py` — minor fix

Fix `AuthConfig` OAuth client annotations:

```python
# Before:
google_client: OAuthClient = None
github_client: OAuthClient = None

# After:
google_client: OAuthClient | None = None
github_client: OAuthClient | None = None
```

This is directly related to config consolidation — without this fix, pydantic validation fails when these fields are `None` (which they are by default and in Docker).

---

## Files NOT Modified

- `config/config.py` (`RagConfig`) — no changes needed. Its env vars (MILVUS_HOST, CHUNK_SIZE, etc.) are flat and work fine in Docker via `env_file` + environment overrides.
- `app.py` — no changes. It already reads config correctly.
- `processing/worker.py` — no changes. It already reads from `config()`.
- No new Python code. This phase is purely infrastructure.

---

## How It Works

### Local development (no Docker for app)
```bash
docker-compose up postgres milvus-standalone minio redis  # infrastructure only
PYTHONPATH=src uv run uvicorn app:app --host 0.0.0.0 --port 8000
PYTHONPATH=src uv run arq processing.worker.WorkerSettings
```
Uses `localhost` endpoints in `.env`. Same as today.

### Full Docker
```bash
docker-compose up --build
```
All services start. The `app` and `worker` services override connection vars via `environment:` in compose to use Docker hostnames.

### Config resolution order (pydantic-settings)
1. Init values → 2. Environment vars → 3. `.env` file → 4. YAML file → 5. Secrets

Docker `environment:` entries are real env vars, so they **override** `.env` file values. This means:
- `.env` has `DATABASE_URL=...localhost...` for local dev
- Docker compose `environment` has `DATABASE_URL=...postgres...` for Docker
- The Docker override wins. No config changes needed.

---

## Verification Checklist

- [ ] `docker-compose up --build` starts all services without errors
- [ ] App is reachable at `http://localhost:8000`
- [ ] Upload endpoint works (app → MinIO via `minio:9000` internal)
- [ ] Download presigned URL works (browser → MinIO via `localhost:9000` external)
- [ ] Background processing runs (worker picks up jobs from Redis)
- [ ] Milvus ingestion works (worker → Milvus via `milvus-standalone:19530`)
- [ ] Local dev mode still works (docker infra only, app on host)
- [ ] `.env.example` documents all configurable vars

---

## Risk Notes

1. **PyTorch image size** — The Docker image will be large (~2-3 GB) due to PyTorch + sentence-transformers. This is expected for an ML-capable backend. Using `python:3.13-slim` and CPU-only torch mitigates somewhat.

2. **`uv sync` in Docker** — uv creates a `.venv` inside the container. The `PATH` must include `.venv/bin` for the CMD to find `uvicorn` and `arq`.

3. **Milvus startup time** — Milvus takes ~60-90s to start (configured `start_period: 90s`). The app/worker `depends_on` with `condition: service_healthy` ensures they wait. The app's module-level `connections.connect()` in `vector_store.py` runs at import time — if Milvus isn't ready, the import fails. The `depends_on` health check should prevent this, but the app also has graceful degradation (RAG imports are lazy in most paths).

4. **MinIO external endpoint in Docker** — The presigned URL hostname must be reachable from the browser. In local Docker dev, `localhost:9000` works because MinIO port is mapped. In production, this would need to be the public hostname/IP.
