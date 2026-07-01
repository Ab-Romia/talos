# Chat-Memory Indexing — implementation + hand-off notes

Branch: `feature/chat-message-memory` (off latest `origin/main`). Feature: periodically
embed older chat messages into Milvus (per-channel recall) and inject the not-yet-indexed
tail directly as context, so the RAG assistant "remembers" a channel's conversation.

## Design (the `indexed_at` partition)
Every message is in exactly one tier, split on `Message.indexed_at`:
- **Tier 1 — direct injection:** the channel's un-indexed tail (`indexed_at IS NULL`, capped
  at `chat_context_cap`) is loaded by `/ask` and passed as `chat_history`.
- **Tier 2 — retrieval:** the indexed body (`source="chat"`, scoped by `chatroom_id`) is
  recalled by `RAGChain`'s per-channel chat retriever, merged into context (not citations).
The cron stamps `indexed_at` only after a successful Milvus insert, so nothing is lost and
nothing is double-counted. A full tail (== cap) logs a lag warning.

## Files — OUR lane (rag / processing)
- `src/rag/router.py` (NEW) — streaming `POST /api/channels/{channel_id}/ask`
  (`channel.message:send`). Resolves workspace from the channel, loads the un-indexed tail,
  persists user + assistant turns, streams `RAGChain.stream_query`.
- `src/rag/rag_chain.py` — added `chatroom_id`/`chat_history` params, `source=="file"` file
  filter, per-channel chat retriever merged into context (files-only citations).
- `src/rag/ingestion.py` — file chunks tagged `source="file"`; new `ingest_chat_messages`.
- `src/rag/vector_store.py` — new `delete_message_chunks` (mirrors `delete_file_chunks`).
- `src/processing/chat_indexing.py` (NEW) — `build_chat_documents` + `index_pending_messages`
  (purge→ingest→stamp, lose-safe & idempotent), pinned to `WORKSPACE_COLLECTION`.
- `src/processing/chat_tasks.py` (NEW) — taskiq cron task (`*/N` from config).
- `src/scheduler.py` (NEW) — `TaskiqScheduler` + `LabelScheduleSource`.
- `src/config/config.py` — `RagConfig` knobs: `chat_index_interval_minutes`,
  `chat_index_grace_seconds`, `chat_index_batch_size`, `chat_recall_k`, `chat_context_cap`.
- `tests/chat/test_chat_indexing.py` (NEW) — 4 tests, all pass.

## Files touched OUTSIDE our lane — please review/approve (owners)
- **`src/chat/model.py`** (chat) — added `indexed_at: Mapped[datetime | None]` to `Message`.
  Nullable, `default=None`; `MessageSchema` unchanged, so `storage.put` is unaffected.
- **`src/workspace/router.py`** (routing) — one include: `channel.include_router(channel_rag_router)`
  so `/ask` mounts under the channel (inherits `workspace:view` + `channel:view`).
- **`docker-compose.yaml`** (infra) — added `processing.chat_tasks` to the worker command and a
  new `scheduler` service (`taskiq scheduler scheduler:scheduler processing.chat_tasks`).

## Verification
`IS_TEST=1 uv run python -m pytest tests -q` → 155 passed, 4 failed. The 4 failures are the
pre-existing notifications/VAPID tests (need `push`/VAPID env not set locally) — unrelated to
this feature. `tests/chat` (incl. the 4 new indexer tests): all pass.

## Local-model testing (no OpenAI / no quota)
Both the embedding model and the LLM can run locally with **no code changes** — env only:
```
EMBEDDING_PROVIDER=huggingface          # sentence-transformers/all-MiniLM-L6-v2 (local)
OPENAI_BASE_URL=http://localhost:11434/v1   # Ollama OpenAI-compatible endpoint
OPENAI_API_KEY=ollama                        # dummy; Ollama ignores it
OPENAI_MODEL=qwen2.5:7b-instruct             # any local Ollama model
```
`ChatOpenAI` honours `OPENAI_BASE_URL`, so `get_llm()` transparently drives Ollama. Verified:
the real `RAG_PROMPT | get_llm()` chain streamed a correct answer grounded in recalled chat
memory using `qwen2.5:7b-instruct`.

## Caveats / follow-ups
- **No Alembic** (`create_all` only): `indexed_at` appears on fresh DBs but won't ALTER an
  existing `messages` table — recreate the dev/test DB or add the column manually.
- **Milvus not exercised locally** (no Milvus in this env): ingest/retrieve paths mirror the
  existing file pipeline and pin `WORKSPACE_COLLECTION`; add a live Milvus round-trip test.
- **`origin/search` coordination:** when it lands, patch `filesystem.service.search_files`'s
  Milvus expr to include `source == "file"`, or chat vectors will leak into file-search.
- **`origin/rich-msg` coordination:** when `Message.content` becomes ProseMirror JSONB,
  `build_chat_documents` must flatten it to text before embedding (currently reads `m.content`
  as a plain string).
- **Frontend wiring:** `/ask` is a standalone streaming endpoint. The frontend currently drives
  RAG via `POST .../messages`; wiring it to `/ask` (or folding `/ask` into message-send) is a
  separate task. Note `/ask` persists the user turn itself — reconcile to avoid double-persist
  if the frontend also posts the message.
