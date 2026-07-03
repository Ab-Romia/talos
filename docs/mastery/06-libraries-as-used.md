# 06 — Libraries As We Actually Use Them

This is not library documentation. It is a record of how *we* wired each dependency
into `src/rag/` (and the two teammate seams we depend on: `src/chat/`, `src/database.py`,
`src/broker.py`). Every claim cites `file:line` in this repo (branch
`feature/chat-message-memory`), verified by reading the line. Versions are pinned in
`uv.lock` (not `pyproject.toml`, which only floors them):

| package | pinned version | uv.lock |
|---|---|---|
| langchain-core | 1.4.0 | |
| langchain | 1.3.2 | |
| langchain-classic | 1.0.7 | |
| langchain-community | 0.4.2 | |
| langchain-milvus | 0.3.3 | |
| langchain-huggingface | 1.2.2 | |
| pymilvus | 2.6.12 | |
| sentence-transformers | 5.5.1 | |
| transformers | 5.3.0 | |
| huggingface-hub | 1.5.0 | |
| pydantic | 2.13.4 | |
| pydantic-settings | 2.14.1 | |
| taskiq | 0.12.4 | |
| taskiq-redis | 1.2.2 | |
| s3fs / fsspec | 2023.6.0 / 2023.6.0 | |
| python-socketio | 5.16.2 | |
| sqlalchemy | 2.1.0b2 | |
| fastapi | 0.136.3 | |
| starlette | 1.2.1 | |

---

## langchain-core: Documents, retrievers, prompts, streaming — and the deleted chain

**`Document` is our universal chunk unit.** File chunks and chat-memory segments are
both `langchain_core.documents.Document`; retrieval always returns a `list[Document]`
regardless of source (`source == "file"` vs `source == "chat"` in metadata —
`src/rag/rag_chain.py:101-117`).

**`BaseRetriever` is our composition point, not `VectorStore` directly.**
`build_rag_pipeline()` (`src/rag/retrieval/retrievers.py:35-85`) is "the single
definition of how Talos retrieves" (its own docstring, `:42-49`) — it wraps a
`vectorstore.as_retriever(...)` in zero or more `BaseRetriever` decorators
(`EnsembleRetriever` for BM25 hybrid, `ContextualCompressionRetriever` for rerank,
`ContextualCompressionRetriever` again for LLM/embeddings compression via
`compression_retriever()`, `src/rag/retrieval/compression.py:16-44`). Both `RAGChain`
(Milvus-backed) and the eval harness (`InMemoryVectorStore`-backed) call this same
function, so a retrieval-behavior change moves both call sites at once — that shared
seam is deliberate (`retrievers.py:42-44`).

**`ChatPromptTemplate` + `MessagesPlaceholder` carry conversation history.**
`RAG_PROMPT` (`src/config/prompts.py:19-33`) has a `system` message templated on
`{context}`, a `MessagesPlaceholder(variable_name="chat_history")`, then `("human",
"{question}")`. `chat_history` is filled from `PreparedAsk.history`
(`rag_chain.py:257-261`), which is the un-indexed tail loaded by the router
(`src/rag/router.py:85-92`) — **not** LangChain memory; see below.

**`StrOutputParser` + `.stream()` is our only generation path.**
`stream_answer()` does `for chunk in (self.llm | StrOutputParser()).stream(prompt_value):
yield chunk` (`rag_chain.py:262-264`). No `.invoke()` path exists for the live `/ask`
endpoint — `query()` (`rag_chain.py:222-226`) just drains `stream_query()` into a string,
kept for callers (evals, scripts) that want a blocking call.

**The deleted `RunnableParallel` chain, and why.** Before the 2026-07-02
`ask-hardening-and-smart-context` plan, `RAGChain` built one `self.chain` LCEL pipeline
— retrieval and generation composed into a single `Runnable` (a `RunnableParallel`
assembling context + question, piped into the prompt, LLM, and parser). The plan's
Task 3 explicitly deletes that construction ("the existing `self.chain` construction
DELETED — the `RunnableParallel` block ... is no longer needed",
`docs/superpowers/plans/2026-07-02-ask-hardening-and-smart-context.md:228` area, goal
statement at `:6`) and replaces it with the current **explicit two-phase split**:
- `prepare(question) -> PreparedAsk` — synchronous, does query rewrite + HyDE-aware
  retrieval + chat recall + context formatting, and **raises** on failure
  (`rag_chain.py:228-250`).
- `stream_answer(prepared) -> Generator[str]` — synchronous generator, LLM-only
  (`rag_chain.py:252-265`).

The reason lives in `rag/router.py`'s docstring and comments: a single opaque
`RunnableParallel` chain interleaves retrieval and generation inside one `.stream()`
call, so a Milvus or rewrite-LLM failure surfaces **mid-stream**, after the HTTP
`StreamingResponse` has already sent status 200 and headers. Splitting `prepare()` out
lets the router run it via `asyncio.to_thread` and turn any exception into a real `502`
*before* `StreamingResponse` starts (`router.py:190-194`, comment at `:150-152`
"Retrieval runs eagerly ... so Milvus/rewrite failures become a real 502 before any
bytes stream"). `stream_query()` is kept only as a "back-compat wrapper: prepare +
stream in one sync generator (used by `query()`, the eval harness, and
`scripts/debug_ask.py`)" (`rag_chain.py:274-278`) — external callers (eval, mcp-server
branch) still call the old `.query()`/`.stream_query()` shape and never see the split.

