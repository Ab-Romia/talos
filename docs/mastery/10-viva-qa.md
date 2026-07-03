# 10 · Viva / Defense Q&A Bank

Forty questions an examiner or teammate will ask, with crisp, grounded model
answers. Each answer is quotable in a defense and traceable to code. Organized by
theme: architecture, correctness, security/tenancy, evaluation, operations, and
tradeoffs/YAGNI.

Where an answer leans on a concept (embeddings, chunking, reranking, decay math,
and so on), a pointer like `(→ 00 §n)` sends you to `00-foundations.md` to rehearse
the idea underneath before you're asked to explain it cold.

---

## Architecture

**Q1. Why one Milvus collection for both files and chat, instead of two?**
One collection (`talos_documents`, our vector database → 00 §3) with a `source`
field (`"file"` / `"chat"`)
keeps a single connection, schema, and index to operate, and lets one query filter
to either stream. Retrieval always conjoins `source == "file"` or `source ==
"chat"` into the tenancy expr (`rag_chain.py:103,114`), so the streams never bleed.
Two collections would double the infra with no isolation benefit the `source`
filter doesn't already give.

**Q2. Why embed conversation as segments, not individual messages?**
A lone message like "yes, let's do that" embeds meaninglessly — per-message vectors
fragment a conversation below the level similarity search can work on (embeddings
encode meaning as geometry; too little text gives a mushy, unfindable vector,
→ 00 §2/§4). The indexer
groups settled messages into topic-coherent segments closed by an inactivity gap
or size cap (`build_chat_segments`, `chat_indexing.py:43-67`). SeCom (ICLR 2025)
showed segment-level retrieval beats turn- and session-level under the same
retriever (GPT4Score 71.57 vs 65.58 vs 63.16 on LOCOMO), and an inactivity gap is
the cheapest online-safe boundary — no extra LLM or embedding calls.

**Q3. Why split `RAGChain` into `prepare()` and `stream_answer()`?**
It's the async-correctness story. `prepare()` does all retrieval synchronously but
the router runs it in a worker thread (`asyncio.to_thread`, `router.py:191`), so if
Milvus or the rewriter fails it raises **before any response bytes are sent** →
real 502, not a broken 200 (`rag_chain.py:228-250`). `stream_answer()` only
generates, iterated via `iterate_in_threadpool` (`router.py:200`), so no LLM token
ever blocks the event loop. Measured result: `/docs` stays ~1ms during an active
`/ask` (manual §1).

**Q4. What are the "three chokepoints" and why do they matter?**
`RagConfig` (every knob, one place, `config.py`), `build_rag_pipeline` (all file
retrieval, `retrievers.py:35`), and `RagTrace` (all observability, `trace.py`).
They matter because learning three things lets you reason about the whole system:
change a knob and it reaches everything via the `config=` seam; change retrieval
once and production *and* eval move together; read one trace and every debug
surface agrees.

**Q5. How does config layering (global → workspace → channel) work?**
`resolve_ai_config` reads the workspace-default row (`channel_id IS NULL`) and the
channel row, cleans each against the whitelist, and layers them via
`model_copy(update=...)` in order global → workspace → channel — channel wins
(`ai_settings.py:106-132`). The result is a **real `RagConfig`**, so every existing
`config=` seam stays honest, and per-field origin is recorded as
`config_provenance` in the trace.

**Q6. Why is the eval harness allowed to share production code — isn't that
circular?**
It's the opposite of circular: eval calls the *same* `build_rag_pipeline` and
`RAG_PROMPT`, with the only substitution being `InMemoryVectorStore` for Milvus
(same cosine geometry, → 00 §2). That's what makes "eval == ship" (→ 00 §12)
literally true — a retrieval change that doesn't move eval isn't measured, and the
guard `tests/rag/test_eval_uses_production_path.py` machine-checks the shared path.

