# Deep Audit + Research Findings — chat memory, /ask, WebSockets, indexing

Date: 2026-07-02 · Branch: `feature/chat-message-memory` (17 commits ahead of main)
Method: 4 adversarial code audits + 3 external research tracks (multi-agent, claims
verified against code/installed-library source/primary docs; research claims passed
3-vote adversarial verification). Analysis only — no fixes, no plan.

---

## Part 0 — Empirical confirmations (live dev stack, 2026-07-02)

- **Event-loop blocker demonstrated**: with the app idle, `/docs` answers in
  ~0.8–1.3 ms. During a single `/ask` (local fast config: HyDE/rewrite off,
  qwen2.5:7b), a concurrent `/docs` request took **6.29 s** (blocked through the
  whole retrieval + generation-start phase), then ~110 ms per probe during token
  streaming, recovering to ~1 ms the moment the stream ended (`/ask` total 7.66 s).
  One question froze every other request on the worker. Production config
  (OpenAI + HyDE + rewrite) would block longer.
- **Disconnect orphan demonstrated**: aborting the client 1.5 s into an `/ask`
  stream left the channel with the user question persisted and **no assistant
  message** — the partial answer (already generated) was dropped, and the dangling
  human turn will be injected into future tails. Confirmed by direct DB inspection.
- Functional positive: `/ask` answered the seeded-memory questions correctly
  (both facts recalled from indexed chat memory).

## Part 1 — Code audit findings (ranked)

### 1. BLOCKER — `/ask` blocks the event loop for the whole request
`src/rag/router.py:128-132`: the async `stream()` generator iterates the **sync**
`chain.stream_query(...)`. Everything inside is synchronous LangChain: Milvus search,
the CPU cross-encoder rerank, HyDE + query-rewrite LLM calls, and every streamed LLM
token (`rag_chain.py:206-242`, `generation.py:20-26`). Starlette iterates async
StreamingResponse bodies directly on the event loop, so one `/ask` stalls every other
request and every Socket.IO client on that worker. This must be resolved before any
WS-native /ask (which would put even more traffic on the same loop).
Verified first-hand.

### 2. HIGH — indexer can double-run concurrently; idempotency claim only holds sequentially
- taskiq's scheduler overlap guard covers only the enqueue coroutine (ms), not task
  execution (`taskiq/scheduler/run.py`, verified in installed source).
- The worker container runs **2 processes by default** (`--workers` default 2, no
  override in `docker-compose.yaml:36`).
- RedisStreamBroker redelivers unacked messages after `idle_timeout` = **10 min**
  (`taskiq_redis/redis_broker.py:162`) — a second concurrency vector.
- `index_pending_messages` (`src/processing/chat_indexing.py:88-109`) has **no
  locking/claim step** (contrast `processing/tasks.py:30-41`, which claims files
  atomically). Two overlapping runs can select the same batch; interleaved
  purge→ingest→stamp can leave **permanent duplicate vectors** in Milvus (nothing
  re-purges once `indexed_at` is stamped) or a window with zero vectors.
- **No retry exists**: SmartRetryMiddleware is opt-in per task via `retry_on_error`
  label, which `index_chat_messages` doesn't carry (`chat_tasks.py:21`,
  `smart_retry_middleware.py:71-85`). Recovery = next cron tick (safe only because
  nothing is stamped on failure).
- Scheduler singleton is ops-discipline only (taskiq docs: "run only one instance").

### 3. MAJOR — /ask failure modes: broken 200s and orphaned questions
- Mid-stream Milvus/LLM error → client gets HTTP **200** with truncated body (headers
  flushed before lazy retrieval fires). No try/except anywhere in the stream path.
- Client disconnect mid-stream → generator cancelled → `_persist_assistant_turn` and
  trace-fill never run. The user question (persisted *before* streaming,
  `router.py:114`) remains as a dangling human turn injected into future tails.
- `/ask` HTTP surface has **zero tests** (nothing imports `rag.router`).

### 4. MAJOR — "eval measures what prod ships" has two holes (verified first-hand)
- **Hybrid retrieval is dead in prod**: `build_rag_pipeline` only builds BM25 when a
  `corpus` is passed (`retrievers.py:60-73`); prod `RAGChain` never passes one
  (`rag_chain.py:108-110`); eval always does (`eval_utils.py:281,448`). Flipping
  `use_hybrid_retrieval` on from eval results silently ships dense-only.