### Self-test Q&A
- **Q: Why doesn't `/ask` use one LCEL chain anymore?**
  A: An interleaved chain can only fail mid-stream, after `StreamingResponse` has sent
  200 + headers. `prepare()` runs retrieval eagerly off the event loop and raises before
  any bytes are sent; `stream_answer()` is generation-only. (`rag_chain.py:228-278`,
  `router.py:150-152,190-194`)
- **Q: What guarantees `stream_query()` and `.query()` still work for the mcp-server
  branch and the eval harness?**
  A: They're unchanged thin wrappers over `prepare()` + `stream_answer()`
  (`rag_chain.py:222-226,274-278`); the plan explicitly called out preserving their
  exact signatures for those external callers.
- **Q: Where does chat history actually come from — LangChain memory or something
  else?**
  A: `self._injected_history` set from the router's un-indexed-tail load
  (`rag_chain.py:78,249`), not any `ConversationBufferMemory`-style object — that path
  was deleted in the same hardening pass (see the pydantic/model_copy section for the
  parallel dead-config cleanup).
- **Q: Do file retrieval and chat-memory retrieval share a retriever object?**
  A: No — `self.retriever` (files, via `build_rag_pipeline`) and `self.chat_retriever`
  (chat memory, a plain `vectorstore.as_retriever(...)`) are separate; both return
  `Document`s that get concatenated before `_format_docs` (`rag_chain.py:138-142`).

---

## langchain_milvus + pymilvus: dynamic schema, expr grammar, the ORM bridge

