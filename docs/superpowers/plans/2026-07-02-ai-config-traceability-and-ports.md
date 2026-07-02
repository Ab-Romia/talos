# Workspace AI Config + Full Traceability + File-Pipeline Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the RAG system per-workspace configurable (channel overrides), fully traceable (timing, correlation id, selection-stage visibility, always-on trace digest), and port the file-pipeline fixes discovered in the integration session to this branch.

**Architecture:** A new rag-owned `ai_settings` table stores whitelisted JSONB overrides per workspace (nullable `channel_id` = workspace default; non-null = channel override). Resolution happens once per `/ask` inside the existing worker thread: `global_rag_config.model_copy(update=merged_overrides)` feeds the existing `config=` seam, so `RagTrace.effective_config` stays honest by construction; the trace additionally records per-field provenance, latency breakdown, a request id, and the chat-selection drop statistics. The file-processing task is fixed branch-appropriately (sync session, real column writes, workspace-scoped async MinIO download).

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (sync+async), pydantic v2, LangChain + Milvus, taskiq, s3fs (`MinIOFileSystem`), pytest.

## Global Constraints

- **Never modify teammate-owned files**: `src/chat/`, `src/auth/`, `src/filesystem/`, `src/app.py`, `docker-compose.yaml`, `src/database.py`, `src/permissions/`, `src/notifications/`. EXCEPTION granted for this plan (precedent: the `/ask` mount): `src/workspace/router.py` may gain exactly two `include_router` lines + one import line (Task 5), documented in the handoff doc.
- **Branch**: `feature/chat-message-memory`. Never commit to `main`.
- **Commits**: author `Ab-Romia <aabouroumia@gmail.com>`. NO AI attribution, NO `Co-Authored-By` lines, ever.
- **Run tests**: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` from `/home/romia/talos-main` (postgres-test container must be up: `docker compose up -d postgres-test`; never bare `uv run pytest`). Baseline before Task 1: `tests/rag tests/chat` = 68 passed. Suite must pass after every task.
- **Config chokepoint**: every new knob is a field on `RagConfig` in `src/config/config.py`.
- **Working tree**: 2 uncommitted owner TODO-comment diffs exist in `src/chat/model.py` and `src/chat/realtime.py` — leave untouched; always `git add` explicit paths, never `-A`.
- Permission strings that already exist and must be reused verbatim: `workspace:view`, `channel:view`, `workspace.role:manage` (no new permission strings — they'd need teammate registry seeding).

---

### Task 1: Port the file-pipeline fixes (branch-appropriate)

**Files:**
- Modify: `src/processing/tasks.py`
- Modify: `src/processing/documents.py:26-29` (download call)
- Test: `tests/processing/test_process_file.py` (new file; also create empty `tests/processing/__init__.py` if pytest requires it — it doesn't by default, skip unless collection fails)

**Interfaces:**
- Consumes: `filesystem.storage.minio.MinIOFileSystem(config: MinIOConfig, workspace_id: uuid.UUID, channel_id: uuid.UUID | None)` — async s3fs subclass whose `split_path` prepends `{bucket}/{ws_id}/{ch_id or '.'}` to relative paths; `File.uri` on this branch is `minio://<relative-virtual-path>` (workspace scoping is NOT in the uri — `split_path` re-adds it).
- Produces: a `process_file` task that actually works on this branch: claims via `processing_status`, downloads via the workspace-scoped filesystem, routes to `process_document`/`process_image`, and records terminal status in the real `processing_status` column.

Background (from the integration-session audit): this task has never executed successfully anywhere. Five defects: never enqueued (teammate-side, reported), wrong storage constructor + dead `download_file_to_path` API, sync `with` on `AsyncSessionLocal`, writes to `.status` (not a column on this branch — silent no-op), and `FileStatus.PROCESSING` doesn't exist (AttributeError). This task fixes everything that is OURS; the enqueue hook, `FileStatus.PROCESSING`, and `chunk_count`/`processing_error` columns are the filesystem owner's (Task 7 documents the report).

- [ ] **Step 1: Write the failing tests**

```python
# tests/processing/test_process_file.py
"""process_file: claim -> download (workspace-scoped) -> route -> stamp.
No Milvus/MinIO touched: storage and the document processor are faked."""
import uuid

import pytest
from sqlalchemy import select

from filesystem.model import File, FileStatus


@pytest.fixture
def uploaded_file(db_session, test_channel):
    f = File(
        id=uuid.uuid7(),
        workspace_id=test_channel.workspace_id,
        channel_id=test_channel.id,
        uploader_id=None,
        filename="note.txt",
        content_type="text/plain",
        size_bytes=10,
        processing_status=FileStatus.UPLOADED,
        uri="minio://docs/note.txt",
    )
    db_session.add(f)
    db_session.commit()
    yield f
    db_session.rollback()
    db_session.delete(f)
    db_session.commit()


class _FakeStorage:
    def __init__(self, config, workspace_id, channel_id=None):
        self.workspace_id = workspace_id
        self.channel_id = channel_id
        _FakeStorage.last = self


async def _fake_process_document(file_record, db, storage):
    _fake_process_document.called_with = (file_record.id, type(storage).__name__)


@pytest.mark.anyio
async def test_process_file_stamps_indexed_on_success(db_session, uploaded_file, monkeypatch):
    import processing.tasks as tasks
    monkeypatch.setattr(tasks, "MinIOFileSystem", _FakeStorage)
    monkeypatch.setattr("processing.documents.process_document", _fake_process_document)

    await tasks.process_file.original_func(uploaded_file.id)

    db_session.expire_all()
    row = db_session.scalar(select(File).where(File.id == uploaded_file.id))
    assert row.processing_status == FileStatus.INDEXED
    assert _FakeStorage.last.workspace_id == uploaded_file.workspace_id
    assert _FakeStorage.last.channel_id == uploaded_file.channel_id


@pytest.mark.anyio
async def test_process_file_stamps_failed_on_error(db_session, uploaded_file, monkeypatch):
    import processing.tasks as tasks
    monkeypatch.setattr(tasks, "MinIOFileSystem", _FakeStorage)

    async def _boom(file_record, db, storage):
        raise RuntimeError("parse exploded")
    monkeypatch.setattr("processing.documents.process_document", _boom)

    with pytest.raises(RuntimeError):
        await tasks.process_file.original_func(uploaded_file.id)

    db_session.expire_all()
    row = db_session.scalar(select(File).where(File.id == uploaded_file.id))
    assert row.processing_status == FileStatus.PROCESSING_FAILED
```