**Q7. Why does `/ask` broadcast to the channel, and why a custom event?**
So every channel member sees the answer, not just the asker who holds the HTTP
stream. It can't ride the normal chat `message` event because `MessageSchema`
requires a non-null `sender_id` and assistant rows have `sender_id = NULL`, so it
emits a custom `ai_message` payload on room `channel:{id}`
(`router.py:119-142`). The broadcast is best-effort — a failure logs a warning and
the request still succeeds.

**Q8. Why is there only one RAG entry point, and what does ordinary chat do?**
`POST …/ask` is the sole LLM path; ordinary chat (`POST …/messages`) just stores
and broadcasts. That keeps `/ask` additive and self-contained — nothing in the
normal chat flow calls the model, so the RAG feature can't destabilize messaging.

**Q9. What is the `message_text` seam and why does it exist?**
`rag/message_text.py` is the single place that turns `Message.content` into text.
It exists so the incoming `origin/rich-msg` migration (content str → ProseMirror
JSONB) is a **one-file review**, not a scattered break across every read site
(`chat_indexing.py`, `router.py`, `debug_ask.py` all go through it).

---

## Correctness

**Q10. How is file re-ingestion idempotent?**
`process_document` calls `delete_file_chunks(file_id, workspace_id)` immediately
before re-ingesting (`documents.py:148-152`), so re-running deletes the prior
chunks first — Milvus has no unique constraint on `(file_id, chunk_index)`, so
without the purge a retry would duplicate vectors. This is the general
at-least-once/idempotent-retry discipline the whole task-queue layer needs
(→ 00 §13).

