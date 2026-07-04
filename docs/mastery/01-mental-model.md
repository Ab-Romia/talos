# 01 · The Mental Model

Hold the system as **four layers and three chokepoints**. Everything else in
this guide hangs off this picture. (If any term here is unfamiliar —
embeddings, reranking, chunking — read `00-foundations.md` first; every concept
the guide uses is explained there, and later chapters cross-reference it as
`→ 00 §n`.)

## The four layers

```
┌──────────────────────────────────────────────────────────────────┐
│ 4 · SURFACES     POST /ask (stream)   ai_message (socket room)   │
│                  GET/PATCH .../ai/config      {"debug":true}     │
├──────────────────────────────────────────────────────────────────┤
│ 3 · ORCHESTRATION   RAGChain.prepare() → stream_answer()         │
│                     (built per request, off the event loop)      │
├──────────────────────────────────────────────────────────────────┤
│ 2 · RETRIEVAL    build_rag_pipeline (files)   chat recall        │
│                  dense→[hybrid]→[rerank]→[compress]              │
│                  fetch→tail-dedupe→decay+redundancy select       │
├──────────────────────────────────────────────────────────────────┤
│ 1 · DATA         Milvus talos_documents (source=file|chat)       │
│                  Postgres messages (indexed_at) · ai_settings    │
│    WRITERS       chat indexer (cron, segments) · process_file    │
└──────────────────────────────────────────────────────────────────┘
```

Two flows write layer 1; one flow reads it; one config object steers all of it.

## The three chokepoints (memorize these)

1. **`RagConfig`** (`src/config/config.py`) — every knob. Read from env once
   into `global_rag_config`, then *layered* per request: global → workspace →
   channel via the `ai_settings` table. Whatever `resolve_ai_config` returns
   IS the config the chain runs on — no side channels.
2. **`build_rag_pipeline`** (`src/rag/retrieval/retrievers.py`) — the only
   place file-retrieval composition lives. Production and the eval harness
   both call it; edit once, both change.
3. **`RagTrace`** (`src/rag/trace.py`) — the only observability record. Filled
   once per run by the chain; read identically by the `/ask` debug flag,
   `scripts/debug_ask.py`, and the always-on `ask.trace` log digest.

Corollaries you should be able to recite: *eval measures what prod ships*
(same pipeline + prompt + config path); *the trace cannot lie about config*
(the resolved object is both the behavior driver and the trace source);
*chat memory can never kill an answer* (whole recall path degrades to
file-only inside one guard).

## The two-tier memory idea (the one non-obvious design)

A channel's conversation is split at the **indexer boundary**
(`messages.indexed_at`): recent un-indexed messages ride into the prompt
verbatim (tier 1 — doubly bounded: message cap AND char budget, newest first);
older conversation lives in Milvus as
**segments** (tier 2) and is recalled semantically, then re-ranked by
recency-decay and redundancy. A message is in exactly one tier —
`exclude_message_ids` drops any segment that overlaps the tail. Index lag is
therefore *masked, not fatal*.

## Ownership map

| Yours (edit freely, this guide covers every line) | Teammates' (never hand-edit; seams in ch. 07) |
|---|---|
| `src/rag/` (all) | `src/chat/` (kiro) |
| `src/processing/` (all) | `src/workspace/`, `src/permissions/` |
| `src/config/config.py`, `src/config/prompts.py` | `src/filesystem/` |
| `tests/rag*`, `tests/processing/`, `tests/chat/test_chat_indexing.py` | `src/auth/`, `src/notifications/` |
| `docs/` | `src/app.py`, `src/database.py`, `docker-compose.yaml`, `frontend/` (other branch) |

Sanctioned exceptions on your branch (documented in the handoff): the 4-line
Message.indexed_at column in `chat/model.py`, and the mount lines in
`workspace/router.py` (3 for `/ask` + ai-config routers).

## Repo orientation

- **`/home/romia/talos-main`** — your worktree, branch
  `feature/chat-message-memory`, the source of truth. `PYTHONPATH=src`;
  imports are rooted at `src/` (`from rag.router import ask`).
- **`/home/romia/talos-integration`** — throwaway local merge of your branch +
  `origin/frontend`; runs the demo app. Carries demo-only patches (marked
  `DEMO`) that must never be pushed.
- **`/home/romia/talos-frontend`** — teammates' React app checkout with the
  demo `@ai` patches (`ChatPage.jsx`, `services/chat.js`, `services/socket.js`).
- **`/home/romia/gp_artifact`** — the old repo; today it matters for
  `evaluation/` (v6/v7 eval evidence + reports) and the OpenRouter key in its
  `.env`.
- Top-level files in talos-main you should know: `app.py` (FastAPI assembly +
  lifespan `create_all` — this is what auto-creates `ai_settings`),
  `rag_cli.py` (legacy CLI ingest), `pyproject.toml`/`uv.lock` (deps; dev
  tools live in a dependency *group*, hence `uv sync --all-groups`),
  `docker-compose.yaml` (postgres, postgres-test, redis, milvus+minio, worker,
  scheduler), `config/config.yaml` (the OTHER config system — teammates'
  `Config`/`cfg()`, not your `RagConfig`).

**Two config systems** — do not confuse them: `cfg()` (`config/config_.py`,
YAML+env, teammates' app config: DB, auth, MinIO) vs `global_rag_config`
(`src/config/config.py`, env-only, yours). Chapter 03 covers yours; you only
ever *read* theirs (e.g. `cfg().minio`).

## The running stack (dev)

Five processes + three services: uvicorn app (:8000), taskiq **worker**
(executes tasks), taskiq **scheduler** (enqueues cron ticks — exactly ONE
instance ever), Milvus (:19530, with its bundled MinIO :9000), Redis (:6379),
Postgres (:5433 — `talos_dev`/`talos_frontend`/`talos_test` databases).
Chapter 08 has the exact launch commands. The demo app runs the integration
worktree; its exact live profile (model, embedder, toggles) is whatever the
env said at launch — never guess it, read it from any answer's trace
(`effective_config`) or the `ask.trace` log line.

## Self-test

1. *Name the three chokepoints and one sentence each.* — RagConfig (all knobs,
   layered global→workspace→channel), build_rag_pipeline (only place file
   retrieval lives; eval calls it too), RagTrace (single observability record,
   three readers).
2. *Why can't the trace lie about config?* — The router resolves config first
   and passes the resolved object into `RAGChain(config=...)`; `_fill_trace`
   reads the same `self.config`. One object drives behavior and reporting.
3. *A message was sent 30 seconds ago. Which tier answers about it?* — Tier 1:
   it's un-indexed (grace window is 300s in prod), so it's injected verbatim
   in the tail.
4. *Which config system owns MinIO credentials?* — Teammates' `cfg()`
   (config_.py); your `RagConfig` never touches storage credentials.
5. *What single invariant makes index lag harmless?* — Every message is in
   exactly one tier; un-indexed messages ride verbatim until the indexer
   stamps them.