NOTE for the implementer: check `tests/conftest.py` for an anyio/asyncio marker convention — if the suite uses plain `asyncio.run` style instead of `pytest.mark.anyio`, convert the two tests to sync defs that call `asyncio.run(tasks.process_file.original_func(...))`. Also confirm the fixture names `db_session` and `test_channel` exist there (they are used by `tests/chat/test_chat_router.py`); `File.uploader_id` nullability — if NOT NULL, use `test_user.id` via the `test_user` fixture instead of `None`.

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/processing -q`
Expected: FAIL — `AttributeError` (`tasks.MinIOFileSystem` doesn't exist yet / `AsyncSessionLocal` misuse / `FileStatus.PROCESSING`).

- [ ] **Step 3: Rewrite `process_file`**

Replace the imports and the body of `src/processing/tasks.py` up to the `try:` block with:

```python
"""Task dispatcher for file processing."""

import uuid

from sqlalchemy import update as sa_update

from broker import broker
from config import cfg
from database import SessionLocal
from filesystem.model import File, FileStatus
from filesystem.storage.minio import MinIOFileSystem
from utils.logger import get_logger

logger = get_logger(__name__)


# TODO: retry, backoff, timeout..
@broker.task()
async def process_file(file_id: uuid.UUID):
    """Main task dispatcher. Routes to document or image processor by MIME type."""
    # The body is written sync-style (plain execute/commit, and the processors
    # take a sync Session) — use the sync factory, not AsyncSessionLocal.
    with SessionLocal() as db:
        # Atomically claim the file. NOTE: FileStatus has no in-flight
        # PROCESSING member (filesystem owner's model — reported); re-asserting
        # UPLOADED keeps the rowcount gate but NOT mutual exclusion. The
        # pre-ingest delete_file_chunks purge keeps output idempotent, so a
        # rare double-run costs compute, not correctness.
        result = db.execute(
            sa_update(File)
            .where(
                File.id == file_id,
                File.processing_status.in_([
                    FileStatus.UPLOADED,
                    FileStatus.PROCESSING_FAILED,
                ])
            )
            .values(processing_status=FileStatus.UPLOADED)
        )
        db.commit()

        if result.rowcount == 0:
            file_record = db.get(File, file_id)
            if file_record is None:
                logger.warning("File not found for processing", file_id=file_id)
            else:
                logger.info(
                    "File not in processable state, skipping",
                    file_id=file_id,
                    status=file_record.processing_status.value,
                )
            return

        file_record = db.get(File, file_id)
        if file_record is None:
            logger.warning("File row vanished after claim", file_id=file_id)
            return

        # Workspace-scoped storage: on this branch File.uri is a RELATIVE
        # virtual path ("minio://<parent>/<name>"); MinIOFileSystem.split_path
        # re-prepends {bucket}/{workspace}/{channel} — so the filesystem must
        # be constructed per file with the file's own scope.
        storage = MinIOFileSystem(
            cfg().minio,
            workspace_id=file_record.workspace_id,
            channel_id=file_record.channel_id,
        )
```

Keep the existing `try:` dispatch block that follows, changing ONLY the two terminal-status writes:
- `file_record.status = FileStatus.INDEXED` → `file_record.processing_status = FileStatus.INDEXED  # .status is not a column on this branch`
- `file_record.status = FileStatus.PROCESSING_FAILED` → `file_record.processing_status = FileStatus.PROCESSING_FAILED`

Leave `file_record.processing_error = str(e)[:2048]` in place but add the comment `# not a mapped column yet — silently dropped until the filesystem owner adds it (reported)`.

- [ ] **Step 4: Fix the download in `process_document`**

In `src/processing/documents.py`, replace:
```python
        # Download from MinIO
        await storage.download_file_to_path(file_record.id.hex, tmp_path)
```
with:
```python
        # Download from MinIO. File.uri is "minio://<relative-path>"; strip the
        # protocol only — the workspace-scoped MinIOFileSystem.split_path adds
        # bucket/workspace/channel. (download_file_to_path was a dead API.)
        rel_path = str(file_record.uri).removeprefix("minio://")
        await storage._get_file(rel_path, tmp_path)
```
NOTE: `MinIOFileSystem` is constructed `asynchronous=True`, so the async underscore API is correct. If `_get_file` raises `RuntimeError: Loop is not running`-style errors from s3fs, insert `await storage.set_session()` immediately after construction in `tasks.py` (guard with `if getattr(storage, "_s3", None) is None:`). Verify against the installed s3fs by running the tests.

Also change the same two `file_record.chunk_count = ...` lines in `documents.py` (lines ~51 and ~79) to keep working but gain the comment `# not a mapped column yet — silently dropped (reported to filesystem owner)`.

- [ ] **Step 5: Run tests, then the full suite**