**One collection, dynamic schema, source-field discipline.** `WORKSPACE_COLLECTION =
global_rag_config.milvus_collection_name` (`src/rag/vector_store.py:69`, default
`"talos_documents"`, `src/config/config.py:26`) backs **both** file chunks and
chat-memory segments. `get_workspace_vectorstore()` builds a `langchain_milvus.Milvus`
with `enable_dynamic_field=True` (`vector_store.py:213-222`) — there is no fixed schema
beyond the vector field; `workspace_id`, `file_id`, `chatroom_id`, `source`,
`message_ids` etc. are all dynamic scalar fields written per-row. **Source discipline is
the only thing preventing chat vectors from leaking into file search and vice versa**:
file retrieval's expr always conjoins `source == "file"`
(`rag_chain.py:101-103`, comment: "keeps chat-memory vectors out of file retrieval in
the shared talos_documents collection"); chat recall's expr conjoins `source == "chat"`
(`rag_chain.py:114`). This is a convention enforced by every caller building its own
`expr`, not a schema constraint — see the integration map for the known leak risk on
the not-yet-merged `search` branch.

**Milvus expr filter grammar we actually use:**
- Simple equality + AND: `f'workspace_id == "{workspace_id}"'`, joined with `" && "`
  (`rag_chain.py:103-107`, `vector_store.py:246-248`).
- `in [...]` list membership for `file_ids` scoping:
  `f"file_id in [{ids_csv}]"` where `ids_csv` is a comma-joined, double-quoted list
  (`rag_chain.py:104-106`).
- `json_contains_any(field, json_array)` for matching against a list-valued dynamic
  field: `delete_chat_segments_for_messages` deletes every chat segment whose
  `message_ids` array contains *any* of a given id list —
  `f'source == "chat" && json_contains_any(message_ids, {ids_json})'`
  (`vector_store.py:300-304`), where `ids_json = json.dumps([str(i) for i in
  message_ids])`. This exists because a segment vector's metadata carries a list of
  message ids (segment, not per-message, granularity — see
  `docs/chat-memory-handoff.md`'s "Segments" section), so purging on message
  edit/delete must match against *any* member of that list, not an exact field value.

**Two separate Milvus client stacks, bridged by a monkeypatch.** `langchain_milvus`
talks to Milvus through a `pymilvus.MilvusClient` (its own connection alias/handler
registry), but our code also reads schema via the **ORM** API (`pymilvus.Collection`,
`pymilvus.connections`) in `_assert_collection_dim` (`vector_store.py:119-137`,
`Collection(collection_name).schema.fields`) and `get_collection_info`
(`vector_store.py:180-192`). These are two independent connection registries in
pymilvus; without a bridge, `Collection(using=alias)` raises "should create connection
first" for any alias only known to the `MilvusClient` side. `_link_milvus_client_orm()`
(`vector_store.py:15-35`) registers a just-constructed `MilvusClient`'s `_handler` under
`connections._alias_handlers[alias]` (and clones or synthesizes
`connections._alias_config[alias]`) so `Collection(using=alias)` can find it.
`_install_milvus_client_orm_bridge()` (`vector_store.py:38-53`) installs this as a
monkeypatch on `MilvusClient.__init__` **at import time** (`vector_store.py:53`, called
unconditionally at module load) — every `MilvusClient(...)` constructed anywhere in the
process, including inside `langchain_milvus.Milvus`, gets bridged automatically. The
patch is idempotent via a `_talos_orm_bridge` marker attribute
(`vector_store.py:41-42`) so re-importing the module doesn't double-wrap. The module's
own docstring is explicit about why: "This path had no live caller on main until the
`/ask` endpoint + chat indexer" (`vector_store.py:21-22`) — i.e. this bridge didn't
matter until this feature branch started reading schema via the ORM.

**Consistency/staleness model: none, deliberately eventual.** There is no explicit
consistency-level configuration anywhere in `vector_store.py` — inserts (via
`Milvus.add_documents`) and deletes (via raw `MilvusClient.delete`) rely on Milvus's
default consistency. Reads immediately after a chat-index tick may not see that tick's
inserts; this is accepted because chat recall already tolerates staleness by design (the
un-indexed tail covers what hasn't been embedded yet — see `router.py`'s two-tier model,
docstring `:6-11`).

**Deletes go through a second, un-bridged `MilvusClient`.** `delete_file_chunks`,
`delete_message_chunks`, `delete_chat_segments_for_messages` each construct their own
`MilvusClient(uri=f"http://{host}:{port}")` (`vector_store.py:242-244,271-273,297-299`)
rather than reusing `get_workspace_vectorstore()`'s embedded client — deletes don't need
an embedder, so a lighter direct client is used. Each of these still benefits from the
import-time monkeypatch since it's installed globally, not per-instance.

### Self-test Q&A
- **Q: Why does `_ensure_milvus_connection` (ORM `connections.connect`) exist alongside
  `langchain_milvus.Milvus`'s own `MilvusClient`?**
  A: They're different registries; `Milvus` never calls `connections.connect` itself.
  `_ensure_milvus_connection()` (`vector_store.py:74-82`) sets up the `"default"` ORM
  alias, used directly by `utility.has_collection`/`Collection(...)` calls that don't go
  through a `MilvusClient` at all (e.g. `clear_collection`, `get_collection_info`).
- **Q: What stops a chat-memory segment from showing up in a file-only retrieval
  answer?**
  A: Purely the `source == "file"` conjunct every file-retrieval expr adds
  (`rag_chain.py:101-103`) — there's no schema-level partition.
- **Q: How would you purge every chat vector touching message ids `[a, b, c]`?**
  A: `client.delete(collection_name=WORKSPACE_COLLECTION, filter='source == "chat" &&
  json_contains_any(message_ids, ["a","b","c"])')` — exactly
  `delete_chat_segments_for_messages` (`vector_store.py:281-304`).
- **Q: If you remove `_install_milvus_client_orm_bridge()`'s call at
  `vector_store.py:53`, what breaks first?**
  A: `_assert_collection_dim` and `get_collection_info`, the first callers that
  construct a `Collection(...)` against an alias only known via a `MilvusClient` —
  they'd hit pymilvus's "should create connection first".

---

## sentence-transformers / HF embeddings + cross-encoder reranker

**Embedding provider selection is config-driven, cached, and model-aware.**
`get_embeddings()` (`vector_store.py:140-143`) resolves `provider`/`model` from
`RagConfig` and delegates to `_build_embeddings()` (`vector_store.py:106-116`), an
`@lru_cache(maxsize=None)` keyed on `(provider, model, api_key)` — the comment explains
why: "constructing the embedder (esp. the HuggingFace sentence-transformer) loads the
model from disk and costs ~3.5s — otherwise paid on every query"
(`vector_store.py:108-110`). For `provider == "huggingface"`, `_hf_embeddings_for(model)`
(`:94-103`) branches on model name: any model containing `"bge-"` gets
`HuggingFaceBgeEmbeddings` with `query_instruction=BGE_QUERY_INSTRUCTION` and
`encode_kwargs={"normalize_embeddings": True}`; everything else gets plain
`HuggingFaceEmbeddings(model_name=model)`.

**The BGE query-instruction lesson is a fixed historical bug, not hypothetical.** The
audit (`docs/audits/2026-07-02-rag-retrieval-quality-findings.md`, F3) found:
"**Code trap found:** `vector_store.py:92-95` hardcodes MiniLM in the huggingface branch
and ignores `config.embedding_model`" — i.e. before the `4f8e4d5` commit, the HF branch
always returned MiniLM regardless of `RagConfig.embedding_model`, so setting
`EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` silently had no effect, and even if honored,
bge-family models need the retrieval-instruction prefix `"Represent this sentence for
searching relevant passages: "` on the **query** side only (per the BAAI model card) or
"retrieval quality silently degrades" (comment, `vector_store.py:95-96`). Both are fixed
in the current `_hf_embeddings_for`/`_build_embeddings` (`vector_store.py:89-116`).

**Dimension mismatch is checked, not assumed.** `_assert_collection_dim()`
(`vector_store.py:119-137`, also `@lru_cache`) reads the live collection's `vector`
field `dim` via the ORM (`Collection(collection_name).schema.fields`), embeds a probe
string with the configured embedder, and raises `RuntimeError` if they disagree —
guarding against "env lost `EMBEDDING_PROVIDER` and fell back to OpenAI/1536 against a
384-dim corpus" (`:121-123`). It's called from `get_workspace_vectorstore()` only when
`embeddings` wasn't injected by the caller (`:205-211`) — HyDE and eval callers that
supply their own `Embeddings` instance skip the check by design.

**Cross-encoder reranker: one process-wide instance.** `CROSS_ENCODER_MODEL =
"cross-encoder/ms-marco-MiniLM-L-6-v2"` (`retrievers.py:25`); `_get_cross_encoder()`
(`:28-32`) is `@lru_cache(maxsize=1)` wrapping `HuggingFaceCrossEncoder(model_name=...)`
— comment: "Without this, a fresh transformer was being instantiated on every chat
message." No explicit device placement call exists in this file (no `.to("cpu")`); HF
defaults to CPU absent CUDA, and the eval/reingest scripts explicitly set
`CUDA_VISIBLE_DEVICES=""` to force CPU when running locally (see remediation plan,
Task 4/5/6 run commands) rather than the library code pinning a device itself.

**Both the embedder cache and the cross-encoder cache are loaded off the event
loop.** `/ask`'s router comments explain why `RAGChain` construction + `prepare()` run
via `asyncio.to_thread`: "on the first request per process it loads the embedding model
and cross-encoder (cached afterwards), which would otherwise block the loop for
seconds" (`router.py:169-172`).

### Self-test Q&A
- **Q: You change `EMBEDDING_MODEL` to a new bge variant but retrieval quality doesn't
  change. What's the first thing to check?**
  A: Whether `_build_embeddings.cache_clear()` was needed — the `lru_cache` is keyed on
  `(provider, model, api_key)`, so a genuinely different model name should get a fresh
  cache entry; if it's the *same* string across a process that already cached it,
  nothing rebuilds. Also check `_assert_collection_dim` didn't fail silently (it only
  raises if the collection exists at all).
- **Q: Why does only the query side get the BGE instruction prefix, not the documents
  we ingest?**
  A: Per the BAAI model card, `bge` models are trained asymmetrically — passages are
  embedded plain, queries get the instruction prefix so the retrieval task is
  represented correctly; `query_instruction=` on `HuggingFaceBgeEmbeddings` only affects
  `embed_query`, not `embed_documents` (`vector_store.py:98-102`).
- **Q: Where's the actual cross-encoder reranking wired into the retrieval pipeline?**
  A: `build_rag_pipeline` wraps the dense/hybrid retriever in a
  `ContextualCompressionRetriever` with `CrossEncoderReranker(model=_get_cross_encoder(),
  top_n=config.retrieval_top_k)` when `config.use_reranking` is true
  (`retrievers.py:75-81`), and widens the candidate pool to `rerank_fetch_k` first
  (`:52-53`) so reranking has something to reorder.
- **Q: Does the cross-encoder run per-request or once at startup?**
  A: Once per process — `_get_cross_encoder()` is `lru_cache(maxsize=1)`, so the first
  `/ask` call in a worker process pays the load cost and every subsequent call reuses
  it (`retrievers.py:28-32`).

---

## pydantic v2 + pydantic-settings

**Two independent `BaseSettings` trees, deliberately.** `Config`
(`src/config/config_.py:124-166`, app/auth/minio/redis/files settings, env-nested via
`env_nested_delimiter="__"`) and `RagConfig` (`src/config/config.py:17-105`, all RAG
knobs) are separate classes — see `MEMORY.md`'s "Two config systems" note, confirmed by
both files' independent `model_config`. `RagConfig.model_config` sets
`env_file=".env", env_file_encoding="utf-8", extra="ignore"` (`config.py:103-105`);
`Config.model_config` sets `env_file='.env', env_nested_delimiter="__", extra="ignore",
yaml_file="config/config.yaml"` (`config_.py:138-143`) plus a custom
`settings_customise_sources` that layers a **test-only YAML override**
(`config/config.test.yaml`, deep-merged) ahead of env vars when `is_pytest()` is true
(`config_.py:145-166`).

**`extra="forbid"` as an intentional whitelist, not a strictness default.**
`AiConfigPatch` (`src/rag/ai_settings.py:55-72`) sets `ConfigDict(extra="forbid")` with
the comment "Whitelisted, bounded overrides. `extra='forbid'` IS the blacklist"
(`:56`). This is the *opposite* posture from `RagConfig`/`Config`'s `extra="ignore"` —
here, any key not explicitly declared on `AiConfigPatch` (workspace-admin-tunable knobs
only: `use_hyde`, `retrieval_top_k`, `openai_model`, etc., `:59-69`) is a hard validation
error, which is exactly what you want for a model that gates untrusted
workspace-admin JSON before it reaches `RagConfig`.

**The `model_copy(update=...)` does-NOT-re-validate lesson — the actual bug this
guards against.** `resolve_ai_config()` builds the effective per-request config as
`global_rag_config.model_copy(update=merged)` (`ai_settings.py:131`) — `model_copy` is a
**shallow copy + attribute overwrite**, not a re-run of pydantic validators. The
module's own docstring states it directly: "Resolution returns a real `RagConfig`
(`model_copy`), so the existing `config=` seam ... stay[s] honest by construction"
(`:4-6`), and `_clean()`'s docstring: "`model_copy(update=...)` does NOT re-validate, so
stale/poisoned rows must never reach the resolved `RagConfig`" (`:80-83`). Concretely:
if a bad value ever landed in the `ai_settings.overrides` JSONB column (e.g. from an
older code version, or hand-edited), `model_copy(update={"retrieval_top_k": "9"})`
would happily set the attribute to the *string* `"9"` with no type coercion or bounds
check — pydantic validators only run at construction (`RagConfig(...)`), not at
`model_copy`. The fix is `_clean()` (`ai_settings.py:79-101`): every override key is
re-validated **per key** by constructing `AiConfigPatch(**{k: v})` (`:91`) before it's
allowed into the merge dict, and the comment at `:97-99` spells out the corollary: store
"the COERCED value, not the raw one ... so e.g. `"9"` must land as `int 9` and `"false"`
as `bool False` — never as truthy strings." `tests/rag/test_ai_settings.py:58` has a test
docstring repeating this exact lesson.

**`@field_validator` gates a live allow-list, not a static enum.**
`AiConfigPatch._model_vetted` (`ai_settings.py:74-79`) checks `openai_model` against
`global_rag_config.ai_model_allow_list` (`config.py:100-101`, comment: "never free
text") at validation time — a model deleted from the allow-list later still gets caught
retroactively by `_clean()`'s per-key re-validation on every read
(`ai_settings.py:82-83`, "a model since removed from the allow-list are dropped per
key").

**Field-level bounds as the real security boundary.** `AiConfigPatch` fields use
`Field(default=None, ge=..., le=...)` (`:60-68`) — e.g. `retrieval_top_k` capped at 50,
`rerank_fetch_k` at 100 — so a workspace admin can tune retrieval depth but not turn it
into a resource-exhaustion vector.

### Self-test Q&A
- **Q: A workspace's `ai_settings.overrides` JSONB has `{"retrieval_top_k": 500}` from
  before the `le=50` bound existed. What happens on the next `/ask` call?**
  A: `resolve_ai_config` → `_clean()` reconstructs `AiConfigPatch(retrieval_top_k=500)`,
  which now fails the `le=50` `Field` constraint, so `ValidationError` is caught and the
  key is dropped with a `logger.warning` (`ai_settings.py:91-95`) — the stale row never
  reaches `model_copy`.
- **Q: Why can't you just re-validate the whole merged dict once instead of per-key?**
  A: The code comment flags this directly: "if a cross-field validator is ever added to
  `AiConfigPatch`, this would miss it" (`ai_settings.py:87-89`) — per-key validation is a
  known, accepted limitation given `AiConfigPatch` currently has no cross-field rules.
- **Q: Why does `RagConfig` use `extra="ignore"` while `AiConfigPatch` uses
  `extra="forbid"`?**
  A: `RagConfig` reads from `.env`/environment, which routinely has unrelated vars
  present — `ignore` avoids spurious failures. `AiConfigPatch` validates
  *user-submitted* JSON from a PATCH endpoint, where any undeclared key is a bug or an
  attack, not noise — `forbid` is the correct posture there.
- **Q: What's the actual mechanism (not just the sentence "model_copy doesn't
  re-validate") that could let a bad type slip through if `_clean()` didn't exist?**
  A: `BaseModel.model_copy(update={...})` sets `__dict__` fields directly via a shallow
  copy, bypassing `__init__`/validators entirely — so `RagConfig(retrieval_top_k=10)
  .model_copy(update={"retrieval_top_k": "not-a-number"})` produces a `RagConfig`
  instance whose `.retrieval_top_k` is the *string* `"not-a-number"`, which downstream
  code (`vectorstore.as_retriever(search_kwargs={"k": dense_k})`,
  `retrievers.py:52-58`) would pass straight to Milvus and likely error far from the
  actual bad input.

---

## taskiq + taskiq-redis: broker, worker, scheduler

**The trio and how they're wired.** `src/broker.py` defines `broker` (module-level
singleton, `:49-59`); `src/scheduler.py` builds a `TaskiqScheduler(broker,
sources=[LabelScheduleSource(broker)])` (`scheduler.py:11-13`) run via `taskiq scheduler
scheduler:scheduler <task-modules> --app-dir=src` (module docstring, `:1-6`); the worker
process is started separately (not a file in `src/rag`, but discovered via task-module
imports) and executes `@broker.task`-decorated functions, e.g. `index_chat_messages`
(`src/processing/chat_tasks.py:21-42`).

**`RedisStreamBroker` + `RedisAsyncResultBackend`, at-least-once semantics.**
`broker.py:50-56` builds `RedisStreamBroker(url=cfg().redis.url)
.with_result_backend(RedisAsyncResultBackend(redis_url=..., result_ex_time=3600))
.with_middlewares(SmartRetryWithCallbackMiddleware())`. Redis Streams give
at-least-once delivery with consumer-group semantics; unacked messages become eligible
for redelivery after an idle timeout (taskiq-redis's `idle_timeout`, not overridden here
— library default applies since no explicit value is passed to `RedisStreamBroker(...)`
at `broker.py:50`). Results expire after 1 hour (`result_ex_time=60*60`, `:53`).

**`InMemoryBroker(await_inplace=True)` swaps in under test.**
`broker.py:61-62`: `if cfg().is_test: broker = InMemoryBroker(await_inplace=True)
.with_middlewares(*broker.middlewares)`. `await_inplace=True` makes `.kiq()` calls
execute the task synchronously in the calling coroutine instead of round-tripping
through Redis — this is what lets tests assert on task side-effects without a running
worker process.

**`LabelScheduleSource` — cron lives on the task decorator, not a separate schedule
file.** `index_chat_messages` is declared with `@broker.task(schedule=[{"cron":
_CRON}], retry_on_error=True, max_retries=3)` (`chat_tasks.py:21`), where `_CRON =
f"*/{max(global_rag_config.chat_index_interval_minutes, 1)} * * * *"` is computed **at
import time** (`:18`) from `RagConfig.chat_index_interval_minutes` (default 5,
`config.py:72`). `LabelScheduleSource(broker)` (`scheduler.py:13`) scans the broker's
registered tasks for the `schedule` label and drives them — so any new
`@broker.task(schedule=[...])` anywhere in an imported task module is picked up
automatically; the scheduler file itself never lists tasks by name.

**The delay label is NOT honored on `RedisStreamBroker` — this is a real, documented
gotcha, not a hypothetical.** The comment in `chat_tasks.py:26-29` states it plainly:
"`retry_on_error` gives transient Milvus/embedding failures 3 immediate retries (the
`RedisStreamBroker` ignores the delay label, so retries are immediate; the next cron
tick remains the durable fallback)." `docs/chat-memory-handoff.md` repeats this: "*there
is no backoff*; a 4th failure waits for the next cron tick." Practical consequence: if
you're debugging why a transient Milvus outage causes 3 rapid-fire retries instead of a
backed-off retry, this is why — and the *actual* backoff mechanism is the next scheduled
cron tick, not taskiq retry delay.

**Batching + backpressure is hand-rolled in the task body, not a taskiq feature.**
`index_chat_messages` loops up to `chat_index_max_batches` times
(`chat_tasks.py:28-38`), each iteration draining `chat_index_batch_size` messages via
`asyncio.to_thread(index_pending_messages, ...)` (blocking DB+Milvus+embedding work kept
off the async worker loop, per the module docstring `:6-8`), and breaks early once a
batch returns fewer than a full page (`:37-38`) — this is a manual burst-drain loop, not
anything taskiq provides.

### Self-test Q&A
- **Q: A chat-index task fails 3 times in a row. When does it retry next?**
  A: Immediately, 3 times in the same tick (no backoff — the delay label is a no-op on
  `RedisStreamBroker`), then it waits for the next scheduled cron tick
  (`chat_tasks.py:26-29`).
- **Q: How does a new scheduled task get picked up by the scheduler without editing
  `scheduler.py`?**
  A: Decorate it with `@broker.task(schedule=[{"cron": "..."}])` in any module the
  scheduler process imports; `LabelScheduleSource(broker)` discovers it by label
  (`scheduler.py:11-13`).
- **Q: Why does `broker.py` swap to `InMemoryBroker` under `IS_TEST`, and what would
  break if it didn't?**
  A: Tests would need a live Redis + worker process to exercise any `.kiq()` call;
  `InMemoryBroker(await_inplace=True)` executes tasks synchronously in-process instead
  (`broker.py:61-62`).
- **Q: Why is `index_pending_messages` wrapped in `asyncio.to_thread` instead of called
  directly from the async task function?**
  A: It does blocking DB + Milvus + embedding-model work; running it directly on the
  async worker's event loop would stall every other task the worker is scheduled to run
  concurrently (`chat_tasks.py:6-8`).

---

## s3fs / fsspec: the MinIO filesystem

*(Owned by the filesystem module, not RAG — documented here because RAG code depends on
its contract via `processing/tasks.py`, `processing/images.py`.)*

**Registration + subclassing.** `MinIOFileSystem(S3FileSystem)`
(`src/filesystem/storage/minio.py:9-25`) sets `protocol = "minio"` and is registered via
`fsspec.register_implementation("minio", MinIOFileSystem)` at **import time**
(`:42`, module-level, unconditional) — so any `fsspec.open("minio://...")` or
equivalent anywhere in the process resolves to this class once the module has been
imported once.

**`split_path` scopes every path to a workspace (and optionally channel).**
`split_path()` (`:27-31`) is an `S3FileSystem` hook that turns a user-facing path into
the actual S3 key; the override prepends `f"{self.bucket}/{self.ws_id}/{self.ch_id or
'.'}/"` before delegating to `super().split_path(...)`. This means a `MinIOFileSystem`
instance is bound to one workspace (and optionally one channel) at construction
(`__init__` takes `workspace_id`, `channel_id`, `:12-14`) — there is no way to escape
that scope through a relative path; every read/write routes through this prefix.

**`asynchronous=True` and the `_url`/`_get_file` async surface.** The constructor passes
`asynchronous=True` to `S3FileSystem.__init__` (`:20`), so this is the async fsspec
variant — methods are coroutines (`_url`, and by extension `_get_file` inherited from
`S3FileSystem`, not overridden here). The one async override present, `_url()`
(`:33-39`), rewrites the presigned URL's host from the internal MinIO endpoint to
`public_endpoint` when configured, so browsers get a reachable URL while server-side
code talks to MinIO over its internal address.

### Self-test Q&A
- **Q: If you construct two `MinIOFileSystem` instances for different `workspace_id`s,
  can one see the other's files through a relative path?**
  A: No — `split_path` hard-prepends `bucket/ws_id/ch_id-or-dot/` before any path is
  resolved (`minio.py:27-31`); there is no shared root.
- **Q: Why does `_url` need overriding instead of just using `S3FileSystem`'s default
  presigned URL?**
  A: MinIO here has two addresses — an internal one the app uses to reach the bucket,
  and a public one browsers use; the override swaps the host after the internal client
  signs the URL (`minio.py:36-38`).
- **Q: What would happen to every `minio://` fsspec call if
  `fsspec.register_implementation` were removed from `minio.py:42`?**
  A: fsspec wouldn't know how to resolve the `"minio"` protocol at all — any
  `fsspec.filesystem("minio", ...)`/`fsspec.open("minio://...")` call would raise.

---

## python-socketio: AsyncServer, rooms, cross-process emit

*(Owned by `src/chat/`; RAG imports `sio` read-only.)*

**Server construction.** `mgr = socketio.AsyncRedisManager(cfg().redis.url,
channel="sio#")` then `sio = socketio.AsyncServer(client_manager=mgr,
async_mode="asgi", logger=False, engineio_logger=False)`
(`src/chat/realtime.py:18-24`). The Redis-backed manager is what lets `sio.emit(...)`
reach clients connected to a *different* uvicorn worker process than the one issuing the
emit — required because `/ask`'s HTTP handler (a different ASGI app/process context than
a socket connection) needs to broadcast to everyone in a channel room.