**Q11. How is the chat indexer idempotent on a crashed tick?**
Order is **purge → ingest → stamp → commit** (`chat_indexing.py:157-169`). A crash
before the stamp leaves rows un-`indexed_at`; the next tick re-selects the *same*
deterministic oldest batch (`ORDER BY sent_at ASC LIMIT`) and the pre-ingest purge
(`delete_chat_segments_for_messages`, matching any of the batch's `message_ids`)
removes partial segments before re-inserting. Segments are batch-local, so no
segment ever spans two batches. Same idea as Q10: the queue redelivers at least
once, so the handler purges-then-inserts to stay idempotent (→ 00 §13).

**Q12. Walk me through the advisory-lock design and the bug it avoids.**
`index_pending_messages` takes pg session-advisory lock `0x7A105C47` on a
**dedicated `engine.connect()`** held for the whole run (`chat_indexing.py:135-180`).
The bug it avoids: session locks bind to the *connection*, and the ORM session
commits mid-run — a commit can return its pooled connection to the pool, so
unlocking via the ORM session could hit a different connection, silently no-op, and
leak the lock forever. The dedicated connection is also crash-safe: pg releases the
lock when the connection drops — necessary because the queue underneath is
at-least-once, so "a second run might start" is a real case, not a hypothetical
(→ 00 §13).

**Q13. Two worker processes, cron overlap, Redis redelivery — how do you prevent
double indexing?**
All three concurrency vectors funnel through the same advisory lock: a second
concurrent run calls `pg_try_advisory_lock`, gets `false`, logs "lock held
elsewhere," and returns 0 (`chat_indexing.py:143-145`). taskiq's scheduler overlap
guard only covers the enqueue coroutine, and RedisStreamBroker redelivers after a
10-min idle timeout (Redis Streams give at-least-once delivery, → 00 §13) — the
lock is the actual guarantee, not the scheduler.

**Q14. How does the AI-config PATCH handle two concurrent first-writes?**
Check-then-insert races the unique constraint. `_apply_patch` catches
`IntegrityError`, rolls back, re-selects the row a concurrent writer just created,
merges into it, and commits — exactly one retry (`settings_router.py:67-76`). The
DB constraint is the source of truth; the code reconciles to it rather than
trusting its earlier `SELECT`.

**Q15. Why re-validate overrides on read when they were validated on write?**
Because `model_copy(update=...)` does **not** re-run validators
(`ai_settings.py:131`). A row written before a bound tightened, or a model since
dropped from the allow-list, or hand-edited JSONB, would flow unchecked into a live
`RagConfig`. `_clean` re-validates every override per key on read and drops what
fails (`ai_settings.py:79-103`).

**Q16. Why store the coerced value, not the raw one?**
JSONB round-trips strings. Stored raw, `use_hyde: "false"` would set a **truthy
string** — inverting "off" to "on" — and `"9"` would break arithmetic. `_clean`
stores `getattr(patch, k)`, the coerced post-validation value, so bools and ints
land as bools and ints (`ai_settings.py:99-102`).

**Q17. What happens if chat recall fails mid-answer?**
Nothing fatal. The whole recall path is wrapped in one guard that logs a warning
and returns `[]` on any exception, degrading to file-only context
(`rag_chain.py:179-183`). This is the standing guarantee: *chat memory can never
kill an answer.*

**Q18. What happens if the client disconnects mid-stream?**
The generator is cancelled before `_persist_exchange` runs, so **nothing is
persisted** — no orphaned question turn pollutes the channel or future prompts.
Persistence deliberately happens only *after* a successful stream
(`router.py:207-211`); the question and answer commit together in one transaction.

**Q19. What does the client see if generation dies mid-stream?**
The stream is already a 200 (headers flushed), so it ends with the marker
`[ask:error]` and persists nothing (`router.py:203-206`). A client can distinguish
"model finished" from "backend died" by that marker.

**Q20. How is "every message in exactly one tier" preserved at the boundary?**
A message is tier-1 (un-indexed tail, `indexed_at IS NULL`) or tier-2 (recalled
segment). The router passes tail ids as `exclude_message_ids`, and recall drops any
segment whose `message_ids` overlap the tail (`rag_chain.py:154-162`). So a message
momentarily on both sides — its vector lands a beat before its `indexed_at` commit
— is still counted once.

---

## Security / Tenancy

**Q21. How is workspace isolation enforced in retrieval?**
Every file query conjoins `workspace_id == "<id>" && source == "file"` into the
Milvus expr (`rag_chain.py:103`); chat recall conjoins `chatroom_id == "<id>" &&
source == "chat"` (`rag_chain.py:114`). The tenant clause is always present and
always ANDed, so no query can reach another workspace's vectors.

**Q22. Isn't `file_ids` a cross-workspace hole?**
No — this was audited and refuted. `file_ids` only *adds* a `file_id in [...]`
clause **on top of** the mandatory `workspace_id ==` clause (`rag_chain.py:103-107`),
so a caller passing another tenant's file id still gets zero rows. The residual
(noted, low severity) is that there's no intra-workspace per-file ACL yet — the
router TODO stands.

**Q23. How is the override whitelist designed to be safe?**
`AiConfigPatch` uses `extra="forbid"` (`ai_settings.py:57`) so any field not on the
whitelist is a 422, never a silent no-op; numeric fields carry explicit bounds
(`retrieval_top_k` `ge=1,le=50`, `rerank_fetch_k` `ge=1,le=100`, etc.); and
`openai_model` is vetted against `ai_model_allow_list` on write **and** neutralized
on read if it later falls off the list (`ai_settings.py:62-76`). Defense in depth:
validated on write, re-validated and coerced on read.

**Q24. Why are some knobs global-only and un-overridable?**
Indexer cadence, batching, segmentation, embedding provider/model, and the
collection name are process-wide infra — there is **one** indexer and **one**
collection for everybody. Exposing them per-workspace would be an illusion of
control (manual §2). Only genuine per-tenant *behavior* (11 fields in `OVERRIDABLE`)
is overridable.

**Q25. Could chat vectors leak into a teammate's file-search feature?**
Only if that feature forgets to filter `source`. The shared collection means
`origin/search`'s file search must add `source == "file"` to its expr or it will
match `source == "chat"` vectors — flagged in the handoff caveats. Within RAG's own
code the filter is always present.

**Q26. How do you keep secrets and tenant data out of logs and the repo?**
The `ask.trace` digest logs only counts and timings, not content
(`router.py:213-223`); full content lives in the trace, surfaced only via explicit
`debug:true`. The audit flagged a live JWT in an untracked `HOW_TO_TEST_ASK.txt` at
the repo root as a leak risk (one `git add -A` from exposure) — the discipline is
to gitignore/delete such files, and eval raw rows quoting the private corpus are
kept git-ignored (`REPORT.md`).

---

## Evaluation

**Q27. What does "eval == ship" actually guarantee, and where does it stop?**
It guarantees the eval's retrieval and generation are the production functions —
`build_rag_pipeline`, `RAG_PROMPT`, a `RagConfig` derived from
`global_rag_config` — so the headline number reflects the deployed default. It
stops at two honest gaps (manual §9): hybrid/BM25 (→ 00 §7) is measured in eval
but is a dead no-op in prod (no corpus passed), and chat memory has **no**
quantitative eval coverage yet.

**Q28. Tell me the v6/v7 lineage and how it led to today's defaults.**
v6 was the de-leaked benchmark run (canonical, PDF-backed); v7 was a targeted local
eval showcasing rerank/HyDE/rewrite but bypassing the production pipeline (raw
sentence-transformers, pool=50, clean corpora). The 2026-07-02 audit showed v7
didn't cover the live regime, so a real-substrate ablation (one variable changed
per arm, → 00 §12) was built (`evaluation/live_pdf_eval/`) — 83 judged questions
over the actual guide PDF — and *that* set today's defaults:
`chunking_strategy="by_title"` (§4), `retrieval_top_k=10`, `rerank_fetch_k=50`
(reranking, → 00 §6) (REPORT.md, config comments `config.py:28-62`).

