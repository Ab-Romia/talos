# Talos

AI-augmented collaborative platform built around workspaces, chatrooms, and retrieval-augmented chat over user-uploaded documents. Graduation project.

The backend is a FastAPI service wired to PostgreSQL, Milvus, MinIO, and Redis; the frontend is a React + MUI + Tailwind SPA. A background worker handles asynchronous file processing.

## Architecture

```
Upload -> MinIO object store -> ARQ worker
                                    |
                                    +-> Documents: parse, chunk, ingest into Milvus
                                    +-> Images:    thumbnail to MinIO

Query  -> Query Processing (Rewrite / HyDE) -> Hybrid Retrieval (Dense + BM25)
                                                      |
                                               Cross-Encoder Reranking
                                                      |
                                             LLM Generation with Citations
```

**Key components:**

- **Authentication.** Password, TOTP, Google/GitHub OAuth, and WebAuthn passkeys. Sessions are JWE-encrypted and stored in Postgres.
- **Chat.** Per-workspace chatrooms with server-sent-event streaming of LLM responses, fed by the RAG pipeline.
- **Hybrid retrieval.** Dense (semantic) plus sparse (BM25) search with reciprocal rank fusion.
- **Cross-encoder reranking.** Two-stage retrieval for precision.
- **Query processing.** Query rewriting, expansion, HyDE.
- **Context compression.** LLM extraction or embedding-based filtering.
- **Conversation memory.** Multi-turn context awareness.
- **File upload and processing.** Documented below.

## File upload and processing

Talos accepts document and image uploads into workspaces and processes them asynchronously so the API can return immediately while text extraction and indexing happen out of band.

**Upload flow.** A multipart upload is validated by magic-byte MIME sniffing, size-capped, checksummed (SHA-256), and stored in MinIO under a deterministic workspace-scoped key. Metadata (filename, content type, size, uploader, workspace, optional chatroom, processing status) is persisted in Postgres. The endpoint responds `202 Accepted` and enqueues an ARQ job for the worker to pick up.

**Access control.** Every file operation goes through a workspace-membership check, so files remain scoped to the users allowed to see them.

**Downloads.** The API issues short-lived presigned URLs from MinIO rather than proxying bytes. Content-Disposition headers are set server-side so the browser downloads with the original filename.

**Background processing.** A separate ARQ worker process consumes jobs from Redis:

- Documents (PDF, DOCX, TXT, Markdown) are downloaded from MinIO, parsed with `unstructured`, split with LangChain's recursive character splitter, and ingested into Milvus with workspace and file metadata. Retrieval can then be filtered to a specific workspace or file.
- Images (PNG, JPEG, WebP) are resized to a JPEG thumbnail with Pillow and uploaded alongside the original.
- Status transitions (`UPLOADED`, `PROCESSING`, `INDEXED`, `FAILED`) are persisted on the file record. Retries and timeouts are managed by ARQ; failure messages are recorded for inspection.

**Message attachments.** Files can be linked to chat messages through a join table so the UI can surface what the user referenced and the retriever can filter accordingly.

**Lifecycle.** Soft-deleting a file removes its chunks from Milvus as well, so retrieval never surfaces content that has been deleted.

**Plumbing.** Bucket initialization runs on app startup; MinIO is configured with separate internal and external endpoints so presigned URLs resolve correctly for both the worker and browser clients. The ARQ Redis pool is wired into the FastAPI lifespan and degrades gracefully when Redis is unavailable. A multi-stage Dockerfile produces both the `app` and `worker` images, and `docker-compose.yaml` runs them as separate services.

The module is covered by unit tests (service, storage, schemas, processing tasks, worker settings, ingestion) and integration tests (upload, metadata, pagination, attach, delete) running against real Postgres and a mocked MinIO.

## Setup

### Prerequisites

- Python 3.13
- Node.js 18+
- Docker or Podman + docker-compose
- OpenAI API key

### 1 — Clone and configure

```bash
git clone https://github.com/Ab-Romia/gp_artifact.git
cd gp_artifact

cp .env.example .env
# Open .env and fill in at minimum:
#   OPENAI_API_KEY, POSTGRES_PASSWORD, AUTH__JWE_SECRET
```