Run: `IS_TEST=1 uv run python -m pytest tests/processing -q` → 2 passed
Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` → 70 passed

- [ ] **Step 6: Commit**

```bash
git add src/processing/tasks.py src/processing/documents.py tests/processing/test_process_file.py
git commit -m "fix(processing): make process_file executable — sync session, real status column, workspace-scoped download"
```

---

### Task 2: RagTrace timing + request id + always-on trace digest

**Files:**
- Modify: `src/rag/trace.py`
- Modify: `src/rag/rag_chain.py` (accept `request_id`, measure stages, fill new fields)
- Modify: `src/rag/router.py` (mint request id, log digest, add to ai_message payload)
- Test: `tests/rag/test_rag_chain.py`, `tests/rag/test_ask_endpoint.py` (extend)

**Interfaces:**
- Produces: `RagTrace` gains fields `request_id: str = ""`, `retrieval_ms: float = 0.0`, `generation_ms: float = 0.0`. `RAGChain.__init__` gains keyword `request_id: str | None = None`. The `ai_message` payload gains key `request_id`. Router emits one `logger.info("ask.trace", ...)` line on EVERY successful ask (not only debug).

- [ ] **Step 1: Write the failing tests**

Append to `tests/rag/test_rag_chain.py`:
```python
def test_trace_records_timing_and_request_id():
    captured = {}
    chain = _make_chain(captured)
    chain.request_id = "req-123"  # normally passed via __init__
    prepared = chain.prepare("q")
    "".join(chain.stream_answer(prepared, include_citations=False))
    assert chain.trace.request_id == "req-123"
    assert chain.trace.retrieval_ms >= 0.0
    assert chain.trace.generation_ms >= 0.0
```
And a constructor form: in the same test file add `RAGChain(..., request_id="req-456")` to `_make_chain`'s kwargs path OR simply add a second assertion-style test:
```python
def test_request_id_constructor_arg():
    captured = {}
    chain = _make_chain(captured)
    assert hasattr(chain, "request_id")
```
(implementer: wire `request_id` through `_make_chain` by adding `request_id="req-123"` to the `RAGChain(...)` call inside it, then assert `chain.trace.request_id == "req-123"` in the first test and drop the manual attribute set).

Extend `tests/rag/test_ask_endpoint.py::test_ask_broadcasts_ai_message_to_channel_room` with:
```python
    assert payload["request_id"]
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_rag_chain.py tests/rag/test_ask_endpoint.py -q`
Expected: new assertions FAIL (no such fields).

- [ ] **Step 3: Implement**

`src/rag/trace.py` — add three fields to the dataclass (after `embedding_provider`):
```python
    request_id: str = ""
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
```

`src/rag/rag_chain.py`:
- Add `request_id: str | None = None` to `__init__` params; store `self.request_id = request_id or ""`; init `self._retrieval_ms = 0.0`, `self._generation_ms = 0.0`.
- In `prepare()`, wrap the retrieval body: `t0 = time.perf_counter()` before `docs = self._rewrite_and_retrieve(question)` and `self._retrieval_ms = (time.perf_counter() - t0) * 1000.0` after `context = self._format_docs(docs)` (add `import time` at top).
- In `stream_answer()`, wrap the token loop: `t0 = time.perf_counter()` before the `for chunk in (...)` loop; set `self._generation_ms = (time.perf_counter() - t0) * 1000.0` right after the loop, BEFORE `self._fill_trace(...)`.
- In `_fill_trace()`, pass the new fields into the `RagTrace(...)` construction: `request_id=self.request_id, retrieval_ms=round(self._retrieval_ms, 1), generation_ms=round(self._generation_ms, 1),`.

`src/rag/router.py`:
- At the top of `ask_question`, after resolving `workspace_id`: `request_id = str(uuid.uuid7())` (add `import uuid` to imports if absent — check first).
- Pass `request_id=request_id` into the `RAGChain(...)` construction inside `_build_and_prepare`.
- In `stream()`, after `_broadcast_ai_message(...)`, add the always-on digest:
```python
            t = chain.trace
            logger.info(
                "ask.trace",
                request_id=request_id,
                channel_id=str(channel_id),
                model=t.model,
                n_file=len(t.file_candidates),
                n_chat=len(t.chat_candidates),
                retrieval_ms=t.retrieval_ms,
                generation_ms=t.generation_ms,
                answer_chars=len(answer),
            )