**Q29. What was the single biggest quality win and how big was it?**
Chunk hygiene (→ 00 §4). The live corpus was 1,778 element-level fragments (median
67 chars) because the legacy `RecursiveCharacterTextSplitter` splits but never
merges (audit F1). Switching to `by_title` (merged section-sized chunks, ~440
chars, 0.000 boilerplate) gave **+18.6 points** judged correctness (→ 00 §12)
alone (REPORT.md, arm A1); bge-small (→ 00 §5) added +1.2 more (A2, the winner at
0.855 vs 0.657 baseline).

**Q30. Why keep reranking and query-rewrite on if hygiene did most of the work?**
Because the judged arms say so, not intuition. A2 (rerank on, → 00 §6) beat A4
(rerank off) end-to-end 0.855 vs 0.837 — the phase-1 page-recall edge for
dense-only did *not* survive judged evaluation (a proxy-metric trap, → 00 §12). Rewrite was marginal here (+0.006 on standalone
questions) but is retained for the conversational `/ask` path, where v7 showed its
real value (+0.41 recall@5 on follow-ups) (REPORT.md "Winners").

**Q31. What are the honest limits of your eval?**
Questions and judge are both LLMs (gpt-4o) — no human qrels; the paraphrase
constraint and independent review pass mitigate lexical leakage but don't replace
human labels. It's a single corpus, single domain, so the +19.8 headline shouldn't
be quoted as general — only the *direction* (hygiene ≫ embedder > rerank/rewrite)
should transfer (REPORT.md "Honest caveats").

**Q32. How do you turn an eval result into a shipped default?**
Pre-state a decision rule (highest judged correctness, ties → simpler/cheaper),
run the grid, and the winning arm's flags **become** the `config.py` defaults. The
current defaults carry provenance comments pointing back to the arm that set them
(`config.py:28-39`), so the config file itself records why each number is what it
is.

---

## Operations

