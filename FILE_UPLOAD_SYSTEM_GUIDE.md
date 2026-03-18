# Talos File Upload System - Complete Technical Guide

This document explains everything built on the `feature/file-upload-system` branch: the architecture, every file, every design decision, and how the pieces connect.

---

## Table of Contents

1. [Big Picture](#1-big-picture)
2. [Architecture Overview](#2-architecture-overview)
3. [Phase 1: Storage Foundation](#3-phase-1-storage-foundation)
4. [Phase 2: Upload & Download API](#4-phase-2-upload--download-api)
5. [Phase 3: Background Processing](#5-phase-3-background-processing)
6. [Phase 4: RAG Integration](#6-phase-4-rag-integration)
7. [Phase 5: Docker & Config](#7-phase-5-docker--config)
8. [Phase 6: Testing](#8-phase-6-testing)
9. [Data Flow Walkthroughs](#9-data-flow-walkthroughs)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Glossary](#11-glossary)

---

## 1. Big Picture

The goal: let users upload files (PDFs, images, text) to their workspaces, store them in object storage, automatically extract text and generate thumbnails, and make the text searchable through the existing RAG (Retrieval-Augmented Generation) pipeline.

What was built:

```
User uploads file via HTTP
       |
       v
[FastAPI endpoint] -- validates MIME type, file size
       |
       v
[MinIO object storage] -- binary file stored here
       |
       v
[PostgreSQL] -- metadata row created (FileAttachment)
       |
       v
[ARQ background job] -- enqueued via Redis
       |
       v
[Worker process] -- picks up job
       |
       +-- Document? --> extract text --> chunk --> embed --> store in Milvus
       +-- Image? ----> generate thumbnail --> upload thumb to MinIO
```

---

## 2. Architecture Overview

### Services

| Service | Purpose | Port |
|---------|---------|------|
| **FastAPI app** | HTTP API server | 8000 |
| **ARQ worker** | Background file processing | (no port, connects to Redis) |
| **PostgreSQL** | Relational data (users, workspaces, file metadata) | 5432 |
| **MinIO** | S3-compatible object storage for file binaries | 9000 (API), 9001 (console) |
| **Redis** | Message broker for ARQ task queue | 6379 |
| **Milvus** | Vector database for RAG embeddings | 19530 |

### Project Structure (new files only)

```
src/
  files/                    # File upload module
    __init__.py
    constants.py            # Limits, MIME types, templates
    exceptions.py           # Custom exception hierarchy
    models.py               # FileAttachment ORM model
    schemas.py              # Pydantic response schemas
    dependencies.py         # FastAPI dependency injection
    service.py              # Business logic (FileService)
    storage.py              # MinIO client wrapper
    router.py               # HTTP endpoints

  processing/               # Background processing module
    __init__.py
    worker.py               # ARQ worker config
    tasks.py                # Task dispatcher
    documents.py            # Text extraction + chunking
    images.py               # Thumbnail generation

  config/
    config_.py              # Added MinIOConfig, RedisConfig

  rag/
    vector_store.py         # Added workspace vectorstore + delete
    ingestion.py            # Added ingest_file_chunks()

tests/
  conftest.py               # Shared test fixtures
  unit/                     # 74 unit tests
  integration/              # 22 integration tests

Dockerfile                  # Multi-target (app + worker)
.dockerignore
docker-compose.yaml         # Full service stack
```

---

## 3. Phase 1: Storage Foundation

This phase defines the data models, constants, exception types, and the MinIO storage client. These are the building blocks everything else uses.

### 3.1 Constants (`src/files/constants.py`)

```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
```

This is 50 megabytes in bytes. The multiplication makes it readable: `50 * 1024 * 1024` = 50 MB.

```python
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/webp",
}
```

A **set** (not list) of allowed MIME types. Sets give O(1) lookup, so `if detected_mime not in ALLOWED_MIME_TYPES` is very fast. We also split them into `DOCUMENT_MIME_TYPES` and `IMAGE_MIME_TYPES` subsets so the processing pipeline knows which handler to use.

```python
STORAGE_KEY_TEMPLATE = "workspaces/{workspace_id}/chatrooms/{chatroom_id}/{file_id}{ext}"
```

This is the path inside MinIO. Example: `workspaces/abc-123/chatrooms/general/def-456.pdf`. Files not tied to a chatroom use `"general"` as the chatroom part.

```python
THUMBNAIL_SIZE = (300, 300)
```

Maximum thumbnail dimensions. Pillow's `thumbnail()` method preserves aspect ratio, so a 1000x500 image becomes 300x150 (not 300x300).

### 3.2 Exceptions (`src/files/exceptions.py`)

```python
class FileError(Exception):           # Base - catches all file errors
class FileTooLarge(FileError):         # .size, .max_size
class UnsupportedFileType(FileError):  # .mime_type
class FileNotFoundError(FileError):    # .file_id
class StorageError(FileError):         # .operation, .detail
```

**Why a hierarchy?** You can catch `FileError` to handle any file-related problem, or catch specific subclasses for targeted handling. The router catches `FileTooLarge` and returns HTTP 413, catches `UnsupportedFileType` and returns HTTP 415.

Each exception stores structured data (`.size`, `.mime_type`, etc.) so callers can inspect what went wrong, not just read a string message.

### 3.3 The FileAttachment Model (`src/files/models.py`)

This is the core database table. Let's break it apart:

```python
class ProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
```

**State machine**: `UPLOADED -> PROCESSING -> INDEXED` (happy path) or `UPLOADED -> PROCESSING -> FAILED` (error). It inherits from both `str` and `Enum` so it serializes cleanly to JSON (as the string value, not `ProcessingStatus.UPLOADED`).

The column uses `PgEnum` (PostgreSQL-native enum) rather than storing a plain string. This is more type-safe at the database level.

```python
class FileAttachment(Base):
    __tablename__ = "file_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

- `UUID(as_uuid=True)` - stores as PostgreSQL native `UUID` type, Python gets a `uuid.UUID` object (not a string)
- `default=uuid.uuid4` - **note: no parentheses!** This passes the function itself, not the result. SQLAlchemy calls `uuid.uuid4()` each time a new row is created. If you wrote `uuid.uuid4()`, every row would get the same ID.

```python
    workspace_id = mapped_column(UUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    chatroom_id = mapped_column(UUID, ForeignKey("chatrooms.id", ondelete="SET NULL"), nullable=True, index=True)
    uploader_id = mapped_column(UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
```

Foreign keys with different delete behaviors:
- `CASCADE` on workspace: if a workspace is deleted, all its files are deleted too
- `SET NULL` on chatroom/uploader: if a chatroom or user is deleted, the file survives but loses the reference

```python
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
```

- `storage_key` is the path inside MinIO (unique per file)
- `checksum` is a SHA-256 hash of the file content (64 hex chars), useful for deduplication or integrity checks

```python
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        PgEnum(ProcessingStatus, name="processing_status_enum", create_type=True),
        ...
    )
```

`create_type=True` tells SQLAlchemy to run `CREATE TYPE processing_status_enum AS ENUM (...)` in PostgreSQL. This creates a custom type at the database level.

```python
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
```

**Soft deletion**: instead of `DELETE FROM file_attachments WHERE id = ...`, we set `deleted_at = now()`. The row stays in the database but all queries filter with `WHERE deleted_at IS NULL`. This makes deletion reversible and preserves audit trails.

```python
    __table_args__ = (
        Index("ix_file_workspace_created", "workspace_id", "created_at"),
        Index("ix_file_active", "workspace_id", "created_at",
              postgresql_where=text("deleted_at IS NULL")),
    )
```

**Composite indexes** speed up common queries. The **partial index** (`postgresql_where=...`) only indexes non-deleted files, making the "list active files" query faster and the index smaller.

#### The `message_files` Association Table

```python
message_files = Table(
    "message_files", Base.metadata,
    Column("message_id", UUID, ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
    Column("file_id", UUID, ForeignKey("file_attachments.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(), server_default=text("now()")),
)
```

This is a **many-to-many join table**: one message can have many files, one file can be attached to many messages. The composite primary key `(message_id, file_id)` prevents duplicate attachments. `server_default=text("now()")` means PostgreSQL generates the timestamp, not Python.

### 3.4 MinIO Storage Client (`src/files/storage.py`)

```python
class MinIOStorage:
    def __init__(self, internal_endpoint, external_endpoint, ...):
        self._internal = Minio(internal_endpoint, ...)
        self._external = Minio(external_endpoint, ...)
```

**Two-client pattern** - this is the most important architectural decision in the storage layer:

- `_internal` (e.g., `minio:9000` in Docker): used for server-to-server operations (upload, download, delete). This is the Docker hostname, reachable only from within the Docker network.
- `_external` (e.g., `localhost:9000` from host): used only for generating **presigned URLs** that the user's browser will use to download files directly from MinIO. The browser can't reach `minio:9000`, but it can reach `localhost:9000`.

**Why presigned URLs?** Instead of streaming files through the FastAPI server (which ties up a worker thread), we generate a temporary signed URL that lets the browser download directly from MinIO. The URL expires after 15 minutes and includes a cryptographic signature so it can't be forged.

```python
async def upload_file(self, storage_key, data, size, content_type) -> str:
    result = await run_in_threadpool(
        self._internal.put_object, self.bucket_name, storage_key, data, size, ...
    )
```

**`run_in_threadpool`** - MinIO's Python client is synchronous (blocking I/O). In an async FastAPI app, blocking calls freeze the event loop. `run_in_threadpool` runs the blocking call in a separate thread, keeping the event loop free to handle other requests. This is FastAPI/Starlette's built-in solution for sync-in-async.

The `http_client` configured with connection pooling (`num_pools=10, maxsize=10`) and retries (`total=3, backoff_factor=0.2`) makes the client resilient to transient network issues.

### 3.5 Model Relationships

The `FileAttachment` model was wired into existing models:

```python
# In model/messaging.py - Workspace
files: Mapped[list["FileAttachment"]] = relationship("FileAttachment", back_populates="workspace")

# In model/messaging.py - Message
files: Mapped[list["FileAttachment"]] = relationship(
    "FileAttachment", secondary="message_files", back_populates="messages"
)
```

`back_populates` creates bidirectional navigation: `workspace.files` gives all files, `file.workspace` gives the workspace.

---

## 4. Phase 2: Upload & Download API

### 4.1 Pydantic Schemas (`src/files/schemas.py`)

```python
class FileMetadata(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    ...
    model_config = {"from_attributes": True}
```

`from_attributes = True` (formerly `orm_mode`) lets Pydantic read data from SQLAlchemy model attributes. Without this, `FileMetadata.model_validate(file_attachment_obj)` would fail because Pydantic expects a dict, not an ORM object.

### 4.2 Dependencies (`src/files/dependencies.py`)

```python
def get_workspace_member(workspace_id: uuid.UUID, user = Depends(active_user), db = ...) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id, ...))
    if workspace is None:
        raise HTTPException(404)
    if workspace.owner_id != user.id:
        raise HTTPException(403)
    return workspace
```

This is a **FastAPI dependency** - it runs before the endpoint function. When you write `workspace: Workspace = Depends(get_workspace_member)` in an endpoint, FastAPI:
1. Extracts `workspace_id` from the URL path
2. Gets `user` from the `active_user` dependency (which validates the JWT)
3. Gets `db` from `get_db` (which provides a database session)
4. Calls `get_workspace_member` with those values
5. If it returns, the endpoint proceeds with the workspace object
6. If it raises an HTTPException, the request is rejected

This keeps authorization logic DRY - every file endpoint just declares `Depends(get_workspace_member)` and gets automatic auth + workspace validation.

```python
def get_storage(request: Request) -> MinIOStorage:
    storage = getattr(request.app.state, "minio_storage", None)
    if storage is None:
        raise HTTPException(503, "Storage service not available")
    return storage
```

`request.app.state` is a shared object set during app startup. This pattern avoids global variables - the storage instance is created once in the lifespan and accessed via the request.

### 4.3 FileService (`src/files/service.py`)

The service layer contains all business logic, separate from HTTP concerns.

#### Upload Flow

```python
async def upload(self, file: UploadFile, workspace_id, uploader_id, chatroom_id=None):
    # 1. Read first 2048 bytes for MIME detection
    header = await file.read(2048)
    await file.seek(0)
    detected_mime = magic.from_buffer(header, mime=True)
```

**Why `magic.from_buffer` instead of trusting the Content-Type header?** The header is set by the client and can be spoofed. `python-magic` reads the actual bytes (the "magic bytes" or file signature) to detect the real type. For example, a `.pdf` starts with `%PDF`, a `.png` starts with `\x89PNG`.

```python
    # 2. Get file size by seeking to end
    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    file.file.seek(0)
```

`file.file` is the underlying Python file object. `seek(0, SEEK_END)` moves to the end, `tell()` gives the position (= file size), then `seek(0)` rewinds to the beginning so we can read the content for upload.

```python
    # 4. Compute SHA-256 checksum
    sha256 = hashlib.sha256()
    while chunk := file.file.read(1024 * 1024):
        sha256.update(chunk)
    checksum = sha256.hexdigest()
    file.file.seek(0)
```

The `:=` is the **walrus operator** (Python 3.8+). It reads 1MB at a time and assigns the result to `chunk`. When `read()` returns `b""` (end of file), the loop stops. Reading in chunks avoids loading the entire file into memory at once.

#### Cursor-Based Pagination

```python
def list_files(self, workspace_id, chatroom_id=None, cursor=None, limit=20):
    query = select(FileAttachment).where(...).order_by(
        FileAttachment.created_at.desc(), FileAttachment.id.desc()
    ).limit(limit + 1)  # fetch one extra to know if there's more
```

**Why `limit + 1`?** If we ask for 20 files and get 21 back, we know there's a next page. We return only the first 20 and use the last one's timestamp+ID as the cursor.

```python
    if cursor is not None:
        ts_str, id_str = cursor.split("|", 1)
        cursor_ts = datetime.fromisoformat(ts_str)
        cursor_id = uuid.UUID(id_str)
        query = query.where(
            (FileAttachment.created_at < cursor_ts) |
            ((FileAttachment.created_at == cursor_ts) & (FileAttachment.id < cursor_id))
        )
```

The cursor format is `"2026-03-07T00:40:19.238184|de3761c5-..."`. The query says: "give me files created before this timestamp, OR created at the same timestamp but with a smaller ID." This handles the edge case where multiple files have the same `created_at`.

**Why cursor pagination instead of OFFSET?**
- `OFFSET 1000` makes PostgreSQL scan and discard 1000 rows. Slow for large datasets.
- Cursor pagination uses an index (`ix_file_workspace_created`) to jump directly to the right position. Consistently fast regardless of page number.

#### Soft Delete

```python
def soft_delete(self, file_id, workspace_id):
    file = self.get_file(file_id, workspace_id)
    file.deleted_at = datetime.now()
    self.db.commit()

    try:
        from rag.vector_store import delete_file_chunks
        delete_file_chunks(str(file_id))
    except Exception:
        logger.warning("Failed to delete file chunks from vector store")
```

Two things happen on delete:
1. Set `deleted_at` in PostgreSQL (reversible)
2. Try to remove vector embeddings from Milvus (best-effort, wrapped in try/except)

The `from rag.vector_store import delete_file_chunks` is a **lazy import** - it only loads the RAG module when actually needed. This avoids importing heavy ML libraries (torch, langchain) during normal file operations.

### 4.4 Router (`src/files/router.py`)

Seven endpoints, all under `/api`:

| Method | Path | Status | Purpose |
|--------|------|--------|---------|
| `POST` | `/workspaces/{id}/files` | 202 | Upload file |
| `GET` | `/workspaces/{id}/files/{fid}` | 200 | Get metadata |
| `GET` | `/workspaces/{id}/files/{fid}/download` | 200 | Get download URL |
| `GET` | `/workspaces/{id}/files/{fid}/status` | 200 | Processing status |
| `GET` | `/workspaces/{id}/files` | 200 | List files |
| `DELETE` | `/workspaces/{id}/files/{fid}` | 200 | Soft delete |
| `POST` | `/workspaces/{id}/.../messages/{mid}/files` | 200 | Attach to message |

**Why 202 for upload?** HTTP 202 means "Accepted" - the file is stored, but processing hasn't completed yet. The client can poll the `/status` endpoint to check progress.

```python
async def upload_file(request: Request, ...):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(413, "File exceeds maximum size")
```

**Two-layer size check**: First checks `Content-Length` header (fast, before reading body), then `FileService.upload` checks actual size (authoritative, after reading). This is defense in depth - the header check rejects obviously oversized requests early without wasting bandwidth.

```python
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        await arq_pool.enqueue_job("process_file", str(db_file.id), _job_id=f"process_{db_file.id}")
```

After upload, the endpoint enqueues a background job. `_job_id=f"process_{db_file.id}"` ensures idempotency - if the same file ID is enqueued twice, ARQ deduplicates by job ID. The `if arq_pool is not None` check means the app works even without Redis (graceful degradation).

---

## 5. Phase 3: Background Processing

### 5.1 ARQ Worker (`src/processing/worker.py`)

ARQ is a lightweight async task queue backed by Redis (like Celery, but async and simpler).

```python
class WorkerSettings:
    functions = [func(process_file, max_tries=3)]
    redis_settings = get_redis_settings()
    on_startup = on_startup
    max_jobs = 5
    job_timeout = 600  # 10 minutes
```

- `max_tries=3`: if processing fails, ARQ retries up to 3 times
- `max_jobs=5`: process up to 5 files concurrently
- `job_timeout=600`: kill the job if it takes longer than 10 minutes

The `on_startup` hook creates a `SessionLocal` factory and `MinIOStorage` instance, stored in `ctx` (the ARQ context dict). Every job function receives this `ctx` as its first argument.

```python
def get_redis_settings() -> RedisSettings:
    redis_url = cfg.redis.url  # e.g., "redis://localhost:6379/0"
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
    )
```

Parses a standard Redis URL into ARQ's settings format. The path part (`/0`, `/1`) is the Redis database number.

### 5.2 Task Dispatcher (`src/processing/tasks.py`)

```python
async def process_file(ctx: dict, file_id: str):
    db_factory = ctx["db_session_factory"]
    storage = ctx["minio_storage"]

    with db_factory() as db:
        file_record = db.get(FileAttachment, uuid.UUID(file_id))
```

The dispatcher follows the **strategy pattern**: based on the file's MIME type, it delegates to either `process_document` or `process_image`.

```python
        try:
            if file_record.content_type in DOCUMENT_MIME_TYPES:
                from processing.documents import process_document
                await process_document(file_record, db, storage)
            elif file_record.content_type in IMAGE_MIME_TYPES:
                from processing.images import process_image
                await process_image(file_record, db, storage)

            file_record.processing_status = ProcessingStatus.INDEXED
            db.commit()

        except Exception as e:
            db.rollback()
            file_record = db.get(FileAttachment, uuid.UUID(file_id))
            file_record.processing_status = ProcessingStatus.FAILED
            file_record.processing_error = str(e)[:2048]
            db.commit()
            raise  # Let ARQ retry
```

The error handling pattern:
1. `db.rollback()` - undo any partial changes from the failed processing
2. Re-fetch the record (the old one may be stale after rollback)
3. Set status to FAILED with the error message (truncated to 2048 chars)
4. `raise` - re-raise so ARQ knows the job failed and can retry

### 5.3 Document Processing (`src/processing/documents.py`)

The pipeline: **Download -> Extract text -> Chunk -> Ingest into Milvus**

```python
async def process_document(file_record, db, storage):
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await storage.download_file_to_path(file_record.storage_key, tmp_path)
        elements = _extract_text(tmp_path, file_record.content_type)
        ...
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
```

**Temp file pattern**: Download to a temp file (not memory) because `unstructured` and other extraction libraries expect file paths. The `finally` block guarantees cleanup even if processing fails. `delete=False` in `NamedTemporaryFile` prevents auto-deletion so we control the lifecycle.

```python
def _extract_text(file_path, content_type):
    try:
        from unstructured.partition.auto import partition
        elements = partition(filename=file_path, strategy="fast")
        return [(el.text, {"page_number": ...}) for el in elements]
    except ImportError:
        return _fallback_extract(file_path, content_type)
```

**Graceful degradation**: `unstructured` is a heavy library that may not be installed. If it's missing, we fall back to simple text reading for `.txt` and `.md` files. PDFs require `unstructured` - without it, they return empty.

```python
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=global_rag_config.chunk_size,   # default: 1000 chars
        chunk_overlap=global_rag_config.chunk_overlap,  # default: 200 chars
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
```

**Chunking**: splits documents into overlapping pieces. The overlap ensures that information at chunk boundaries isn't lost. The separators list means: prefer to split at paragraph breaks, then newlines, then sentences, then words, then characters (last resort).

### 5.4 Image Processing (`src/processing/images.py`)

```python
async def process_image(file_record, db, storage):
    with Image.open(tmp_path) as img:
        img.thumbnail(THUMBNAIL_SIZE)  # (300, 300), preserves aspect ratio
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")   # JPEG doesn't support transparency
        thumb_buffer = BytesIO()
        img.save(thumb_buffer, format="JPEG", quality=85)
```

- `thumbnail()` resizes in-place, preserving aspect ratio (never upscales)
- RGBA (transparent PNG) and P (palette/GIF) modes must be converted to RGB for JPEG output
- Quality 85 is a good balance between file size and visual quality

The thumbnail is uploaded with key `{original_key}_thumb.jpg` and the `thumbnail_storage_key` column is updated on the record.

---

## 6. Phase 4: RAG Integration

### 6.1 Workspace Vector Store (`src/rag/vector_store.py`)

```python
WORKSPACE_COLLECTION = "talos_documents"

def get_workspace_vectorstore(collection_name=WORKSPACE_COLLECTION, ...):
    return Milvus(
        embedding_function=embeddings,
        collection_name=collection_name,
        auto_id=True,
        enable_dynamic_field=True,
    )
```

All workspace files go into a single Milvus collection (`talos_documents`). `enable_dynamic_field=True` lets us store arbitrary metadata (workspace_id, file_id, filename, page_number) without defining a rigid schema upfront.

Filtering by workspace happens at query time with Milvus expressions like `workspace_id == "abc-123"`.

```python
def delete_file_chunks(file_id, collection_name=WORKSPACE_COLLECTION):
    client = MilvusClient(uri=f"http://{host}:{port}")
    client.delete(collection_name=collection_name, filter=f'file_id == "{file_id}"')
```

When a file is soft-deleted, we remove its vectors from Milvus so they don't pollute search results.

### 6.2 Ingestion (`src/rag/ingestion.py`)

```python
def ingest_file_chunks(chunks, workspace_id, file_id):
    for chunk in chunks:
        chunk.metadata.setdefault("workspace_id", workspace_id)
        chunk.metadata.setdefault("file_id", file_id)
    vectorstore = get_workspace_vectorstore()
    vectorstore.add_documents(chunks)
```

`setdefault` adds metadata only if not already present (non-destructive). `add_documents` embeds the text (via OpenAI or HuggingFace) and stores the vectors + metadata in Milvus.

### 6.3 Workspace-Aware RAG Chain (`src/rag/rag_chain.py`)

```python
class RAGChain:
    def __init__(self, collection_name, config, workspace_id=None):
        if workspace_id:
            self.vectorstore = get_workspace_vectorstore(embeddings=self.hyde)
            extra_search_kwargs = {"expr": f'workspace_id == "{workspace_id}"'}
        else:
            self.vectorstore = get_vectorstore(collection_name, embeddings=self.hyde)
            extra_search_kwargs = None

        self.retriever = get_retriever(
            vectorstore=self.vectorstore,
            search_kwargs=extra_search_kwargs,
        )
```

When a `workspace_id` is provided, the retriever adds a Milvus filter expression so it only searches documents belonging to that workspace.

### 6.4 Updated Citations (`src/rag/ingestion.py`)

```python
def format_citations(documents):
    for doc in documents:
        filename = doc.metadata.get("filename")
        file_id = doc.metadata.get("file_id")
        if filename:
            citation = f"{filename}, p.{page}" if page else filename
            if file_id:
                citation += f" (file:{file_id})"
        else:
            citation = doc.metadata.get("source", "unknown")
```

Citations now handle two formats: workspace files (with `filename` + `file_id`) and CLI-loaded documents (with `source` path).

---

## 7. Phase 5: Docker & Config

### 7.1 Configuration (`src/config/config_.py`)

```python
class MinIOConfig(BaseModel):
    internal_endpoint: str = "localhost:9000"
    external_endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    secure: bool = False
    bucket_name: str = "talos-uploads"

class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379"

class Config(BaseSettings):
    minio: MinIOConfig = MinIOConfig()
    redis: RedisConfig = RedisConfig()
    model_config = SettingsConfigDict(env_nested_delimiter="__", ...)
```

`env_nested_delimiter="__"` means you can set `MINIO__INTERNAL_ENDPOINT=minio:9000` as an environment variable, and pydantic-settings maps it to `config.minio.internal_endpoint`. The double underscore acts as a path separator.

### 7.2 Dockerfile

```dockerfile
FROM python:3.13-slim AS base
# ... shared setup (deps, source code) ...

FROM base AS app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
CMD ["arq", "processing.worker.WorkerSettings"]
```

**Multi-target build**: both the app and worker share the same base image (same Python, same dependencies, same source code). The only difference is the `CMD`. Build with `docker build --target app .` or `--target worker .`.

**Layer caching**: `COPY pyproject.toml uv.lock ./` then `RUN uv sync` happens before `COPY src/ ./src/`. This means changing source code doesn't re-install dependencies (cache hit on the dependency layer).

### 7.3 App Lifespan (`app.py`)

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup
    Base.metadata.create_all(engine)    # Create tables
    storage = _get_minio_storage()
    await storage.ensure_bucket()        # Create MinIO bucket
    app.state.minio_storage = storage    # Store for dependency injection

    try:
        app.state.arq_pool = await create_pool(get_redis_settings())
    except Exception:
        app.state.arq_pool = None        # App works without Redis

    yield  # App is running

    # Shutdown
    if app.state.arq_pool:
        await app.state.arq_pool.aclose()
```

The **lifespan context manager** replaces the old `@app.on_event("startup")` pattern. Everything before `yield` runs on startup, everything after runs on shutdown.

---

## 8. Phase 6: Testing

### 8.1 Test Architecture

Two tiers:

- **Unit tests** (74): mock everything external (DB, MinIO, Milvus). Test pure logic. No services needed.
- **Integration tests** (22): real PostgreSQL, mocked MinIO/Redis. Test actual SQL queries, API responses, and dependency injection.

### 8.2 Key Testing Challenges Solved

**Problem 1: SQLAlchemy creates the DB engine at import time.**

`model/base.py` runs `engine = create_engine(config().database_url)` at module level. Solution: `tests/conftest.py` sets `os.environ["DATABASE_URL"]` before any src imports.

**Problem 2: RAG modules trigger heavy import chains.**

`rag/__init__.py` does `from .generation import *` which imports `langchain_openai` (not installed in test env). Solution: for unit tests, we use `importlib.util.spec_from_file_location` to load individual RAG modules directly, bypassing `__init__.py`. For service tests, we use `patch.dict("sys.modules", ...)` to mock the RAG modules.

**Problem 3: FileAttachment relationships need related models imported first.**

SQLAlchemy's `relationship("User")` resolves by name. If `User` class hasn't been imported/registered with Base.metadata, it fails. Solution: `tests/conftest.py` imports `model.identity` and `model.messaging` before `files.models`.

### 8.3 Integration Test Setup

```python
# tests/integration/conftest.py
@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)    # Create all tables once
    yield engine
    Base.metadata.drop_all(engine)      # Clean up after all tests

@pytest.fixture
def db_session(test_engine):
    session = sessionmaker(bind=test_engine)()
    yield session
    session.rollback()    # Undo everything this test did
    session.close()
```

Each test gets a fresh session that rolls back after the test. This means tests don't affect each other and the database stays clean without needing to re-create tables.

```python
@pytest.fixture
def client(db_session, test_user, test_workspace, mock_storage):
    app.dependency_overrides[active_user] = lambda: test_user
    app.dependency_overrides[get_workspace_member] = lambda: test_workspace
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: mock_storage
```

**FastAPI dependency overrides** replace real dependencies with test doubles. The real `active_user` validates a JWT token - the override just returns a pre-created test user. This lets us test the file endpoints without setting up the full auth system.

---

## 9. Data Flow Walkthroughs

### 9.1 User Uploads a PDF

```
1. POST /api/workspaces/{ws_id}/files with multipart form data
   |
2. Router: check Content-Length header (fast reject if > 50MB)
   |
3. Dependencies resolve:
   - active_user: validates JWT -> returns User
   - get_workspace_member: checks user owns workspace -> returns Workspace
   - get_db: opens DB session
   - get_storage: returns MinIOStorage from app.state
   |
4. FileService.upload():
   a. Read 2048 bytes, detect MIME with python-magic -> "application/pdf"
   b. Check MIME is in ALLOWED_MIME_TYPES -> pass
   c. Seek to end, get file size -> check < 50MB -> pass
   d. Generate UUID file_id + storage_key
   e. Compute SHA-256 checksum (read file in 1MB chunks)
   f. Upload to MinIO via _internal client
   g. Insert FileAttachment row (status=UPLOADED) into PostgreSQL
   |
5. Enqueue ARQ job: process_file(file_id)
   |
6. Return 202 with {file_id, status: "uploaded", filename, content_type, size_bytes}
```

### 9.2 Worker Processes the PDF

```
1. ARQ picks up "process_file" job from Redis
   |
2. process_file() in tasks.py:
   a. Open DB session from factory
   b. Fetch FileAttachment by ID
   c. Set status = PROCESSING, commit
   d. content_type is "application/pdf" -> in DOCUMENT_MIME_TYPES
   e. Call process_document()
   |
3. process_document() in documents.py:
   a. Download PDF from MinIO to /tmp/abc123.pdf
   b. _extract_text() tries `unstructured.partition.auto.partition`
      -> Returns list of (text, {page_number}) tuples
   c. Build LangChain Document objects with metadata
   d. Split into chunks (1000 chars, 200 overlap)
   e. ingest_file_chunks() -> embed with OpenAI -> store in Milvus
   f. Set chunk_count on the record, commit
   g. Delete temp file
   |
4. Back in process_file():
   a. Set status = INDEXED, commit
```

### 9.3 User Searches Their Workspace Files

```
1. RAGChain(collection_name="...", workspace_id="ws-123")
   |
2. Retriever created with search_kwargs={"expr": 'workspace_id == "ws-123"'}
   |
3. User asks a question
   |
4. Query rewriter reformulates the question
   |
5. Milvus similarity search with workspace filter
   -> Returns relevant chunks from only this workspace's files
   |
6. LLM generates answer using the retrieved context
   |
7. Citations formatted: "[1] report.pdf, p.5 (file:abc-123)"
```

---

## 10. Key Design Decisions

### Why MinIO instead of local filesystem?
- Works identically in dev and production
- Presigned URLs offload bandwidth from the app server
- Scales horizontally (MinIO clusters)
- S3-compatible, so switching to AWS S3 later is a config change

### Why ARQ instead of Celery?
- Native async/await (matches FastAPI)
- Much simpler (single file config vs Celery's complex setup)
- Redis-only (no RabbitMQ needed)
- Good enough for our scale

### Why soft delete instead of hard delete?
- Reversible (can "undelete" by setting `deleted_at = NULL`)
- Audit trail (you can see when something was deleted)
- Referential integrity (no dangling foreign keys from other tables)
- The partial index `WHERE deleted_at IS NULL` keeps queries fast

### Why cursor pagination instead of offset?
- `OFFSET 10000` scans 10000 rows then discards them. Slow.
- Cursor uses an index to jump directly to the right position. O(log n).
- Consistent results even when new files are uploaded between pages.

### Why two MinIO clients?
- Docker networking: containers talk to each other via hostnames (`minio:9000`)
- Browsers talk via the host machine (`localhost:9000`)
- Presigned URLs must use the external endpoint (browser-reachable)
- All other ops use the internal endpoint (faster, no NAT)

### Why lazy imports for RAG?
- `rag/__init__.py` imports torch, langchain_openai, pymilvus - takes seconds
- File upload shouldn't pay this cost on every request
- `from rag.vector_store import delete_file_chunks` inside `soft_delete()` only loads when actually deleting

---

## 11. Glossary

| Term | Meaning |
|------|---------|
| **ARQ** | Async Redis Queue - Python task queue library |
| **MIME type** | Media type identifier (e.g., `application/pdf`, `image/png`) |
| **Magic bytes** | First bytes of a file that identify its type (e.g., `%PDF`, `\x89PNG`) |
| **Presigned URL** | Temporary URL with embedded auth signature for direct S3/MinIO access |
| **Soft delete** | Setting `deleted_at` instead of removing the row |
| **Cursor pagination** | Using a pointer (timestamp+ID) instead of OFFSET for paging |
| **ORM** | Object-Relational Mapping - SQLAlchemy translates Python classes to SQL |
| **Walrus operator** | `:=` - assigns and returns a value in one expression |
| **Lifespan** | FastAPI's startup/shutdown hook pattern |
| **Dependency injection** | FastAPI resolves function parameters via `Depends()` |
| **run_in_threadpool** | Runs blocking (sync) code in a thread to avoid blocking the async event loop |
| **Milvus** | Vector database for storing and searching embeddings |
| **Chunking** | Splitting documents into overlapping pieces for embedding |
| **RAG** | Retrieval-Augmented Generation - find relevant docs, then generate answers |
| **HyDE** | Hypothetical Document Embeddings - generates a fake answer to improve search |
| **Partial index** | Database index that only covers rows matching a condition |
| **Association table** | Join table for many-to-many relationships (`message_files`) |