```
- In `_broadcast_ai_message`, add parameter `request_id: str` and payload key `"request_id": request_id`; update the call site.
- Thread `request_id=request_id` into the existing `logger.exception("ask retrieval failed", ...)` and `logger.exception("ask generation failed", ...)` calls.

- [ ] **Step 4: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` → all pass (72 expected: 70 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/rag/trace.py src/rag/rag_chain.py src/rag/router.py tests/rag/test_rag_chain.py tests/rag/test_ask_endpoint.py
git commit -m "feat(rag): request-id correlation, stage timing, always-on trace digest"
```

---

### Task 3: Make the chat-selection stage visible in the trace

**Files:**
- Modify: `src/rag/retrieval/chat_selection.py` (optional stats out-param)
- Modify: `src/rag/rag_chain.py` (`_retrieve_chat` collects stats; `_fill_trace` records them)
- Modify: `src/rag/trace.py` (one field)
- Test: `tests/rag/test_chat_selection.py`, `tests/rag/test_chat_recall_dedupe.py` (extend)

**Interfaces:**
- Produces: `select_chat_context(candidates, *, k, now, half_life_hours, overlap_threshold, stats: dict | None = None)` — when `stats` is given, it is filled with `{"considered": int, "dropped_redundant": int, "kept": int}`. `RagTrace` gains `chat_selection: dict` recording `{"fetched": int, "dropped_tail": int, "dropped_redundant": int, "kept": int}`. `chat_candidates` stays post-selection (unchanged meaning).

- [ ] **Step 1: Write the failing tests**

Append to `tests/rag/test_chat_selection.py`:
```python
def test_stats_reports_drops_and_keeps():
    docs = [
        _doc("staging database runs on port 5544", hours_old=1),
        _doc("staging database runs on port 5544 !", hours_old=1),   # near-dupe
        _doc("prod key lives in the vault", hours_old=1),
        _doc("unrelated fourth candidate", hours_old=1),
    ]
    stats = {}
    out = select_chat_context(docs, k=2, now=NOW, half_life_hours=168,
                              overlap_threshold=0.6, stats=stats)
    assert stats == {"considered": 4, "dropped_redundant": 1, "kept": 2}
    assert len(out) == 2
```
Append to `tests/rag/test_chat_recall_dedupe.py` (follow that file's existing chain-construction style — it builds a RAGChain with an injected fake chat_retriever):
```python
def test_trace_records_chat_selection_stats():
    # fake retriever returns 3 docs, 1 excluded via tail overlap
    chain = _make_chain_with_chat_docs()  # reuse/adapt the file's existing helper
    chain.prepare("q")
    sel = chain.last_chat_selection
    assert sel["fetched"] == 3
    assert sel["dropped_tail"] == 1
    assert sel["kept"] == sel["fetched"] - sel["dropped_tail"] - sel["dropped_redundant"]
```
(implementer: adapt helper names to what the file actually defines — the assertions are the contract.)

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_chat_selection.py tests/rag/test_chat_recall_dedupe.py -q` → new tests FAIL.

- [ ] **Step 3: Implement**

`src/rag/retrieval/chat_selection.py` — add the keyword param and fill it:
```python
def select_chat_context(
    candidates: list[Document],
    *,
    k: int,
    now: datetime,
    half_life_hours: float,
    overlap_threshold: float,
    stats: dict | None = None,
) -> list[Document]:
```
and at the end, before `return picked`:
```python
    if stats is not None:
        stats["considered"] = len(candidates)
        stats["dropped_redundant"] = dropped_redundant
        stats["kept"] = len(picked)
```
where `dropped_redundant` is a counter incremented in the existing `continue` branch of the greedy loop (`dropped_redundant = 0` initialized before the loop; note: candidates skipped only because `len(picked) >= k` are NOT redundant — the loop `break`s at k before checking overlap, so the existing structure already distinguishes them; verify the `break` precedes the Jaccard check and count only Jaccard skips).

`src/rag/rag_chain.py` `_retrieve_chat` — collect the full picture:
```python
            fetched = len(docs)
            # ... existing tail-overlap filter produces `docs` ...
            dropped_tail = fetched - len(docs)
            sel_stats: dict = {}
            docs = select_chat_context(
                docs, k=..., now=..., half_life_hours=..., overlap_threshold=...,
                stats=sel_stats,
            )
            self.last_chat_selection = {
                "fetched": fetched,
                "dropped_tail": dropped_tail,
                "dropped_redundant": sel_stats.get("dropped_redundant", 0),
                "kept": len(docs),
            }
            return docs
```
(keep the existing argument values exactly as they are today; initialize `self.last_chat_selection = {}` in `__init__` so the no-chat-retriever path is safe; the `return []` degradation path should also leave it as `{}`.)

`src/rag/trace.py` — add field `chat_selection: dict = field(default_factory=dict)`; `src/rag/rag_chain.py` `_fill_trace` passes `chat_selection=dict(self.last_chat_selection)`.

- [ ] **Step 4: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rag/retrieval/chat_selection.py src/rag/rag_chain.py src/rag/trace.py tests/rag/test_chat_selection.py tests/rag/test_chat_recall_dedupe.py
git commit -m "feat(rag): chat-selection stage is now visible in the trace (pool, drop reasons)"
```

---

### Task 4: `ai_settings` storage, whitelist, and resolver

**Files:**
- Create: `src/rag/ai_settings.py`
- Modify: `src/config/config.py` (model allow-list field)
- Modify: `src/rag/__init__.py` (import for table registration)
- Test: `tests/rag/test_ai_settings.py`

**Interfaces:**
- Produces (Tasks 5–6 depend on these exact names):
  - `class AiSettings(Base)` — table `ai_settings`: `id` uuid pk, `workspace_id` uuid FK→workspaces.id CASCADE, `channel_id` uuid|None FK→channels.id CASCADE, `overrides` JSONB default `{}`, `updated_at` timestamptz. Partial unique index `UNIQUE(workspace_id) WHERE channel_id IS NULL` + `UniqueConstraint(workspace_id, channel_id)`.
  - `class AiConfigPatch(BaseModel)` — all-Optional whitelist fields with bounds (below); `model_config = ConfigDict(extra="forbid")`.
  - `resolve_ai_config(workspace_id, channel_id, db) -> tuple[RagConfig, dict]` — returns the effective config and a provenance dict `{field: "global"|"workspace"|"channel"}` covering every whitelist field.
  - `OVERRIDABLE: tuple[str, ...]` — the whitelist.
  - New `RagConfig` field: `ai_model_allow_list: list[str] = ["gpt-4o-mini", "gpt-4o", "qwen2.5:7b-instruct"]`.

Whitelist (exactly these): `use_hyde`, `use_query_rewrite`, `use_reranking`, `retrieval_top_k` (1–50), `rerank_fetch_k` (1–100), `chat_recall_k` (0–10), `chat_recall_fetch_k` (1–50), `chat_decay_half_life_hours` (1–8760), `chat_recall_overlap_threshold` (0–1), `llm_temperature` (0–2), `openai_model` (must be in `ai_model_allow_list`). NEVER settable (enforced by `extra="forbid"`): keys, Milvus/embedding fields, chunking, all `chat_index_*`/`chat_segment_*` knobs (indexer is process-global), `llm_streaming`, langchain fields.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_ai_settings.py
"""ai_settings: whitelist validation, layered resolution, provenance."""
import uuid

import pytest
from pydantic import ValidationError

from config import RagConfig
from rag.ai_settings import AiConfigPatch, AiSettings, resolve_ai_config


def test_patch_rejects_non_whitelisted_field():
    with pytest.raises(ValidationError):
        AiConfigPatch(openai_api_key="steal-me")
    with pytest.raises(ValidationError):
        AiConfigPatch(chat_index_interval_minutes=1)


def test_patch_bounds():
    with pytest.raises(ValidationError):
        AiConfigPatch(retrieval_top_k=0)
    with pytest.raises(ValidationError):
        AiConfigPatch(llm_temperature=3.0)
    assert AiConfigPatch(retrieval_top_k=7).retrieval_top_k == 7


def test_patch_model_allow_list():
    with pytest.raises(ValidationError):
        AiConfigPatch(openai_model="arbitrary-model-9000")
    assert AiConfigPatch(openai_model="gpt-4o").openai_model == "gpt-4o"


def test_resolution_layers_and_provenance(db_session, test_channel):
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"use_hyde": False, "retrieval_top_k": 9}))
    db_session.add(AiSettings(workspace_id=ws, channel_id=test_channel.id,
                              overrides={"retrieval_top_k": 3}))
    db_session.commit()

    cfg, prov = resolve_ai_config(ws, test_channel.id, db_session)
    assert cfg.use_hyde is False                    # workspace layer
    assert cfg.retrieval_top_k == 3                 # channel wins
    assert prov["use_hyde"] == "workspace"
    assert prov["retrieval_top_k"] == "channel"
    assert prov["use_reranking"] == "global"

    cfg2, prov2 = resolve_ai_config(ws, None, db_session)
    assert cfg2.retrieval_top_k == 9                # workspace default only
    assert isinstance(cfg2, RagConfig)

    # cleanup
    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_resolution_no_rows_returns_global(db_session, test_channel):
    cfg, prov = resolve_ai_config(uuid.uuid4(), None, db_session)
    from config import global_rag_config
    assert cfg.retrieval_top_k == global_rag_config.retrieval_top_k
    assert set(prov.values()) == {"global"}
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_ai_settings.py -q` → FAIL (module not found).

- [ ] **Step 3: Implement**

`src/config/config.py` — add near the model fields:
```python
    # Models a workspace admin may select via ai_settings (vetted allow-list;
    # never free text). Extend deliberately.
    ai_model_allow_list: list[str] = ["gpt-4o-mini", "gpt-4o", "qwen2.5:7b-instruct"]
```

`src/rag/ai_settings.py`:
```python
"""Per-workspace (and per-channel) AI configuration.

One rag-owned table of whitelisted overrides layered over global_rag_config:
global -> workspace default (channel_id IS NULL) -> channel override.
Resolution returns a real RagConfig (model_copy), so the existing config=
seam and RagTrace.effective_config stay honest by construction.
"""

import uuid
from datetime import datetime

import sqlalchemy as sql
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import ForeignKey, Index, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from config import RagConfig, global_rag_config
from database import Base

__all__ = ["AiSettings", "AiConfigPatch", "OVERRIDABLE", "resolve_ai_config"]

OVERRIDABLE: tuple[str, ...] = (
    "use_hyde", "use_query_rewrite", "use_reranking",
    "retrieval_top_k", "rerank_fetch_k",
    "chat_recall_k", "chat_recall_fetch_k",
    "chat_decay_half_life_hours", "chat_recall_overlap_threshold",
    "llm_temperature", "openai_model",
)


class AiSettings(Base):
    __tablename__ = "ai_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", name="uq_ai_settings_scope"),
        # Postgres treats NULLs as distinct, so the composite constraint can't
        # guard the workspace-default row — a partial unique index does.
        Index("uq_ai_settings_ws_default", "workspace_id",
              unique=True, postgresql_where=sql.text("channel_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"))
    overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        sql.DateTime(timezone=True), default=sql.func.now(), onupdate=sql.func.now())


class AiConfigPatch(BaseModel):
    """Whitelisted, bounded overrides. extra='forbid' IS the blacklist."""
    model_config = ConfigDict(extra="forbid")

    use_hyde: bool | None = None
    use_query_rewrite: bool | None = None
    use_reranking: bool | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1, le=50)
    rerank_fetch_k: int | None = Field(default=None, ge=1, le=100)
    chat_recall_k: int | None = Field(default=None, ge=0, le=10)
    chat_recall_fetch_k: int | None = Field(default=None, ge=1, le=50)
    chat_decay_half_life_hours: float | None = Field(default=None, ge=1, le=8760)
    chat_recall_overlap_threshold: float | None = Field(default=None, ge=0, le=1)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    openai_model: str | None = None

    @field_validator("openai_model")
    @classmethod
    def _model_vetted(cls, v):
        if v is not None and v not in global_rag_config.ai_model_allow_list:
            raise ValueError(f"model not in allow-list: {v}")
        return v


def _clean(overrides: dict) -> dict:
    """Keep only whitelisted keys with non-null values (defense in depth —
    rows are validated on write, but old rows must never widen the surface)."""
    return {k: v for k, v in (overrides or {}).items()
            if k in OVERRIDABLE and v is not None}


def resolve_ai_config(
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    db: Session,
) -> tuple[RagConfig, dict]:
    """global -> workspace -> channel. Returns (effective config, provenance)."""
    rows = db.execute(
        select(AiSettings.channel_id, AiSettings.overrides)
        .where(AiSettings.workspace_id == workspace_id)
        .where(sql.or_(AiSettings.channel_id.is_(None),
                       AiSettings.channel_id == channel_id))
    ).all()
    ws_over: dict = {}
    ch_over: dict = {}
    for ch_id, overrides in rows:
        if ch_id is None:
            ws_over = _clean(overrides)
        elif channel_id is not None and ch_id == channel_id:
            ch_over = _clean(overrides)

    provenance = {k: "global" for k in OVERRIDABLE}
    provenance.update({k: "workspace" for k in ws_over})
    provenance.update({k: "channel" for k in ch_over})

    merged = {**ws_over, **ch_over}
    cfg = global_rag_config.model_copy(update=merged) if merged else global_rag_config
    return cfg, provenance
```

`src/rag/__init__.py` — add (so `Base.metadata.create_all` sees the table):
```python
from . import ai_settings  # noqa: F401  (registers the ai_settings table)
```
(place it after the existing star imports; verify app boot: `IS_TEST=1 uv run python -c "import app"` — adjust import position if a circular import appears; `rag/ai_settings.py` imports only config + database, so it should be safe.)

- [ ] **Step 4: Run tests, then suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_ai_settings.py -q` → 5 passed
Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rag/ai_settings.py src/rag/__init__.py src/config/config.py tests/rag/test_ai_settings.py
git commit -m "feat(rag): ai_settings storage + whitelisted layered config resolution"
```

---

### Task 5: AI-config API endpoints (workspace + channel)

**Files:**
- Create: `src/rag/settings_router.py`
- Modify: `src/workspace/router.py` (two include lines + one import — the plan's single sanctioned teammate-file touch)
- Test: `tests/rag/test_ai_settings_api.py`

**Interfaces:**
- Consumes: `AiSettings`, `AiConfigPatch`, `resolve_ai_config`, `OVERRIDABLE` (Task 4).
- Produces:
  - `GET  /api/workspaces/{workspace_id}/ai/config` (guard `workspace:view`) → `{"effective": {...whitelist fields...}, "overrides": {...}, "provenance": {...}}`
  - `PATCH /api/workspaces/{workspace_id}/ai/config` (guard `workspace.role:manage`) — body `AiConfigPatch`; keys set to `null` CLEAR that override; returns the same shape as GET.
  - `GET/PATCH /api/channels/{channel_id}/ai/config` (guards `channel:view` / `workspace.role:manage`) — channel-scope row; workspace resolved from the channel like `/ask` does.
  - Routers exported as `workspace_ai` and `channel_ai`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_ai_settings_api.py
"""AI-config endpoints: GET shape, PATCH upsert/clear, validation."""


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_get_returns_global_defaults_initially(client, test_channel, auth_token, path):
    r = client.get(f"/api/workspaces/{test_channel.workspace_id}/ai/config", headers=_h(auth_token))
    assert r.status_code == 200
    body = r.json()
    assert body["overrides"] == {}
    assert body["effective"]["use_reranking"] is True
    assert body["provenance"]["use_reranking"] == "global"


def test_patch_upserts_and_get_reflects(client, test_channel, auth_token):
    ws = test_channel.workspace_id
    r = client.patch(f"/api/workspaces/{ws}/ai/config",
                     json={"use_hyde": False, "retrieval_top_k": 9}, headers=_h(auth_token))
    assert r.status_code == 200
    assert r.json()["effective"]["retrieval_top_k"] == 9
    assert r.json()["provenance"]["retrieval_top_k"] == "workspace"

    # channel override wins over workspace
    r2 = client.patch(f"/api/channels/{test_channel.id}/ai/config",
                      json={"retrieval_top_k": 3}, headers=_h(auth_token))
    assert r2.status_code == 200
    assert r2.json()["effective"]["retrieval_top_k"] == 3
    assert r2.json()["provenance"]["retrieval_top_k"] == "channel"

    # null clears the channel override
    r3 = client.patch(f"/api/channels/{test_channel.id}/ai/config",
                      json={"retrieval_top_k": None}, headers=_h(auth_token))
    assert r3.json()["effective"]["retrieval_top_k"] == 9


def test_patch_rejects_blacklisted_and_out_of_bounds(client, test_channel, auth_token):
    ws = test_channel.workspace_id
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"openai_api_key": "x"}, headers=_h(auth_token)).status_code == 422
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"retrieval_top_k": 999}, headers=_h(auth_token)).status_code == 422
    assert client.patch(f"/api/workspaces/{ws}/ai/config",
                        json={"openai_model": "not-vetted"}, headers=_h(auth_token)).status_code == 422