**Q33. What are the indexer's operational invariants?**
Run exactly **one** scheduler instance (taskiq requirement — two schedulers double
every tick); index lag is *masked*, not fatal (un-indexed messages ride verbatim
in tier 1 — doubly bounded: at most `chat_context_cap` messages AND
`chat_context_char_budget` characters (a char budget works because tokens track
character count closely, → 00 §1), newest first, so even an insane backlog of
huge messages cannot blow the prompt); and the advisory lock guards concurrency
across the two default worker processes. Retries are `retry_on_error=True, max_retries=3` immediate attempts,
with the next cron tick as the durable fallback (`chat_tasks.py:21`, manual §8).

**Q34. A user says "@ai gave a wrong answer." Walk me through debugging it,
step by step.**
(1) Get the `request_id` from the user's timeframe by grepping the app log for the
`ask.trace` digest line. (2) Reproduce offline: `PYTHONPATH=src uv run python
scripts/debug_ask.py <channel> "<question>"` — it prints config-in-effect, tier-1
tail, tier-2 file+chat candidates, the exact prompt, and the answer from the same
`RagTrace`. (3) Read the trace: empty `file_candidates` → nothing ingested or wrong
`workspace_id`; empty `chat_candidates` → still in tier-1 or indexer lagging; wrong
chunks → a chunking/embedder issue; check `config_provenance` for a
workspace/channel override changing behavior. (4) Confirm the exact prompt actually
contains the context — if the answer contradicts good context, it's a prompt/model
issue, not retrieval.

**Q35. `/ask` returns 502. What does it mean and where do you look?**
Retrieval failed *before* streaming — Milvus down, rewriter LLM down, or bad
collection. It's a real error, not a broken stream, precisely because `prepare()`
runs before any bytes are sent. Grep the log for `ask retrieval failed` with that
`request_id` (`router.py:193`).

**Q36. The chat indexer "does nothing" — how do you diagnose?**
Look for the log line `chat indexer lock held elsewhere` — another run holds the
lock, or a leaked lock (check `pg_locks` for key `0x7A105C47`). If there's no
lock message and no work, messages may all be within the grace window
(`chat_index_grace_seconds`, default 300s) and simply not settled yet.

**Q37. You changed the embedding model against a populated collection and get a
dimension error — what happened and what's the fix?**
`_assert_collection_dim` (`vector_store.py:119-137`) probed the configured
embedder, found its dim ≠ the live collection's, and failed fast — doing its job of
catching a lost `EMBEDDING_PROVIDER` env before it silently returns garbage
neighbors (dimension is a contract, → 00 §2). Fix: either restore the matching
env, or re-ingest the collection (`scripts/reingest_workspace_files.py` +
`UPDATE messages SET indexed_at = NULL`).

**Q38. How does a re-ingest actually run given the file claim-gate?**
`process_file` claims a file by flipping UPLOADED/FAILED → UPLOADED and no-ops any
other status (including INDEXED). `reingest_workspace_files.py` flips each target
file's status back to UPLOADED (committed) right before calling `process_file`, so
re-ingestion actually runs; `process_document`'s own per-file purge keeps it
idempotent even if run twice — the same at-least-once discipline as any queued
task (`reingest_workspace_files.py:13-26`, → 00 §13).

---

## Tradeoffs / YAGNI — what you deliberately did NOT build

**Q39. Why no dedicated trace database or OpenTelemetry?**
The trace is filled once per run and read by three surfaces that already agree
(debug flag, `debug_ask.py`, the `ask.trace` log digest) — one schema, no drift
(`trace.py`, manual §10). A trace DB or OTel pipeline would add infra and a second
source of truth for observability that a grep-by-`request_id` over the app log
already provides at this scale. It's a real option for later, not a present need.