**Rooms are `"channel:{channel_id}"` strings.** Every RAG-side emit and every
chat-side broadcast use this exact room-naming convention — see
`sio.emit("ai_message", ..., room=f"channel:{channel_id}")`
(`src/rag/router.py:128-140`) and the ordinary chat broadcast
(`realtime.py:172-178`, `room=f"channel:{message.channel_id}"`).

**We only ever import `sio` to emit from an HTTP handler — write-only, never
`sio.on(...)`.** `_broadcast_ai_message()` does `from chat.realtime import sio  #
teammate module: import-only, never modified` (`router.py:127`) then a single
`await sio.emit("ai_message", {...}, room=...)`
(`:128-140`). This is best-effort and isolated: the whole call is wrapped in
`try/except Exception: logger.warning(...)` with the comment "a broadcast failure must
never fail the request" (`:120-123,141-142`) — a Socket.IO/Redis outage degrades the
live room update but never turns a successful `/ask` answer into an HTTP error.

**The `ai_message` event is a custom event, deliberately not the `message` event.**
Comment at `router.py:124-125`: "NOTE: this payload is a custom event, NOT the chat
`message` event — `MessageSchema` requires a non-null `sender_id`, which assistant rows
don't have." (See the integration map for the downstream `GET /messages` bug this
causes.)