### 2 — Python dependencies

```bash
pip install uv      # skip if uv is already on PATH
uv sync
```

### 3 — SSL certificates (one-time, local HTTPS)

nginx terminates TLS on port 443. You need locally-trusted certs before starting.

**On Fedora/RHEL:**
```bash
sudo dnf install mkcert
```
**On Ubuntu/Debian:**
```bash
sudo apt install mkcert
```

Then generate the certs:
```bash
mkcert -install                         # trust the local CA in your browser (run once)

mkcert -cert-file nginx/certs/cert.pem \
       -key-file  nginx/certs/key.pem  \
       localhost 127.0.0.1 ::1
```

**Rootless Podman only (Fedora default):** ports 80 and 443 require a one-time sysctl:
```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 4 — Build the frontend

nginx serves the compiled React bundle. Build it before starting the stack:

```bash
cd frontend && npm install && npm run build && cd ..
```

### 5 — Start everything

```bash
docker compose up -d
```

This starts: **nginx** (80/443), **app** (internal), **worker**, **postgres**, **milvus** (+ etcd), **minio**, **redis**, **adminer** (8080).

Open **https://localhost** — done.

---

### Development mode (hot-reload, no nginx)

If you're actively changing backend or frontend code, skip nginx and run both locally:

```bash
# Terminal 1 — backend (needs infra containers running)
docker compose up -d postgres milvus-standalone minio redis
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — frontend (proxies /api and /auth to localhost:8000)
cd frontend && npm run dev
# Open http://localhost:5173
```

---

## Tests

```bash
# Unit tests — no external services needed
uv run pytest tests/unit -q

# Auth + integration tests — needs Postgres, Redis, MinIO running
uv run pytest tests/auth tests/integration -q

# Integration tests use a separate DB
DATABASE_URL=postgresql://talos_app:password@localhost:5432/talos_test \
  uv run pytest tests/integration -q
```

## Configuration

Runtime config is loaded from `.env` (pydantic-settings, nested delimiter `__`). See `.env.example` for the full list.

Key settings:

| Variable                       | Default                  | Description                                               |
| ------------------------------ | ------------------------ | --------------------------------------------------------- |
| `OPENAI_API_KEY`               |                          | Required                                                  |
| `OPENAI_MODEL`                 | `gpt-4o-mini`            | LLM model                                                 |
| `EMBEDDING_MODEL`              | `text-embedding-3-small` | Embedding model                                           |
| `MILVUS_HOST`                  | `localhost`              | Milvus host                                               |
| `MILVUS_PORT`                  | `19530`                  | Milvus port                                               |
| `USE_HYBRID_RETRIEVAL`         | `true`                   | Enable hybrid search                                      |
| `USE_RERANKING`                | `true`                   | Enable cross-encoder reranking                            |
| `CHUNK_SIZE`                   | `1000`                   | Document chunk size                                       |
| `CHUNK_OVERLAP`                | `200`                    | Chunk overlap                                             |
| `MINIO__INTERNAL_ENDPOINT`     | `minio:9000`             | MinIO host used by the API and worker (docker-internal)   |
| `MINIO__EXTERNAL_ENDPOINT`     | `localhost`              | Host embedded in presigned URLs — set to your domain      |
| `MINIO__EXTERNAL_SECURE`       | `true`                   | Generate `https://` presigned URLs (matches nginx)        |
| `MINIO__BUCKET_NAME`           | `talos-uploads`          | Object storage bucket                                     |
| `REDIS__URL`                   | `redis://redis:6379`     | ARQ broker URL                                            |

## Tech Stack

- **FastAPI** for the HTTP API, with SSE for streaming chat responses
- **LangChain** for RAG pipeline orchestration
- **Milvus** as the vector database
- **OpenAI** for embeddings and generation
- **MinIO** for S3-compatible object storage
- **ARQ + Redis** for background job processing
- **PostgreSQL** for relational state (users, sessions, workspaces, files, messages)
- **Pydantic** for configuration and validation
- **React + MUI + Tailwind** on the frontend
- **Docker Compose** for local infrastructure

## License

Graduation project, Talos, 2026.