**Q40. Why not cache resolved configs, or make indexer knobs per-workspace?**
Config resolution is one indexed read of at most two rows per request
(`resolve_ai_config`, `ai_settings.py:112-117`) — caching would add invalidation
complexity to save microseconds, and would risk serving a stale override after a
PATCH. Per-workspace indexer knobs are refused on principle: there is one indexer
and one collection, so per-tenant cadence/segmentation would be an illusion (Q24).
Also deliberately skipped from the research: reply-graph/thread-aware selection
(every academic quality claim was refuted in adversarial verification) and
knowledge-graph memory (Zep/Graphiti — real but disproportionate infra, uneven
gains). The consistent YAGNI test: does the added complexity buy a *measured* win
this system's scale and tenancy model actually need? If not, it waits.

---

## Concept warm-ups (from 00-foundations)

Five examiner-style questions on the ideas underneath the code, not the code
itself. If any answer feels shaky, reread the cited section before the defense —
these are the ones an examiner reaches for when they want to know you understand
*why*, not just *what*.

**W1. Why retrieval-augmented generation instead of fine-tuning the model or just
using a bigger one (→ 00 §1)?**
An LLM only knows its frozen training data plus whatever is in the prompt right
now — it has never seen your workspace's PDFs — and when the prompt lacks the
answer it hallucinates fluently rather than admitting it doesn't know. Fine-tuning
or a bigger model doesn't fix either problem: the model still isn't reading your
current documents. RAG fixes both by controlling *what's in the prompt* — retrieve
the relevant passages, paste them in, then instruct the model to answer from that
context.

**W2. What's the difference between a bi-encoder and a cross-encoder, and why do
we fetch 50 candidates but only keep 10 (→ 00 §6)?**
A bi-encoder embeds the query and each passage *independently*, so passages can be
pre-embedded and search is fast — but the model never sees query and passage
together, so it misses fine-grained interactions. A cross-encoder reads the pair
together and scores it far more accurately, but it's too slow to run over a whole
corpus. Fetching 50 with the cheap bi-encoder and rescoring down to 10 with the
cross-encoder gets both: speed at scale, accuracy at the end — and it only works
if the true answer is actually inside that pool of 50 (the burial problem).

**W3. Why bge over MiniLM, and why does the query instruction exist (→ 00
§2/§5)?**
MiniLM is trained for general sentence similarity ("do these two sentences say the
same thing"); bge is trained specifically for retrieval ("would this passage
*answer* this question") — a different, asymmetric relation. Because bge is
asymmetric, the query side needs an instruction prefix ("Represent this sentence
for searching relevant passages: ") to land in the same space as the passages it's
supposed to match. Forget the prefix and nothing errors — retrieval quality just
silently degrades, which is exactly the kind of bug that's invisible until you eval.

**W4. Chunking (`by_title`) beat the embedder swap 18.6 points to 1.2 in the
ablation. What's the general lesson (→ 00 §4/§5/§12)?**
Garbage chunks poison every downstream stage — a better embedder just encodes the
same noisy fragments more precisely, it can't manufacture answer material that
isn't there. `by_title` fixed *what the vectors represent* (section-sized,
single-topic chunks instead of 67-char fragments); the embedder swap only
improved *how* those representations were computed. Fix the representation before
upgrading the computation — the ablation's one-variable-at-a-time design is what
let us attribute the two effects separately instead of crediting a bundle.

**W5. Page-recall went up while answers got worse — why did that proxy metric
mislead, and why didn't judged correctness (→ 00 §12)?**
Page-recall only asks "did any retrieved chunk come from a gold page" — fragment
chunking produces many tiny chunks per page, so it's easy to hit the page by
accident even while returning boilerplate or noise as the actual chunk content.
Judged correctness is end-to-end: a strong LLM judge scores the *answer* against
gold material, so it catches failures anywhere in the funnel, including "the right
page was touched but no usable material reached the prompt." The lesson: optimize
the metric that matches the real goal, and treat any proxy metric's disagreement
with the end-to-end metric as a warning, not a tiebreaker.