- **Chat memory has zero eval coverage**: eval hardcodes `chat_history=[]`
  (`eval_utils.py:505,531`) and builds no chat retriever. The headline new feature is
  quantitatively unmeasured.

### 5. MAJOR — memory-path inconsistencies
- `conversation_memory_k` is dead weight: used only as a boolean (`rag_chain.py:113`);
  `InMemoryChatMessageHistory` is unbounded (k=3 ignored) and GC'd per request —
  contributes nothing. Two parallel memory mechanisms, one dead. Verified first-hand.
- `chat_context_cap=50` is a message-count cap with **no token budget** — one pasted
  wall of text in the tail is uncapped.
- **"Every message is in exactly one tier" breaks under backlog**: >50 un-indexed
  messages in a channel → messages 51+ are in *neither* tier until the indexer catches
  up (warning logged, gap not prevented). Global drain rate is hard-capped at
  batch 500 / 5 min = 100 msg/min across all channels.
- Tier-1 tail maps SYSTEM messages to HumanMessage (`router.py:77-81`) — prompt noise.

### 6. Security / tenancy
- **REFUTED**: `file_ids` is NOT a cross-workspace hole — the Milvus expr conjoins
  `workspace_id == …` with `file_id in […]` (`rag_chain.py:89-92`, verified). Residual:
  no intra-workspace per-file ACL (the router TODO stands, severity depends on whether
  Talos ever gets per-file permissions).
- **`HOW_TO_TEST_ASK.txt` contains a live JWT at the repo root** (untracked). One
  careless `git add -A` from leaking. Move/gitignore/delete.

### 7. Teammate code & cross-branch risk
- Branch discipline is clean: only 3 teammate-owned files touched, all minimal and
  pre-declared in `docs/chat-memory-handoff.md` (chat/model.py +indexed_at,
  workspace/router.py +2 lines mount, docker-compose scheduler). Tests: 44/44 pass.