### Self-test Q&A
- **Q: Why does `/ask` need `AsyncRedisManager` specifically, not just
  `AsyncServer()`?**
  A: The HTTP `/ask` handler and the Socket.IO connection it's broadcasting to may be
  served by different worker processes; `AsyncRedisManager` fans emits out over Redis
  pub/sub so any process's `sio.emit` reaches sockets connected on any other process
  (`realtime.py:18-19`).
- **Q: What happens to an `/ask` response if the Socket.IO broadcast fails?**
  A: Nothing — `_broadcast_ai_message` swallows the exception and logs a warning; the
  HTTP stream and DB persistence already completed before the broadcast is attempted
  (`router.py:141-142`, called from `stream()` after `_persist_exchange`).
- **Q: Why can't `/ask` just persist an assistant `Message` and let the existing chat
  `message` socket event carry it?**
  A: `MessageSchema.sender_id` is non-optional but assistant rows have `sender_id =
  NULL` by design (there's no "AI user") — reusing the `message` event/schema would
  break validation; hence the separate `ai_message` event with a hand-built payload
  (`router.py:124-142`).

---

## SQLAlchemy sync + async duality

**Two independent engines/sessionmakers, both defined in `src/database.py`.** `engine =
create_engine(cfg().database.url, ...)` (sync, `database.py:14-18`) and `async_engine =
create_async_engine(cfg().database.async_url, ...)` (`:20-24`); `SessionLocal =
sessionmaker(bind=engine, ...)` (`:47`) and `AsyncSessionLocal =
async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False,
...)` (`:48`). Both point at the same Postgres database via
`DatabaseConfig.url`/`.async_url` (`config_.py:106-121`), which differ only in
`protocol`/`async_protocol` (both default to `"postgresql+psycopg"`,
`config_.py:107-108` — psycopg3 supports both sync and async natively).

**RAG's rule of thumb, visible in the code: async in the FastAPI request path, sync
inside a thread.** `rag/router.py`'s `ask_question` endpoint (an `async def`) uses
`AsyncSessionLocal` directly for its own quick reads (`router.py:154-155,
73-81,104-116`), but the moment work needs to run in `asyncio.to_thread` — because it's
blocking (embedding load, Milvus, or just "this needs a *sync* session in a thread that
isn't the event loop") — it opens a **sync** `SessionLocal` instead:
`_build_and_prepare()` does `from database import SessionLocal; with SessionLocal() as
db: resolved, provenance = resolve_ai_config(...)` (`router.py:173-176`), and the whole
closure runs via `asyncio.to_thread(_build_and_prepare)` (`:191`). `resolve_ai_config()`
itself is written against the plain sync `Session` type (`ai_settings.py:104-107,
resolve_ai_config(..., db: Session)`), so it could never be called with an
`AsyncSession` even if you wanted to — it does synchronous `db.execute(...)` calls
(`:117-121`).

**The crash class this avoids: a sync `Session` used directly on the event loop, or an
`AsyncSession` awaited from inside a thread.** Neither actually appears in `src/rag/` —
which is itself the evidence of the discipline: every sync-session use in RAG code is
inside an `asyncio.to_thread(...)` closure (`router.py:168-188`,
`settings_router.py:22-38,41-76` — note the comment at `settings_router.py:24`, "local
import by design: tests monkeypatch `database.SessionLocal`"), and every direct
`AsyncSessionLocal` use is inside an `async def` on the request path, never inside a
thread. Mixing them the other way is the standard SQLAlchemy async footgun: calling a
sync `Session`'s blocking DBAPI methods directly on the event loop blocks every other
coroutine; calling `await` on an `AsyncSession` method from a worker thread (no running
event loop in that thread) raises `RuntimeError: no running event loop` (or silently
deadlocks depending on driver). RAG code sidesteps this by keeping the two session types
segregated by execution context, not by any framework-enforced rule.

### Self-test Q&A
- **Q: `_build_and_prepare()` inside `ask_question` uses `SessionLocal`, not
  `AsyncSessionLocal`, even though it's called from an `async def`. Why is that
  correct?**
  A: Because it's invoked via `asyncio.to_thread(_build_and_prepare)`
  (`router.py:191`) — it executes in a worker thread with no event loop, so it must use
  the sync session; using `AsyncSessionLocal` there would have no event loop to await
  against.
- **Q: `resolve_ai_config` takes a plain `Session`. Could you pass it an
  `AsyncSession`?**
  A: No — it calls `db.execute(...)` synchronously (`ai_settings.py:117-121`); an
  `AsyncSession.execute` returns an unawaited coroutine that would need `await`, and the
  function has no `await`s at all.
- **Q: Why does `ask_question`'s top-level workspace lookup
  (`router.py:154-155`) use `AsyncSessionLocal` instead of also deferring to a thread?**
  A: It's a single cheap `db.scalar(select(...))` directly on the request coroutine —
  no blocking model/Milvus work involved, so there's no reason to pay a thread-hop; the
  thread offload is specifically for the parts that load models or hit Milvus.

---

## FastAPI / Starlette specifics

**`StreamingResponse` over a generator that outlives the request-building code.**
`ask_question` returns `StreamingResponse(stream(), media_type="text/plain;
charset=utf-8")` (`router.py:232`) where `stream()` is a local async generator
(`router.py:196-230`) that: forwards LLM chunks as they arrive, persists the exchange
**after** the stream completes successfully (`:207-211`), and only then attempts the
Socket.IO broadcast (`:211`) and debug payload append (`:224-230`). Because
`StreamingResponse` has already sent a 200 status by the time any of this runs, an error
during generation can't become an HTTP error code — instead the code appends a sentinel
string `_ERROR_MARKER = "\n\n[ask:error]"` to the still-open stream (`:47,205`) so
clients can detect a mid-stream failure by content, not status code. Two other sentinels
follow this same pattern: `_CITATION_MARKER` splits the citation footer off the
persisted answer (`:45,208`), `_DEBUG_MARKER` prefixes an appended JSON debug blob
(`:48,230`).

**`iterate_in_threadpool` bridges `RAGChain`'s sync generator into the async
response.** `chain.stream_answer(...)` is a **synchronous** generator (LLM `.stream()`
calls are sync, `rag_chain.py:263`), but `StreamingResponse` needs an async iterable;
`async for chunk in iterate_in_threadpool(gen):` (`router.py:200`, `gen =
chain.stream_answer(...)`, `:198`) runs each `next(gen)` call in Starlette's threadpool
so the blocking LLM streaming calls never occupy the event loop directly.

**Dependency guards are permission `Depends`, layered by router mount, not
per-endpoint duplication.** `channel = APIRouter(prefix="/channels/{channel_id}",
dependencies=[require_perms("channel:view")])` (`workspace/router.py:16-18`) applies
`channel:view` to every route mounted under it, including `channel_rag_router`
(`:26`); `/ask` then adds only its own incremental permission:
`@ask.post("/ask", dependencies=[require("channel.message:send")])`
(`rag/router.py:145`) — the router docstring states this explicitly: "workspace:view /
channel:view perms already apply; this adds channel.message:send" (`router.py:5`).

### Self-test Q&A
- **Q: An `/ask` client sees a 200 response but the stream ends with
  `"\n\n[ask:error]"`. What actually happened, and would a retry with the same request
  work?**
  A: Generation failed after retrieval succeeded and the stream had already started
  (`router.py:203-206`) — headers were already sent so the failure can't be surfaced as
  a status code. A retry may or may not work depending on whether the underlying LLM
  call is transiently failing; nothing about the failure is persisted (the `if answer:`
  guard at `:209` means a failed generation never calls `_persist_exchange`).
- **Q: Why is `iterate_in_threadpool` necessary here specifically, given `RAGChain`
  already offloads retrieval via `asyncio.to_thread`?**
  A: `asyncio.to_thread` in `_build_and_prepare` covers construction + `prepare()`
  only (`router.py:191`); `stream_answer()` is a separate, later sync generator whose
  `.stream()` calls also block, so it needs its own bridge — `iterate_in_threadpool`
  wraps a sync generator for async iteration, applied at the point it's actually
  consumed (`:198-202`).
- **Q: If `channel.message:send` were somehow declared at the `channel`
  `APIRouter` level instead of on `/ask` itself, what would break?**
  A: Every other route mounted under `channel` (chat send/history/presence, files,
  permissions, ai-config) would also start requiring `channel.message:send`, which is
  too broad — those endpoints have their own distinct permission requirements (see
  `chat/router.py:28,52,69,81`).