```
(implementer: tests share DB state — add a cleanup fixture that deletes `AiSettings` rows for the test workspace after each test, mirroring the cleanup style in `test_ai_settings.py`.)

- [ ] **Step 2: Run to verify failure** → 404s (routes don't exist).

- [ ] **Step 3: Implement `src/rag/settings_router.py`**

```python
"""Workspace/channel AI-config endpoints (rag-owned).

GET returns the resolved effective config + raw overrides + provenance.
PATCH validates against the AiConfigPatch whitelist; null clears a key.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from database import AsyncSessionLocal
from rag.ai_settings import AiConfigPatch, AiSettings, OVERRIDABLE, resolve_ai_config
from workspace import require_perms as require
from workspace.model import Channel

workspace_ai = APIRouter(tags=["rag"])
channel_ai = APIRouter(tags=["rag"])


def _view(workspace_id: UUID, channel_id: UUID | None):
    """Resolved view for a scope — runs sync DB reads via a short session."""
    from database import SessionLocal
    with SessionLocal() as db:
        cfg, prov = resolve_ai_config(workspace_id, channel_id, db)
        row = db.scalar(
            select(AiSettings)
            .where(AiSettings.workspace_id == workspace_id)
            .where(AiSettings.channel_id.is_(None) if channel_id is None
                   else AiSettings.channel_id == channel_id))
        overrides = dict(row.overrides) if row else {}
    return {
        "effective": {k: getattr(cfg, k) for k in OVERRIDABLE},
        "overrides": overrides,
        "provenance": prov,
    }


def _apply_patch(workspace_id: UUID, channel_id: UUID | None, patch: AiConfigPatch):
    from database import SessionLocal
    delta = patch.model_dump(exclude_unset=True)  # null values present = clear
    with SessionLocal() as db:
        row = db.scalar(
            select(AiSettings)
            .where(AiSettings.workspace_id == workspace_id)
            .where(AiSettings.channel_id.is_(None) if channel_id is None
                   else AiSettings.channel_id == channel_id))
        if row is None:
            row = AiSettings(workspace_id=workspace_id, channel_id=channel_id, overrides={})
            db.add(row)
        merged = dict(row.overrides or {})
        for k, v in delta.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        row.overrides = merged
        db.commit()


@workspace_ai.get("/ai/config", dependencies=[require("workspace:view")])
async def get_workspace_ai_config(workspace_id: UUID):
    return _view(workspace_id, None)


@workspace_ai.patch("/ai/config", dependencies=[require("workspace.role:manage")])
async def patch_workspace_ai_config(workspace_id: UUID, patch: AiConfigPatch):
    _apply_patch(workspace_id, None, patch)
    return _view(workspace_id, None)


async def _channel_workspace(channel_id: UUID) -> UUID:
    async with AsyncSessionLocal() as db:
        ws = await db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if ws is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return ws


@channel_ai.get("/ai/config", dependencies=[require("channel:view")])
async def get_channel_ai_config(channel_id: UUID):
    ws = await _channel_workspace(channel_id)
    return _view(ws, channel_id)


@channel_ai.patch("/ai/config", dependencies=[require("workspace.role:manage")])
async def patch_channel_ai_config(channel_id: UUID, patch: AiConfigPatch):
    ws = await _channel_workspace(channel_id)
    _apply_patch(ws, channel_id, patch)
    return _view(ws, channel_id)
```
NOTE: `require` here mirrors `rag/router.py`'s existing import (`from workspace import require_perms as require`) — verify the exact name there and match it. The sync `_view`/`_apply_patch` run one indexed point-read/write; acceptable directly in the handler (they are millisecond-scale; if the reviewer objects, wrap in `asyncio.to_thread`).

`src/workspace/router.py` — after the existing `channel.include_router(channel_rag_router)` line add:
```python
from rag.settings_router import workspace_ai as workspace_ai_router, channel_ai as channel_ai_router
workspace.include_router(workspace_ai_router)
channel.include_router(channel_ai_router)
```
(put the import at the top with the existing `from rag.router import ...` import; two include lines next to the existing mounts — this is the sanctioned teammate-file touch and MUST be listed in the Task 7 handoff update.)

- [ ] **Step 4: Run tests + suite** → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rag/settings_router.py src/workspace/router.py tests/rag/test_ai_settings_api.py
git commit -m "feat(rag): workspace/channel AI-config endpoints (whitelisted PATCH, resolved GET)"
```

---

### Task 6: Wire resolution into /ask + provenance in the trace

**Files:**
- Modify: `src/rag/router.py` (`_build_and_prepare` resolves config)
- Modify: `src/rag/rag_chain.py` (`_fill_trace` gains provenance + full whitelist effective_config)
- Modify: `src/rag/trace.py` (one field)
- Test: `tests/rag/test_ask_endpoint.py` (extend)

**Interfaces:**
- Consumes: `resolve_ai_config` (Task 4), `RAGChain(config=...)` seam, `OVERRIDABLE`.
- Produces: every `/ask` uses the workspace/channel-resolved config. `RagTrace` gains `config_provenance: dict`; `effective_config` now includes EVERY `OVERRIDABLE` field (fixing the curated-subset gap). `RAGChain.__init__` gains keyword `config_provenance: dict | None = None`.

- [ ] **Step 1: Write the failing test** (append to `tests/rag/test_ask_endpoint.py`)

```python
def test_ask_uses_workspace_ai_overrides(client, test_channel, auth_token, path, fake_chain):
    r = client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                     json={"use_reranking": False, "retrieval_top_k": 2},
                     headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200

    _ask(client, path, test_channel, auth_token, include_citations=False)
    cfg = fake_chain.last.kwargs.get("config")
    assert cfg is not None
    assert cfg.use_reranking is False
    assert cfg.retrieval_top_k == 2
    prov = fake_chain.last.kwargs.get("config_provenance")
    assert prov["use_reranking"] == "workspace"
    # cleanup
    client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                 json={"use_reranking": None, "retrieval_top_k": None},
                 headers={"Authorization": f"Bearer {auth_token}"})
```

- [ ] **Step 2: Run to verify failure** → FAIL (`config` not passed).

- [ ] **Step 3: Implement**

`src/rag/router.py` — inside `_build_and_prepare()` (it already runs in a worker thread), before constructing the chain:
```python
        from database import SessionLocal
        from rag.ai_settings import resolve_ai_config
        with SessionLocal() as db:
            resolved, provenance = resolve_ai_config(workspace_id, channel_id, db)
        chain = RAGChain(
            collection_name=WORKSPACE_COLLECTION,
            config=resolved,
            config_provenance=provenance,
            workspace_id=str(workspace_id),
            file_ids=file_ids,
            chatroom_id=str(channel_id),
            chat_history=history,
            exclude_message_ids=tail_ids,
            request_id=request_id,
        )
```

`src/rag/rag_chain.py`:
- `__init__` gains `config_provenance: dict | None = None`; store `self.config_provenance = dict(config_provenance or {})`.
- `_fill_trace`: replace the hand-picked `effective_config` dict with the full whitelist plus the two non-overridable-but-informative extras it already had:
```python
        from rag.ai_settings import OVERRIDABLE
        effective = {k: getattr(self.config, k) for k in OVERRIDABLE}
        effective["use_hybrid_retrieval"] = self.config.use_hybrid_retrieval
        effective["compression_type"] = self.config.compression_type.value
```
  and pass `effective_config=effective, config_provenance=dict(self.config_provenance)` into `RagTrace(...)`.
- `compression_type.value` note: enum → keep JSON-safe string as today.

`src/rag/trace.py` — add `config_provenance: dict = field(default_factory=dict)`.

- [ ] **Step 4: Run the suite** → all pass (existing `_FakeChain` in the endpoint tests accepts `**kwargs`, so the two new kwargs flow through untouched — verify `_FakeChain.__init__` stores `self.kwargs = kwargs`; it does).

- [ ] **Step 5: Commit**

```bash
git add src/rag/router.py src/rag/rag_chain.py src/rag/trace.py tests/rag/test_ask_endpoint.py
git commit -m "feat(rag): /ask runs on workspace/channel-resolved config; trace records provenance"
```

---

### Task 7: Docs, manual v2.1, handoff & coordination reports

**Files:**
- Modify: `docs/rag-manual/rag_owners_manual.typ` (+ recompile PDF)
- Modify: `docs/chat-memory-handoff.md`

**Interfaces:** none (documentation). Facts to write are listed below — copy them accurately.

- [ ] **Step 1: Update the owner's manual**

In `docs/rag-manual/rag_owners_manual.typ`:
- §2 (Configuration): add a short "Layering" paragraph + rows: config now resolves `global (env) → workspace override → channel override` via the `ai_settings` table; overrides are whitelist-only (list the OVERRIDABLE fields); indexer/ingestion/infra knobs are global-only by design. Mention `ai_model_allow_list`.
- §9 (Evaluation): add the sentence: "Eval measures the *global default* configuration; a workspace with overrides diverges from the headline number — the per-answer truth is the trace's `config_provenance`."
- §10 (Debugging): add trace fields to the intro list (`request_id`, `retrieval_ms`/`generation_ms`, `chat_selection`, `config_provenance`); add symptom rows: [Answer differs between workspaces → check `config_provenance` for overridden fields] and [Chat memory ignored something it fetched → `chat_selection` shows fetched/dropped_tail/dropped_redundant/kept]; note that the chat-ui 🔍 toggle is a dev scaffold — `debug:true` and `scripts/debug_ask.py` are the durable surfaces; note every ask now logs an `ask.trace` digest line (grep by `request_id`).
- Recompile: `cd docs/rag-manual && typst compile rag_owners_manual.typ RAG_Owners_Manual.pdf` and visually verify the changed pages render (Read the PDF pages).

- [ ] **Step 2: Update the handoff doc**

In `docs/chat-memory-handoff.md`:
- Teammate-touched files list: add the Task 5 lines in `src/workspace/router.py` (one import + two `include_router`).
- New section "Integration findings to owners" with these reports (verbatim content):
  - **Filesystem owner:** upload→RAG was never wired: no `process_file` enqueue on any branch; `FileStatus` lacks an in-flight `PROCESSING` member (the claim-update needs it — until then double-processing is possible, output stays idempotent via the pre-ingest purge); `File` lacks `chunk_count`/`processing_error` columns so those writes are silently dropped. Working reference exists in the local integration worktree.
  - **Chat owner:** `/ask` persists assistant rows with `sender_id NULL`; `MessageSchema.sender_id` non-optional makes `GET /messages` return `[]` for any channel containing one (via `handle_exceptions(default_return=[])`). Also `chat/router.py:39` `sio.send` is unawaited (broadcast never fires). At rich-msg merge: `_persist_exchange` (`src/rag/router.py`) must switch to `wrap_plain_text(...)`/`set_content()` — plain-str content will violate `content_size_bytes NOT NULL`.
  - **Frontend owner:** working `@ai` reference exists (ChatPage/askAi/onAiMessage demo patches); two must-fixes before shipping: handle the `\n\n[ask:error]` stream marker (bubble currently sticks on pending), and the orphaned-pending-bubble race; the AI-config client should target the nested endpoints `GET/PATCH /api/workspaces/{id}/ai/config` and `/api/channels/{id}/ai/config` (replacing the flat `/api/ai/config` scaffold).
  - **Search owner (nourhane):** `filesystem/service.py:375` imports `get_retriever` which no longer exists (silently returns empty results via the broad except) — use `build_rag_pipeline`; and the Milvus expr needs `&& source == "file"` or chat vectors leak into file search.
  - **MCP owner (MohabG2):** rebase onto origin/main (branch reverts the model→database rename); `RAGChain(collection_name=, workspace_id=, file_ids=)` + `.query()` is unchanged and compatible.
- Suggested merge order: mcp-server rebase → chat-message-memory → rich-msg → search → frontend.

- [ ] **Step 3: Run the full suite one last time**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q` → all pass.

- [ ] **Step 4: Commit**

```bash
git add docs/rag-manual/rag_owners_manual.typ docs/rag-manual/RAG_Owners_Manual.pdf docs/chat-memory-handoff.md
git commit -m "docs(rag): manual v2.1 — config layering, provenance, trace fields; teammate integration reports"
```

---

## Out of scope (deliberately)

- Trace persistence table / trace viewer UI, OpenTelemetry, per-chunk ingestion lineage — YAGNI (audit verdict).
- Per-workspace indexer/segmentation knobs — the indexer is process-global; exposing them would be an illusion.
- `use_hybrid_retrieval` / `compression_*` in the whitelist — hybrid is inert in prod; keep global until eval says otherwise.
- Caching resolved configs — one indexed SELECT per ask is negligible; invalidation would be over-engineering.
- Fixing teammate-owned defects (enqueue hook, FileStatus.PROCESSING, File columns, sender_id schema, frontend @ai) — reported via Task 7, not implemented.
- Per-workspace eval runs — documented caveat only.
