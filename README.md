# Talos

AI-augmented collaborative platform built around workspaces, chatrooms, and retrieval-augmented chat over user-uploaded documents. Graduation project.

The backend is a FastAPI service wired to PostgreSQL, Milvus, MinIO, and Redis; the frontend is a React + MUI + Tailwind SPA. A background worker handles asynchronous file processing.

A full case study, including the retrieval evaluation behind the shipped defaults, is at [romia.dev/projects/talos](https://romia.dev/projects/talos).

## Architecture

```
Upload -> MinIO object store -> taskiq worker
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

**Upload flow.** A multipart upload is validated by magic-byte MIME sniffing, size-capped, checksummed (SHA-256), and stored in MinIO under a deterministic workspace-scoped key. Metadata (filename, content type, size, uploader, workspace, optional chatroom, processing status) is persisted in Postgres. The endpoint responds `202 Accepted` and enqueues a taskiq job for the worker to pick up.

**Access control.** Every file operation goes through a workspace-membership check, so files remain scoped to the users allowed to see them.

**Downloads.** The API issues short-lived presigned URLs from MinIO rather than proxying bytes. Content-Disposition headers are set server-side so the browser downloads with the original filename.

**Background processing.** A separate taskiq worker process consumes jobs from Redis:

- Documents (PDF, DOCX, TXT, Markdown) are downloaded from MinIO, parsed with `unstructured`, chunked by the configured strategy (`by_title` by default), and ingested into Milvus with workspace and file metadata. Retrieval can then be filtered to a specific workspace or file.
- Images (PNG, JPEG, WebP) are resized to a JPEG thumbnail with Pillow and uploaded alongside the original.
- Status transitions (`UPLOADED`, `PROCESSING`, `INDEXED`, `FAILED`) are persisted on the file record. Retries and timeouts are managed by taskiq; failure messages are recorded for inspection.

**Message attachments.** Files can be linked to chat messages through a join table so the UI can surface what the user referenced and the retriever can filter accordingly.

**Lifecycle.** Soft-deleting a file removes its chunks from Milvus as well, so retrieval never surfaces content that has been deleted.

**Plumbing.** Bucket initialization runs on app startup; MinIO is configured with separate internal and external endpoints so presigned URLs resolve correctly for both the worker and browser clients. The taskiq broker starts and stops with the FastAPI lifespan. A multi-stage Dockerfile produces the `app`, `worker`, and `mcp` images, and `docker-compose.yaml` runs them as separate services.

The module is covered by unit tests (service, storage, schemas, processing tasks, worker settings, ingestion) and integration tests (upload, metadata, pagination, attach, delete) running against real Postgres and a mocked MinIO.

## Setup

### Prerequisites

- Python 3.13
- Docker (or Podman with the Docker socket)
- OpenAI API key

### Install

```bash
git clone https://github.com/Ab-Romia/talos.git
cd talos

cp .env.example .env
# Fill in OPENAI_API_KEY and the other secrets

pip install uv
uv sync
```

### Start services

```bash
docker compose up -d
# Starts: app, worker, scheduler, mcp, postgres, milvus (+ etcd), minio, redis
```

### Run the API and frontend

The backend is served by the `app` container on port 8000. The frontend is a separate Vite dev server:

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

## Tests

```bash
# Unit tests (no external services required)
uv run pytest tests/unit -q

# Auth and integration tests (need Postgres, Redis, MinIO running)
uv run pytest tests/auth tests/integration -q
```

## Configuration

Runtime config is loaded from `.env` (via pydantic-settings, nested delimiter `__`). See `.env.example` for the complete list.

Key settings:

| Variable                       | Default                  | Description                                        |
| ------------------------------ | ------------------------ | -------------------------------------------------- |
| `OPENAI_API_KEY`               |                          | Required                                           |
| `OPENAI_MODEL`                 | `gpt-4o-mini`            | LLM model                                          |
| `EMBEDDING_MODEL`              | `text-embedding-3-small` | Embedding model                                    |
| `MILVUS_HOST`                  | `localhost`              | Milvus host                                        |
| `MILVUS_PORT`                  | `19530`                  | Milvus port                                        |
| `USE_HYBRID_RETRIEVAL`         | `true`                   | Enable hybrid search                               |
| `USE_RERANKING`                | `true`                   | Enable cross-encoder reranking                     |
| `CHUNK_SIZE`                   | `1000`                   | Document chunk size                                |
| `CHUNK_OVERLAP`                | `200`                    | Chunk overlap                                      |
| `MINIO__INTERNAL_ENDPOINT`     | `localhost:9000`         | MinIO host used by the API and worker              |
| `MINIO__EXTERNAL_ENDPOINT`     | `localhost:9000`         | MinIO host embedded in presigned URLs for browsers |
| `MINIO__BUCKET_NAME`           | `talos-uploads`          | Object storage bucket                              |
| `EMBEDDING_PROVIDER`           | `openai`                 | Embedding backend: `openai` or `huggingface`       |
| `REDIS__URL`                   | `redis://localhost:6379` | taskiq broker URL                                  |

## Tech Stack

- **FastAPI** for the HTTP API, with SSE for streaming chat responses
- **LangChain** for RAG pipeline orchestration
- **Milvus** as the vector database
- **OpenAI** for embeddings and generation
- **MinIO** for S3-compatible object storage
- **taskiq + Redis** for background job processing
- **PostgreSQL** for relational state (users, sessions, workspaces, files, messages)
- **Pydantic** for configuration and validation
- **React + MUI + Tailwind** on the frontend
- **Docker Compose** for local infrastructure

## License

Graduation project, Talos, 2026.
