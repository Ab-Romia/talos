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
  Later (Task 5, AI-config endpoints): one import —
  `from rag.settings_router import workspace_ai as workspace_ai_router, channel_ai as channel_ai_router`
  — and two more includes, `workspace.include_router(workspace_ai_router)` and
  `channel.include_router(channel_ai_router)`, mounting
  `GET`/`PATCH /api/workspaces/{id}/ai/config` and `/api/channels/{id}/ai/config`.
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

## Socket.IO event for the frontend team
`/ask` broadcasts the finished exchange to everyone in the channel room (not just the asker,
since the HTTP response only streams to the requester). Event: `ai_message` on room
`channel:{channel_id}`, payload:
```json
{
  "channel_id": "...",
  "question_message_id": "...",
  "message_id": "...",
  "question": "...",
  "content": "...",
  "role": "assistant"
}
```
Emitted from `_broadcast_ai_message` in `src/rag/router.py` after `_persist_exchange` commits
(best-effort — a broadcast failure never fails the request). This is a custom event, NOT the
chat `message` event, because `MessageSchema` requires a non-null `sender_id` and assistant
rows have `sender_id = NULL`.

## Ops invariants (indexer / scheduler)
- **Exactly ONE `taskiq scheduler` process** may run against a given broker — taskiq has no
  built-in de-duplication, so a second scheduler instance double-fires every cron tick
  (double-ingests, double the Milvus writes). Deploy topology must guarantee singleton.
- The indexer (`processing.chat_tasks` → `chat_indexing.index_pending_messages`) takes a
  **Postgres session-level advisory lock** (`pg_try_advisory_lock`, key `0x7A105C47`) on a
  dedicated connection before draining, so concurrent ticks (or a slow tick overlapping the
  next cron fire) skip rather than race.
- **Retry:** `retry_on_error=True, max_retries=3` gives transient Milvus/embedding failures 3
  *immediate* retries within the same tick — `RedisStreamBroker` ignores taskiq's retry-delay
  labels, so there is no backoff; a 4th failure waits for the next cron tick.
- **Batching:** each tick drains up to `chat_index_max_batches` (10) × `chat_index_batch_size`
  (500) messages, i.e. up to 5,000 messages per tick before yielding to the next scheduled run.

## Segments (this plan's model)
Chat memory is indexed as **conversation segments**, not per-message vectors: consecutive
messages in a channel are grouped by an inactivity gap (`chat_segment_gap_minutes` = 30) and
capped at `chat_segment_max_messages` (12) per segment. Each segment vector carries a
`message_ids` list in its metadata; purge on message edit/delete goes through
`delete_chat_segments_for_messages` (Milvus filter `json_contains_any(message_ids, ...)`).
Chat recall re-ranks before returning: fetch `chat_recall_fetch_k` (10) candidates, apply a
recency decay with `chat_decay_half_life_hours` = 168h (one week) floored at 0.25, drop
near-duplicates above `chat_recall_overlap_threshold` (0.6 lexical overlap), then narrow to the
top `chat_recall_k` (3).
Segments never span indexer batches (`batch_size` = 500 >> the 12-message segment cap), so a
conversation straddling a batch cut becomes two segments — a rare retrieval-quality nit, not a
correctness issue.

### Migrating existing per-message vectors to segments
Legacy per-message chat vectors (from an earlier version of this feature) still work for
recall/dedupe — migration is **optional but recommended** for consistency with the segment
model. To migrate on a dev DB:
1. Purge existing chat vectors: delete where `source == "chat"`.
2. `UPDATE messages SET indexed_at = NULL;`
3. Let the indexer re-embed everything as segments on its next tick(s).

## Caveats / follow-ups
- **No Alembic** (`create_all` only): `indexed_at` appears on fresh DBs but won't ALTER an
  existing `messages` table — recreate the dev/test DB or add the column manually.
- **Milvus not exercised locally** (no Milvus in this env): ingest/retrieve paths mirror the
  existing file pipeline and pin `WORKSPACE_COLLECTION`; add a live Milvus round-trip test.
- **`origin/search` coordination:** when it lands, patch `filesystem.service.search_files`'s
  Milvus expr to include `source == "file"`, or chat vectors will leak into file-search.
