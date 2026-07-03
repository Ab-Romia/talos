# 08 · The Change Playbook — how to change anything yourself, and know it's right

This chapter is the operational half of the Owner's Manual. The manual tells you
*what the system is*; this tells you *how to move it without breaking it, and how
to prove you didn't*. Every recipe names the exact files, the test you write
**first**, the verification you run, and the blast radius. Nothing here is
aspirational — the file:line references are real and current on
`feature/chat-message-memory`.

The mental model to keep the whole time: the system funnels through **three
chokepoints** — `RagConfig` (all knobs, `src/config/config.py`),
`build_rag_pipeline` (all file retrieval, `src/rag/retrieval/retrievers.py:35`),
and `RagTrace` (all observability, `src/rag/trace.py:9`) — plus **one boundary**
(the indexer's `indexed_at` partition). If a change doesn't touch one of those
four things, it's probably in the wrong place.

---

## 0 · The universal verification loop

Four instruments, applied in order of how much of the change you're proving. Most
changes use the first two; retrieval-behavior changes need all four.

### 0.1 Run the tests (every change, no exceptions)

```bash
docker compose up -d postgres-test          # test DB on :5433 (talos_test)
IS_TEST=1 uv run python -m pytest tests/rag tests/chat tests/processing -q
```

- `IS_TEST=1` flips `config/config_.py:9` (`is_test()` checks `"IS_TEST" in
  os.environ`) so the app loads `config/config.test.yaml` → DB `talos_test` on
  `:5433`. Without it you point tests at the dev DB and the session-scoped
  `init` fixture (`tests/conftest.py:23-31`) runs `Base.metadata.drop_all` — it
  **has wiped live dev data before** (see the dev-env notes). Always `IS_TEST=1`.
- Use `uv run python -m pytest`, **never** bare `uv run pytest` — the latter can
  resolve a stale global `~/.local/bin/pytest` outside the venv.
- `PYTHONPATH=src` is auto-set for pytest via `pyproject.toml`; every import is
  `src`-relative (`from config import ...`, `from rag.rag_chain import ...`).
- The `tests/rag tests/chat tests/processing` triad is the standing gate. Scope
  down while iterating (`tests/rag/test_chunking.py -q`), but run the triad
  before you call it done.

### 0.2 Debug one answer (any change to what an answer contains)

When a real question produces a wrong/empty/weird answer, don't guess — read the
trace. Two durable surfaces, **one schema** (`RagTrace`, `src/rag/trace.py`):

- **Live over HTTP:** `POST …/ask` with `{"debug": true}`. The stream appends
  `\n\n__ASK_DEBUG__\n` + the full trace JSON (`src/rag/router.py:224-230`).
  Split on the marker client-side.
- **Offline / reproducible:** `PYTHONPATH=src uv run python scripts/debug_ask.py
  <channel_id> "<question>"`. It builds a real `RAGChain`, runs the real query
  path, and prints config-in-effect, tier-1 tail, tier-2 file+chat candidates,
  the **exact prompt**, and the answer (`scripts/debug_ask.py:47-75`). Because it
  reads the same `RagTrace` the endpoint serializes, the script and `/ask` can
  never drift.

The chat-UI 🔍 toggle exists but is a dev scaffold — not a supported surface.

### 0.3 Read the `ask.trace` log digest (production incident, after the fact)

Every *successful* `/ask` logs one `ask.trace` line — `request_id`, `model`,
`n_file`, `n_chat`, `retrieval_ms`, `generation_ms`, `answer_chars`
(`src/rag/router.py:213-223`) — regardless of the debug flag. Correlate a user
report to a run by grepping the app log for its `request_id`. Failures log
`ask retrieval failed` (502 path, `router.py:193`) or `ask generation failed`
(mid-stream, `router.py:204`).

### 0.4 Run the eval grid (any change to *retrieval behavior*)

If the change could move which chunks reach the prompt — chunking, embedder,
`fetch_k`/`top_k`, rerank, a new retrieval stage — unit tests prove it *runs*;
only the eval proves it's *better*. This is the "eval == ship" gate (§Invariants).

```bash
CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation \
  uv run python evaluation/live_pdf_eval/run_ablation.py --phase 1   # metrics-only, free
# --phase 2 runs judged end-to-end arms via OpenRouter (needs data/guide.pdf + key)
```

The harness chunks via production `build_chunk_documents`, retrieves via
production `build_rag_pipeline`, answers via production `RAG_PROMPT`; the only
substitution is `InMemoryVectorStore` for Milvus
(`evaluation/live_pdf_eval/run_ablation.py:1-20`). Results and the decision record
live in `evaluation/live_pdf_eval/REPORT.md`.

**When each instrument applies:**

| Change kind | 0.1 tests | 0.2 debug | 0.4 eval |
|---|---|---|---|
| Config bounds / whitelist | ✔ | — | — |
| Prompt wording | ✔ | ✔ | ✔ (judged arm) |
| Retrieval stage / chunking / embedder / k | ✔ | ✔ | ✔ **required** |
| Trace field / observability | ✔ | ✔ | — |
| /ask endpoint behavior | ✔ | ✔ | — |
| Chat-selection scoring | ✔ | ✔ | — (no eval coverage yet) |
| Indexer / segmentation | ✔ | ✔ (re-index first) | — |

---

## The recipes

Each recipe: **edit → test-first → verify → blast radius.**

### R1 · Add a `RagConfig` knob

**Edit:** add the field to `RagConfig` in `src/config/config.py` (the class ends
at line 105). Give it a default and a comment saying *why that default*
(every existing field does — see the eval-provenance comments at
`config.py:28-39`). The field name uppercased **is** the env var
(`extra="ignore"`, `config.py:103-104`), so `MY_KNOB=…` just works.

**Test first:** add to `tests/rag/test_config_seam.py` — assert the default and
assert the value threads through whatever reads it. If a factory should honor it,
assert the factory output changes when you pass a `RagConfig(my_knob=…)`.

**Verify:** `IS_TEST=1 uv run python -m pytest tests/rag/test_config_seam.py -q`.
Confirm nothing else regressed with the triad.

**Blast radius:** small and contained *if* you read it through the `config=` seam
(don't reach for `global_rag_config` inside functions that already receive a
`config`). If you skip the seam, you break eval (which runs several configs in
one process) and the workspace-override layer silently.

**Decision — global-only vs overridable:** a knob is global-only by default. Make
it per-workspace overridable only if it is genuinely per-tenant *behavior*
(not infra). See R9.

---

### R2 · Change the prompt

**Edit:** `src/config/prompts.py` — `RAG_PROMPT` (`prompts.py:19-33`, a
`ChatPromptTemplate` with a `{context}` system block, a `chat_history`
`MessagesPlaceholder`, and the `{question}` human turn) or `QUERY_REWRITE_PROMPT`
(`prompts.py:9-17`). Do **not** add or rename a template variable without updating
every `.invoke`/`.format_messages` call — `RAG_PROMPT` is invoked in
`rag_chain.py:257-261` (generation), `rag_chain.py:194-198` (trace fill), and the
eval at `eval_utils.py:505,531`.

**Test first:** `tests/rag/test_trace.py` asserts the prompt is captured in the
trace; extend it to assert your new instruction/variable appears. If you added a
variable, add a test that a missing value raises loudly rather than silently
formatting to empty.

**Verify:** run the triad, then `scripts/debug_ask.py` on a real channel and read
section 4 ("EXACT PROMPT SENT TO THE LLM") — confirm the change is present and the
tail/context still render. For a wording change meant to improve answers, run a
judged eval arm (0.4) — the prompt is the shared `RAG_PROMPT`, so eval measures it.

**Blast radius:** prod **and** eval (same object — chokepoint C for the prompt).
Every answer changes. This is exactly why it goes through eval.

---

### R3 · Add a retrieval stage to `build_rag_pipeline`

Example: an MMR diversity pass, a metadata pre-filter, a second reranker.

**Edit:** `src/rag/retrieval/retrievers.py:35-85` only. The composition today is
dense → optional BM25 hybrid → optional cross-encoder rerank (with candidate
widening) → optional compression. Insert your stage as another wrapper around
`base_retriever`, gated by a `RagConfig` flag (R1) so it's a toggle, not a
hard-coded behavior change. Keep the widening contract intact: `dense_k =
rerank_fetch_k if use_reranking else retrieval_top_k` (`retrievers.py:52`) is what
lets a later narrowing stage actually improve recall instead of just reordering.

**Test first:** `tests/rag/test_build_pipeline.py` — assert the stage appears when
the flag is on and is absent when off, using a fake vectorstore (no Milvus).

**Verify:** triad, then **eval is mandatory** (0.4). Because production and eval
both call `build_rag_pipeline` (chokepoint C), one edit moves both — that's the
point, and it's also why you must eval before shipping the new default.

**Blast radius:** every retrieval path, prod and eval, simultaneously. Ship the
stage **off by default**; flip the default only after an eval arm wins.

---

### R4 · Swap the embedding model (incl. Milvus dim + re-ingest)

The highest-leverage and highest-risk change. bge-small-en-v1.5 was chosen over
MiniLM in the live ablation (REPORT.md A2, +1.2 correctness over MiniLM-hygiene,
+19.8 over baseline).

**Edit:**
- To use an already-supported provider/model: set `EMBEDDING_PROVIDER` /
  `EMBEDDING_MODEL` env (or the `config.py:21-22` defaults). The bge branch in
  `vector_store.py:94-103` already prepends the required query-side instruction
  (`BGE_QUERY_INSTRUCTION`, `vector_store.py:86`) — getting that wrong silently
  degrades bge, so route bge models through that branch, never plain
  `HuggingFaceEmbeddings`.
- To add a *new* provider: extend `_build_embeddings` in
  `vector_store.py:106-116` with an `elif provider == "…"` branch. Keep it under
  `@lru_cache` — constructing a sentence-transformer costs ~3.5s and would
  otherwise be paid per query (`vector_store.py:107-109`).

**The dim / re-ingest decision (do this consciously):**
- Milvus fixes vector dim **at collection creation**. bge-small is 384-dim, same
  as MiniLM → the collection *shape* is unchanged, but every vector was produced
  by the old model and **must be re-embedded**. text-embedding-3-small is 1536-dim
  → dim changes → you must drop + recreate.
- `_assert_collection_dim` (`vector_store.py:119-137`, called from
  `get_workspace_vectorstore:207`) fails fast at first query if the configured
  embedder's dim ≠ the live collection's — so a lost `EMBEDDING_PROVIDER` env can't
  silently mismatch. If you see `Embedding dim mismatch`, that's this guard doing
  its job; you changed the model against a populated collection.
- Re-ingest with `scripts/reingest_workspace_files.py` (it flips INDEXED files
  back to UPLOADED so `process_file`'s claim-gate doesn't no-op them —
  `reingest_workspace_files.py:13-26`) **and** reset chat vectors
  (`UPDATE messages SET indexed_at = NULL`, then let the indexer re-embed).
  `process_document` purges old file chunks per file (`documents.py:148-152`) so
  re-running is idempotent.

**Test first:** `tests/rag/test_embeddings_selection.py` — assert the provider/
model routes to the right embedder class and that bge gets the instruction prefix.
`tests/rag/test_collection_unified.py` guards the single-collection assumption.

**Verify:** triad; then a **dim probe** — start the app (or run `debug_ask.py`)
against a populated collection and confirm no `RuntimeError` from
`_assert_collection_dim`; then eval (0.4) to confirm the quality lift transfers.

**Blast radius:** the whole corpus. Query embeddings and stored embeddings must be
the same model — a half-migrated collection returns garbage neighbors. Do it as a
single re-ingest that covers chunking + embedder together (see the REPORT.md
"Recommended defaults" note: chunking + embedder both change vectors in one pass).

---

### R5 · Tune segmentation (chat memory) or chunking (files)

**Chat segmentation — Edit:** `CHAT_SEGMENT_GAP_MINUTES` /
`CHAT_SEGMENT_MAX_MESSAGES` (`config.py:83-84`). These set the segment boundary in
`build_chat_segments` (`chat_indexing.py:43-67`): a segment closes on a channel
change, an inactivity gap, or the size cap. Segments — not messages — are the
embedded retrieval unit (SeCom rationale, manual §5.1).

**File chunking — Edit:** `CHUNKING_STRATEGY` (`config.py:62`, default
`by_title`), `CHUNK_SIZE`, `chunk_prepend_section_title` (`config.py:67`,
stays False — it failed its eval bar). The `by_title` path in
`build_chunk_documents` (`documents.py:47-75`) drops noise categories
(`_NOISE_CATEGORIES`, `documents.py:20`) and packs sections via `chunk_by_title`;
the `recursive` legacy path (`documents.py:78-94`) is kept *only* as the ablation
baseline — it never merges short elements (the fragmentation root cause, audit F1).

**Test first:** `tests/rag/test_chunking.py` — assert the strategy produces
merged section-sized chunks (not fragments) and that noise categories are dropped.
For segmentation, `tests/chat/test_chat_indexing.py` asserts gap/size boundaries.

**Verify:** for chunking, **eval is mandatory** (0.4) — this was the dominant fix
(+18.6 pts, REPORT.md A1). For segmentation, unit tests + `debug_ask.py`
(chat memory has no quantitative eval yet — an honest gap, manual §9).
**Re-index to apply to old data**: segment/chunk shape changes only affect newly
ingested vectors; existing rows keep their old shape until re-ingested (R4's
`indexed_at = NULL` recipe for chat).

**Blast radius:** ingest-time only; live retrieval is unchanged until re-ingest.
No live-query risk, which makes this the safest of the "quality" levers to iterate.

---

### R6 · Add a trace field

**Edit:** add the field to `RagTrace` (`src/rag/trace.py:9-33`) with a default,
then populate it in `_fill_trace` (`rag_chain.py:191-220`). `as_dict()`
(`trace.py:40`) serializes automatically — no other change needed for the debug
flag or `debug_ask.py`, because both read the whole dict.

**Test first:** `tests/rag/test_trace.py` — assert the field is present and
carries the expected value after a run.

**Verify:** triad; then `debug_ask.py` and confirm the field shows in the JSON;
optionally hit `/ask` with `debug:true` and check it round-trips over HTTP.

**Blast radius:** additive and safe — the trace is read-only observability. The
one rule: keep it **JSON-safe** (`doc_summary` at `trace.py:35-38` is the pattern
for compacting Documents) and keep the `chat_selection` arithmetic honest if you
touch it (see Invariant I6).

---

### R7 · Add an `/ask` behavior (+ the endpoint test pattern)

Example: a new request field, a response marker, a header.

**Edit:** `src/rag/router.py`. The request schema is `AskRequest`
(`router.py:54-58`); the handler is `ask_question` (`router.py:145-232`). Respect
the async-correctness contract: retrieval runs eagerly in a worker thread
(`_build_and_prepare` via `asyncio.to_thread`, `router.py:168-191`) so failures
become a real **502 before any bytes stream**; generation streams via
`iterate_in_threadpool` (`router.py:200`) so no token blocks the event loop. Don't
move blocking work onto the event loop. Persist **only after a successful stream**
(`_persist_exchange`, `router.py:95-116`) — this is what prevents orphaned
question turns.

**Test first — the pattern is `tests/rag/test_ask_endpoint.py`:** monkeypatch
`rag.router.RAGChain` with a `_FakeChain` (`test_ask_endpoint.py:18-48`) so no
Milvus/LLM is touched; drive it through the `client` TestClient fixture. The fake
exposes `fail_prepare` / `fail_stream` flags so you can assert the 502 path
(`test_ask_prepare_failure_is_502_and_persists_nothing`), the mid-stream
`[ask:error]` marker path, the debug-payload path, and the broadcast. Add your
assertion in the same style; verify persistence with a **direct DB read**
(`_messages`, `test_ask_endpoint.py:59-67`) — the `GET /messages` endpoint 500s on
assistant rows (pre-existing chat-owner bug, don't fix it here).

**Verify:** `IS_TEST=1 uv run python -m pytest tests/rag/test_ask_endpoint.py -q`,
then the triad.

**Blast radius:** the endpoint only, *if* you keep the thread boundaries. Break
them and you regress the event-loop guarantee (manual §0 proven number: `/docs`
stays ~1ms during an `/ask`).

---

### R8 · Change chat-selection scoring

**Edit:** `src/rag/retrieval/chat_selection.py` — `select_chat_context`
(`chat_selection.py:33-71`). The scoring is
`relevance(1/(1+rank)) × (floor + (1-floor)·0.5^(age_h/half_life))`
(`chat_selection.py:44-47`); redundancy is greedy Jaccard suppression
(`chat_selection.py:53-61`). Keep it a **pure function** — it takes candidates and
returns a subset, no I/O, so it's trivially testable and can't fail an answer
(the caller wraps recall in a degrade-to-file-only guard,
`rag_chain.py:179-183`).

**Test first:** `tests/rag/test_chat_selection.py` (scoring) and
`tests/rag/test_chat_recall_dedupe.py` (tail-dedupe interaction). Assert: an
old-but-uniquely-relevant segment survives (the `_DECAY_FLOOR = 0.25` guarantee),
near-duplicates are dropped, and the `stats` dict **closes** —
`considered == dropped_redundant + kept + truncated` (`chat_selection.py:63-69`).

**Verify:** triad; then `debug_ask.py` and read the `chat_selection` block
(`fetched/dropped_tail/dropped_redundant/truncated/kept`) — the arithmetic must
sum (Invariant I6). No eval grid covers chat memory yet, so unit tests + live
trace are the bar; say so honestly.

**Blast radius:** chat-memory recall quality only. File retrieval untouched. Chat
memory can never kill an answer (the guard), so the worst failure is "memory
ignored something," visible in the trace.

---

### R9 · Add an `ai_settings` whitelist field (bounds + tests)

Make a global knob per-workspace/channel overridable.

**Edit two places, in lockstep** (`src/rag/ai_settings.py`):
1. Add the field name to `OVERRIDABLE` (`ai_settings.py:26-32`).
2. Add a **bounded** field to `AiConfigPatch` (`ai_settings.py:55-69`) with
   `Field(ge=…, le=…)`. Bounds are not optional — `retrieval_top_k` is
   `ge=1, le=50`, `rerank_fetch_k` `ge=1, le=100`, etc. `extra="forbid"`
   (`ai_settings.py:57`) makes anything off-whitelist a 422, not a silent no-op.
   For a value vetted against a list (like `openai_model` vs
   `ai_model_allow_list`), add a `@field_validator` (`ai_settings.py:71-76`).

Why both: `_clean` (`ai_settings.py:79-103`) re-validates each stored override on
**read** and stores the **coerced** value, because `model_copy(update=…)` in
`resolve_ai_config` (`ai_settings.py:131`) does **not** re-validate. A field in
`OVERRIDABLE` but not in `AiConfigPatch` would pass through unbounded/unvalidated.

**Test first:** `tests/rag/test_ai_settings.py` (resolution/cleaning) and
`tests/rag/test_ai_settings_api.py` (endpoint 422 on bad value, 200 + provenance
on good). Assert: out-of-bounds → dropped on read (or 422 on write), string `"9"`
lands as int `9` and `"false"` as bool `False` (the coercion, `ai_settings.py:99-102`),
and provenance reports `workspace`/`channel` correctly. `test_ask_endpoint.py:138-182`
shows the end-to-end override assertion (workspace + channel layering).

**Verify:** those three test files, then the triad.

**Blast radius:** adds a per-tenant lever. Keep infra knobs (indexer cadence,
embedding provider/model, collection name) **out** — one indexer and one
collection serve everyone, so exposing them per-workspace would be an illusion
(manual §2). Overridable = per-tenant *behavior* only.

---

### R10 · Run / extend the eval

**Run:** the two commands in §0.4. Phase 1 is CPU-only and free (retrieval
metrics); Phase 2 is judged end-to-end via OpenRouter and needs `data/guide.pdf`
(git-ignored) + an API key.

**Extend — Edit:** `evaluation/live_pdf_eval/run_ablation.py` (arms: `CHUNKINGS`,
`EMBEDDERS`, `FETCH_KS`, `TOP_KS` near the top; `rag_config`/`build_corpus`/
`build_store`/`retriever_for` build each arm through production functions) and
`evaluation/live_pdf_eval/common.py` (metrics + OpenRouter helpers). The notebook
harness `tests/rag_evaluation/eval_utils.py` is the other lane: `VariantConfig`/
`RagVariant` (`eval_utils.py:317,414`) also call the production `build_rag_pipeline`
(`eval_utils.py:447-449`) and `RAG_PROMPT`.

**Test first:** `tests/rag/test_eval_uses_production_path.py` is the guard that
eval calls the production pipeline — if you refactor eval, that test must still
pass (it's the machine-checked form of "eval == ship").

**Verify:** re-run the grid; record the winner and the decision rule in
`evaluation/live_pdf_eval/REPORT.md`. The workflow to pick a default: run grid →
winning arm's flags **become** the `config.py` defaults (that's exactly how
`retrieval_top_k=10`, `rerank_fetch_k=50`, `chunking_strategy="by_title"` were
set — see the provenance comments in `config.py:28-62`).

**Blast radius:** none to production until you change a default. This is the
sandbox where retrieval changes earn their way in.

---

### R11 · Restart the dev stack

The dev app runs on a **dedicated `talos_dev` DB (port 5433), never `talos_test`**
(pytest drops `talos_test`). Local models, no OpenAI (quota):

```bash
# infra
docker compose up -d postgres milvus-standalone redis          # + etcd/minio as needed
# env for local models (Ollama for LLM, HF for embeddings, CPU-pinned)
export DATABASE__NAME=talos_dev DATABASE__PORT=5433
export EMBEDDING_PROVIDER=huggingface EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
export OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama OPENAI_MODEL=qwen2.5:7b-instruct
export CUDA_VISIBLE_DEVICES=""                 # keep the 8GB GPU for Ollama
export USE_HYDE=false USE_QUERY_REWRITE=false USE_RERANKING=true   # fast local flags
# processes (from the worktree)
PYTHONPATH=src uv run uvicorn app:app --port 8000
PYTHONPATH=/home/romia/talos-main/src:/home/romia/talos-main uv run taskiq worker broker:broker   # +scheduler
```

Notes grounded in the running-env record: HyDE hardcodes a model name, so alias
it in Ollama (`ollama cp` gpt-3.5-turbo → qwen) if you turn HyDE on locally; run
the taskiq worker with the doubled `PYTHONPATH` so `import src` and the indexer's
mapper imports (`workspace.model`, `filesystem.model`) resolve; run exactly **one**
scheduler (Invariant I5). Verify the stack with `debug_ask.py` against a seeded
channel and confirm `/docs` stays ~1ms during an `/ask` (the event-loop guarantee).

**Blast radius:** none to code. The failure mode is pointing the running app at
`talos_test` — which wipes it. Don't.

---

### R12 · Coordinate a teammate-owned change (the report-first rule)

Some files are owned by teammates (kiro == Kyrollos Youssef): `chat/model.py`,
`chat/realtime.py`, `chat/router.py`, `workspace/router.py`, filesystem upload
hooks, `docker-compose.yaml` service defs. The rule: **never hand-repair a
teammate's code.** If you need a change there, or you find a bug there:

1. **Report it, don't fix it.** Write it into the handoff doc
   (`docs/chat-memory-handoff.md`) and tell the owner. Examples already logged:
   the un-awaited `sio.send` at `chat/router.py:39`, the `GET /messages` 500 on
   assistant rows, the `Message.content` str→JSONB migration on `origin/rich-msg`.
2. **Sync, don't diverge.** When their branch lands, sync from main rather than
   forward-porting by hand.
3. **Import-only.** Where you must interoperate, import read-only and never
   mutate — the `ai_message` broadcast does exactly this: `from chat.realtime
   import sio` with a comment "teammate module: import-only, never modified"
   (`router.py:127`).
4. **Isolate the seam.** Reading `Message.content` goes through the *one* adapter
   `rag/message_text.py` so the rich-msg migration is a one-file review, not a
   scattered break.

**Verify:** your change touches only your files; `git diff --stat` should show
teammate files untouched (or, if unavoidable, minimal and pre-declared in the
handoff doc — the audit confirmed only 3 teammate files touched, all minimal).

---

## Invariants you must never break

Each has a guard test. If your change would violate one, you're doing the wrong
change — stop and rethink.

### I1 · Tenancy expressions are always conjoined with `workspace_id`
File retrieval builds `workspace_id == "…" && source == "file"` and only *adds*
`file_id in [...]` (`rag_chain.py:103-107`). `file_ids` is **not** a
cross-workspace hole precisely because the workspace clause is always present
(audit §6, refuted). Chat recall is scoped `chatroom_id == "…" && source ==
"chat"` (`rag_chain.py:114`). Deletes carry the same scoping
(`vector_store.py:246-253`).
**Guard:** `tests/rag/test_rag_chain.py` (expr construction),
`tests/rag/test_collection_unified.py`. Never build a Milvus expr without the
tenant clause.

### I2 · Tier exclusivity — every message is in exactly one tier
A message is either in the un-indexed tail (tier 1, `indexed_at IS NULL`,
`router.py:77`) or recalled as a segment (tier 2). The router passes tail ids as
`exclude_message_ids` and recall drops any segment overlapping the tail
(`rag_chain.py:154-162`), so a message briefly in both (vector lands before the
`indexed_at` commit) is counted once.
**Guard:** `tests/rag/test_chat_recall_dedupe.py`. Never inject the tail without
also excluding its ids from recall.

### I3 · eval == ship
Production and evaluation both call `build_rag_pipeline` and `RAG_PROMPT`; the
eval's `production_default` derives from `global_rag_config`. A retrieval change
that doesn't move eval isn't measured.
**Guard:** `tests/rag/test_eval_uses_production_path.py`. Never fork a
retrieval/prompt path "just for eval" — that's the hole that silently ships
dense-only when you flip `use_hybrid_retrieval` from eval numbers (manual §9,
honest gap).

### I4 · The config chokepoint — one place, threaded by seam
All knobs live on `RagConfig` and reach components via a real `config=` argument
(`rag_chain.py:96-126`, `retrievers.py:35`, `generation.py:9`). This is what lets
one process run several configs (eval, per-workspace overrides).
**Guard:** `tests/rag/test_config_seam.py`. Never read `global_rag_config`
directly inside a function that already receives a `config`.

### I5 · One indexer run at a time (advisory lock on a dedicated connection)
`index_pending_messages` takes pg session-advisory lock `0x7A105C47` on a
**dedicated `engine.connect()` connection** held for the whole run
(`chat_indexing.py:135-180`) — *not* the ORM session's pooled connection, which
can change across commits (a lock taken there could unlock on a different pooled
connection and leak forever). A second run logs and returns 0
(`chat_indexing.py:143-145`). Order is purge → ingest → stamp → commit so a crash
leaves rows un-stamped and the next tick re-selects the same deterministic batch.
**Guard:** `tests/chat/test_chat_indexing.py`. Never move the lock onto the ORM
session; never stamp before ingest; run exactly one scheduler.

### I6 · Trace honesty — the selection arithmetic closes
`chat_selection` reports `fetched = dropped_tail + dropped_redundant + truncated
+ kept` and `select_chat_context`'s own stats close
`considered = dropped_redundant + kept + truncated` (`chat_selection.py:63-69`,
`rag_chain.py:172-178`). The trace must reflect what actually happened — it's the
one source of truth read by three surfaces.
**Guard:** `tests/rag/test_chat_selection.py`, `tests/rag/test_trace.py`. Never
report a count you didn't compute; if you add a drop reason, add it to the sum.

### I7 · The teammate-code rule
Never hand-repair teammate-owned files; report and sync (R12).
**Guard:** social + `git diff --stat` (teammate files untouched) + the handoff
doc. The audit's branch-discipline check is the standing verification.

---

*Three chokepoints — `RagConfig` · `build_rag_pipeline` · `RagTrace`. One
boundary — the indexer. One guarantee — chat memory can never kill an answer.
Change through the chokepoints, prove it with the loop, and you can't be wrong by
accident.*