- **Pre-existing teammate bug (inform kiro, don't fix)**: `chat/router.py:39` calls
  `sio.send(...)` **without await** in an async handler — the HTTP-message broadcast
  silently never fires (verified; pytest even warns "coroutine never awaited"). Also
  double-encodes (`model_dump_json()` inside a dict).
- **`origin/rich-msg` lands ~now** (based on current main) and changes
  `Message.content` str→JSONB. Three call sites on our branch silently break:
  `chat_indexing.py:46`, `router.py:79-81`, `router.py:92-93` (the last also bypasses
  rich-msg's `set_content()` invariants). Handoff doc only flags 1 of 3.
- `origin/search`: `source=="chat"` vectors will leak into its file search unless its
  Milvus expr filters source — already noted in handoff caveats.

### 8. Minor / presentability
- Dead config (Task 8 backlog confirmed): `RagConfig.yaml_file` (`config.py:75` —
  spec claims it was removed; it wasn't), `config/prompts/*.yaml`,
  `config/rag_config.example.yaml`, `RAG_PROMPT_WITHOUT_MEMORY`,
  `get_multiquery_retriever` — all unused.
- `chatroom_id` vs `channel_id` leaks at ~5 seams; documented everywhere, but it's now
  a permanent Milvus metadata name.
- `get_workspace_vectorstore` docstring claims it establishes the ORM connection; it
  actually relies on the import-time `MilvusClient.__init__` monkeypatch.
- Import-time monkeypatch (`_install_milvus_client_orm_bridge`) is justified +
  documented, but call it out explicitly in any PR description.

---

## Part 2 — Research findings

### A. Smart context selection (deep-research, 3-vote verified: 39 confirmed / 11 refuted)
- **Best-evidenced upgrade: topic-coherent segments as the retrieval unit.**
  SeCom (ICLR 2025, arxiv 2502.05589): segment-level beats turn-level and
  session-level under the same retriever — GPT4Score 71.57 vs 65.58 vs 63.16 (LOCOMO).
  Embedding-drift/TextTiling-style segmentation is index-time-cheap (cosine pass over
  embeddings already computed, one threshold, left-context-only = online-safe;
  embedding-enhanced TextTiling F-score 53.5→74.7, INTERSPEECH 2016). LLM segmenters
  (Def-DTS, ACL 2025) score higher but cost an LLM call per segment.
- **Second (near-free, bundle): time-decay + MMR re-rank at query time.**
  Generative-agents' `α·recency(γ^hours) + α·relevance` formula; LiCoMemory's Weibull
  decay; MMR/AdaGReS redundancy suppression (8–15pp IOU over plain top-k). Pure
  re-ranking of the existing top-k candidates — no new infra.
- **Skip reply-graph/thread-aware selection**: every academic claim of a quality win
  was REFUTED 0-3 in adversarial verification (GAAMA, SGMEM claims unsupported).
  Only mechanical feasibility (Slack threads API) survived.
- **Skip knowledge-graph memory (Zep/Graphiti)**: real but disproportionate — graph DB
  + multi-LLM-call ingestion per message; uneven gains (regressions on single-session
  questions). Several headline Zep numbers were refuted (DMR 94.8%, generic "18.5%").

### B. Event-driven vs cron indexing (verdict: keep the cron)
- The sweep *is* documented industry practice: LangChain Indexing API and LlamaIndex
  ingestion pipelines are hash/stamp-based periodic sweeps structurally identical to
  `indexed_at IS NULL` + stamp. Zep itself documents minutes of ingestion lag —
  without Talos's tail-injection masking.
- Outbox/search-reindex literature: an event path is only a latency layer **on top of**
  a reconciling sweep, never a replacement. "Event-driven instead of cron" is a false
  dichotomy.
- taskiq specifics: the `delay` label is **silently ignored** by RedisStreamBroker
  (verified in source — fires immediately). Real debounce requires
  `schedule_by_time` + a Redis ScheduleSource (supported, replaceable `schedule_id`) —
  i.e. you keep the scheduler process anyway.
- Per-message events destroy embedding batching (500/call → 1/call) and lose the
  sweep's crash-recovery guarantee.
- If freshness ever matters: tighten tick/grace (one line) before adding architecture.
- **The real quality lever is the retrieval unit, not the trigger** — segment/window
  grouping (see A) mildly *favors* batch/settled processing. Three independent tracks
  converged on this.

### C. WebSocket-native /ask
- Socket.IO facts (python-socketio 5.16.2, docs-verified): same-process `await
  sio.emit(...)` from an HTTP handler is officially supported; external processes
  (taskiq worker) use `AsyncRedisManager(url, write_only=True, channel="sio#")` —
  channel string must match or delivery silently fails (known footgun issue family).
  No documented ordering guarantee, no replay (a member joining mid-stream misses
  earlier tokens), no backpressure, no batching guidance — per-token emits are one
  Redis PUBLISH each.
- Product semantics: no surveyed product documents "everyone watches the AI type" in
  shared channels; Discord's edit-based pattern (~1 edit/1.2s, visible to all) is the
  only structurally forced precedent. SSE remains the industry default for the
  one-way streaming leg; dual transport (HTTP stream to asker + pub/sub broadcast) is
  neither blessed nor condemned in the literature — a composition of two documented
  primitives (closest prior art: Vercel resumable-streams).
- Codebase-grounded options (complexity-ranked):
  (a) **HTTP /ask streams to asker + emits final answer to the channel room** — lowest
      risk; stays in rag/ (import sio read-only, custom event payload); MUST await.
  (c) **/ask (or the message-handler TODO) kicks a taskiq task; worker generates,
      persists, broadcasts via write-only Redis manager** — the clean end-state:
      moves blocking LLM work off the web loop entirely, zero teammate-code changes.
  (b) **Socket.IO `ask` event handler streaming tokens** — worst fit: runs the sync
      LLM generator on the WS event loop and requires editing teammate-owned
      realtime.py.
- Blockers/constraints for any option: `MessageSchema.sender_id` is non-optional, so
  the AI reply cannot ride the existing `message` broadcast path (needs a distinct
  event/payload or a teammate schema change); finding #1 (event-loop blocker) must be
  fixed first; the current `chat-ui` never opens a socket (HTTP-stream only).

---

## Convergence (the headline for scoping)
1. **Segment-grouped chat memory** is the single best quality-per-complexity upgrade —
   supported independently by the smart-context research (SeCom et al.), the indexing
   research (grouping favors batch processing; keep the cron), and the audit (per-
   message embeddings + flat tail are the weak points, not the trigger or transport).
2. **Async correctness before WS features**: the event-loop blocker, the indexer
   concurrency gap, and error/disconnect handling are the "perfectly working" gaps.
3. **The cron stays; the transport can be layered later** — option (a) cheap, option
   (c) clean; both live entirely in our code.