- **`origin/rich-msg` coordination — mostly done:** `Message.content: str -> JSONB` (ProseMirror)
  now funnels through the single seam `src/rag/message_text.py` (`message_text()`) for BOTH read
  sites — `build_chat_documents` (`src/processing/chat_indexing.py`) and `_load_unindexed_tail`
  (`src/rag/router.py`) — so those two call sites already handle either shape. The remaining
  touchpoint is **`_persist_exchange` in `src/rag/router.py`**, which still WRITES
  `content=<str>` directly to `Message.content`; when the rich-msg branch lands, switch that
  write to rich-msg's `set_content()` helper instead of assigning a raw string.
- **Frontend wiring:** `/ask` is a standalone streaming endpoint. The frontend currently drives
  RAG via `POST .../messages`; wiring it to `/ask` (or folding `/ask` into message-send) is a
  separate task. Note `/ask` persists the user turn itself — reconcile to avoid double-persist
  if the frontend also posts the message. See the `ai_message` Socket.IO event above for how the
  rest of the room learns about the answer.
- **Owner's manual is stale:** `docs/rag-manual/RAG_Owners_Manual.pdf` predates this plan
  (prepare/stream split, segments, re-ranking, the `ai_message` event) and needs regeneration
  via `docs/rag-manual/gen_diagrams.py` + the `.typ` source. Follow-up, not part of this plan.
- **Pre-existing chat-module bugs (report to chat owner, do not fix here):**
  - `MessageSchema.sender_id` is declared **non-optional**, but assistant rows in this feature
    have `sender_id = NULL` (by design — there's no "AI user"). Combined with
    `chat/storage.py`'s `handle_exceptions(default_return=[])`, `GET /messages` **silently
    returns `[]`** for *any* channel that contains an assistant row, because schema validation
    raises and the decorator swallows it. The `/ask` tests work around this by asserting
    persistence via direct DB reads instead of the list endpoint.
  - `chat/router.py:39` has an unawaited `sio.send(...)` — the coroutine is created but never
    awaited, so the ordinary chat "message" broadcast never actually fires. Unrelated to this
    feature but discovered while investigating why room broadcasts weren't showing up; needs
    the chat owner's attention.

## Integration findings to owners

- **Filesystem owner:** upload→RAG was never wired: no `process_file` enqueue on any branch;
  `FileStatus` lacks an in-flight `PROCESSING` member (the claim-update needs it — until then
  double-processing is possible, output stays idempotent via the pre-ingest purge); `File`
  lacks `chunk_count`/`processing_error` columns so those writes are silently dropped. Working
  reference exists in the local integration worktree.
- **Chat owner:** `/ask` persists assistant rows with `sender_id NULL`; `MessageSchema.sender_id`
  non-optional makes `GET /messages` return `[]` for any channel containing one (via
  `handle_exceptions(default_return=[])`). Also `chat/router.py:39` `sio.send` is unawaited
  (broadcast never fires). At rich-msg merge: `_persist_exchange` (`src/rag/router.py`) must
  switch to `wrap_plain_text(...)`/`set_content()` — plain-str content will violate
  `content_size_bytes NOT NULL`.
- **Frontend owner:** working `@ai` reference exists (ChatPage/askAi/onAiMessage demo patches);
  two must-fixes before shipping: handle the `\n\n[ask:error]` stream marker (bubble currently
  sticks on pending), and the orphaned-pending-bubble race; the AI-config client should target
  the nested endpoints `GET/PATCH /api/workspaces/{id}/ai/config` and
  `/api/channels/{id}/ai/config` (replacing the flat `/api/ai/config` scaffold).
- **Search owner (nourhane):** `filesystem/service.py:375` imports `get_retriever` which no
  longer exists (silently returns empty results via the broad except) — use `build_rag_pipeline`;
  and the Milvus expr needs `&& source == "file"` or chat vectors leak into file search.
- **MCP owner (MohabG2):** rebase onto origin/main (branch reverts the model→database rename);
  `RAGChain(collection_name=, workspace_id=, file_ids=)` + `.query()` is unchanged and compatible.

Suggested merge order: mcp-server rebase → chat-message-memory → rich-msg → search → frontend.
