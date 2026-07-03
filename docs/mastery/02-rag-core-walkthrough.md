# 02 — RAG Core Walkthrough

This is the chapter you read when you need to explain, defend, or edit the runtime
of your RAG system by yourself. Every claim below is grounded in the code at
`src/rag/`. Line references are to the files as they stand on
`feature/chat-message-memory`.

Read the files in this dependency order, because each one leans on the ones above it:

1. `message_text.py` — turns a stored message into plain text (leaf, no deps).
2. `generation.py` — builds the LLM (leaf).
3. `vector_store.py` — embeddings + Milvus plumbing (the ORM bridge lives here).
4. `retrieval/compression.py` — the last stage of the pipeline.
5. `retrieval/query_processing.py` — query rewriter + HyDE.
6. `retrieval/chat_selection.py` — the chat re-ranking math.
7. `retrieval/retrievers.py` — `build_rag_pipeline`, which assembles 4/5/6.
8. `trace.py` — the observability record.
9. `rag_chain.py` — `RAGChain`, which wires everything into a query.
10. `router.py` — the `/ask` HTTP endpoint that drives `RAGChain`.

The two big ideas that make the whole thing hang together:

- **Two-tier chat context.** A channel's conversation is split by the
  `Message.indexed_at` column. Tier 1 is the *un-indexed tail* (recent messages,
  `indexed_at IS NULL`) injected verbatim as chat history. Tier 2 is the
  *indexed body* recalled semantically from Milvus. Every message is in exactly
  one tier, so nothing is double-counted and nothing is lost.
- **Prepare/stream split.** Retrieval (which can fail) runs *before* any HTTP
  bytes are sent, so failures become a clean 502. Generation (streaming tokens)
  runs after, once the response is already committed to 200.

---

## `src/rag/message_text.py`

**Job in one sentence:** convert `Message.content` into a plain string, isolating
the one place that has to change when messages stop being plain strings.

**Read it in this order:** `message_text` (the public entry), then `_node_text`
(the recursive helper it may call).

### `message_text(message)` — lines 24–32
Reads `message.content` defensively with `getattr(..., None)` (line 25). Three
branches:
- `None` → `""` (line 27).
- `str` → return it unchanged (lines 28–29). This is the only path that runs today.
- `dict` → delegate to `_node_text` (lines 30–31), the ProseMirror path.
- anything else → `str(content)` fallback (line 32).

### `_node_text(node)` — lines 12–21
A recursive walk over a ProseMirror JSON document:
- `type == "text"` → the node's `text` (lines 14–15).
- `type == "mention"` → `@label` from `attrs`, or `""` if unlabeled (lines 16–18).
- anything else → recurse into `content` children, joining with `"\n"` only when
  the node is the top-level `doc` (block separation), else `""` (lines 19–21).

**Why it's written this way:** the module docstring (lines 1–7) is the whole
rationale — today content is a `str`, but a "rich-msg" branch will switch it to a
ProseMirror JSONB document. By centralizing extraction here, when rich messages
land you review *one* file, not every indexer and router call site. The `dict`
branch already exists so the migration is a data change, not a code change.

**Gotcha:** if you change the shape of a stored message, this is the seam to
update. Both `router.py` (`_load_unindexed_tail`) and the chat indexer call
`message_text`, so a bug here silently corrupts both the tail and the embeddings.

---

## `src/rag/generation.py`

**Job in one sentence:** build the chat LLM from a `RagConfig`.

### `get_llm(provider, streaming, config)` — lines 8–21
- `streaming` defaults to `config.llm_streaming` when not passed (lines 10–11).
- `openai` → a `ChatOpenAI` built from `config.openai_model`,
  `config.llm_temperature`, `streaming`, and `config.openai_api_key` (lines 13–19).
- any other provider → `ValueError` (line 21).

**Why:** everything about the model comes from the passed `config`, never from a
global read inside the function. That is what lets per-workspace/per-channel
overrides (`resolve_ai_config`, chapter 03) actually change the model — you pass a
copied config and this function honours it. The default `config=global_rag_config`
(line 9) is only the fallback for callers that don't override.

**Gotcha:** if you add a second provider, add it here *and* widen
`ai_model_allow_list` / the allow-list validator, or admins still can't select it.

---

## `src/rag/vector_store.py`

**Job in one sentence:** own every Milvus interaction — construct cached
embedders, hand back vectorstores, and delete vectors — plus install the one
monkeypatch that makes LangChain's Milvus client cooperate with the pymilvus ORM.

**Read it in this order:** the ORM bridge (`_link_milvus_client_orm`,
`_install_milvus_client_orm_bridge`, and its call at line 53), then the embedding
builders (`_hf_embeddings_for`, `_build_embeddings`, `get_embeddings`), then the
dimension guard (`_assert_collection_dim`), then the vectorstore getters
(`get_vectorstore`, `get_workspace_vectorstore`), then the delete helpers.

### The MilvusClient ORM bridge — lines 15–53
This is the single most surprising thing in the file, so understand it well.

`langchain_milvus.Milvus` talks to the server through a **MilvusClient**, but it
reads collection *schema* through the older pymilvus **ORM `Collection` API**.
Those two APIs keep *separate connection registries*. When LangChain opens a
MilvusClient connection under some alias, the ORM side knows nothing about that
alias, so `Collection(name, using=alias)` raises `"should create connection
first"` (docstring, lines 16–22).

- `_link_milvus_client_orm(client)` (lines 15–35): copies the client's live
  handler into the ORM's private `connections._alias_handlers` under the client's
  alias (`client._using`, `client._handler`), and clones the `default` alias
  config (or synthesizes one from `milvus_host`/`milvus_port`) so the ORM has both
  a handler and config for that alias. Idempotent: returns early if the alias is
  already registered (lines 25–26).
- `_install_milvus_client_orm_bridge()` (lines 38–51): monkeypatches
  `MilvusClient.__init__` so *every* client, at construction, links itself into
  the ORM registry. It stamps `_talos_orm_bridge = True` on the patched function
  (line 49) and checks that flag first (lines 41–42) so re-imports don't wrap the
  wrapper (double-patching).
- Line 53 runs the install at import time. Because `vector_store` is imported
  whenever RAG is used, the bridge is always in place before any Milvus call.

**Why it exists:** the docstring's last sentence (lines 22–23) is the tell — this
path *had no live caller on main* until the `/ask` endpoint and the chat indexer
started reading schema via the ORM (that is what `_assert_collection_dim` and
`get_workspace_vectorstore` do). The feature surfaced a latent incompatibility;
this bridge is the fix.

**Gotcha:** this reaches into pymilvus *private* attributes (`_using`,
`_handler`, `_alias_handlers`, `_alias_config`). A pymilvus upgrade can rename any
of them and this breaks silently at first use with "should create connection
first". If you ever see that error after a dependency bump, look here first.

### `_ensure_milvus_connection()` — lines 74–82
Lazily opens the ORM `default` alias connection once per process, guarded by the
module-global `_milvus_connected` flag. Every ORM-touching function calls it first.

### Embeddings — lines 85–143
- `BGE_QUERY_INSTRUCTION` (line 86) is the exact prefix the BAAI bge-en-v1.5 model
  card requires on the *query* side. Omitting it silently degrades retrieval
  quality, which is why it is a named constant, not an inline string.
- `_hf_embeddings_for(model)` (lines 94–103): if the model name contains `"bge-"`,
  build `HuggingFaceBgeEmbeddings` with the query instruction and
  `normalize_embeddings=True`; otherwise a plain `HuggingFaceEmbeddings`. The
  bge class is imported lazily inside `_bge_embeddings_cls` (lines 89–91) to keep
  the community import off the hot path when unused.
- `_build_embeddings(provider, model, api_key)` (lines 106–116): `@lru_cache`
  keyed on all three args. `openai` → `OpenAIEmbeddings`; `huggingface` →
  `_hf_embeddings_for`; else `ValueError`. The cache is the point: constructing a
  HuggingFace sentence-transformer loads the model from disk and costs ~3.5s
  (comment, lines 107–109); without the cache you pay that on *every query*.
  Keying on `(provider, model)` means swapping models (via an override) doesn't
  return a stale embedder.
- `get_embeddings(provider, config)` (lines 140–143): the public accessor.
  Resolves provider from config if not passed, extracts the OpenAI secret with
  `.get_secret_value()` (never logs it), and calls `_build_embeddings`.

**Gotcha:** the cache key does *not* include the api_key meaningfully for HF (it's
`None`), and does include it for OpenAI. If two configs share provider+model but
differ only in embedding-affecting kwargs you add later, they'd collide — extend
the key if you add such a knob.

### `_assert_collection_dim(collection_name, provider, model)` — lines 119–137
`@lru_cache` (one probe per process). Ensures the live collection connection
(`_ensure_milvus_connection`), returns early if the collection doesn't exist
(nothing to check). Reads the `vector` field's `dim` from the collection schema
(lines 127–130), embeds a throwaway string to learn the embedder's real dimension
(line 131), and raises a descriptive `RuntimeError` if they disagree (lines
132–137).

**Why:** the classic production failure is that `EMBEDDING_PROVIDER` gets lost
from the environment, config falls back to OpenAI/1536, and you run a 1536-dim
embedder against a 384-dim corpus — every insert/search fails deep inside Milvus
with an opaque error. This turns that into a clear, immediate message telling you
to fix `EMBEDDING_*` or re-ingest (docstring, lines 120–123).

**Gotcha:** it calls `get_embeddings(provider)` positionally (line 131), i.e.
provider-only, using the global config for the model — consistent with how
`get_workspace_vectorstore` passes provider+model separately.

### `get_vectorstore(collection_name, ...)` — lines 146–161
Plain (non-workspace) vectorstore used by the CLI path. Ensures connection, builds
embeddings if not injected, returns a `Milvus` with `auto_id=True` and
`enable_dynamic_field=True` (so metadata fields like `workspace_id`, `source`,
`message_ids` can be filtered on without a fixed schema).

### `get_workspace_vectorstore(collection_name, ...)` — lines 195–222
The product path. Same `Milvus` construction as above, but:
- When it has to build its own embeddings (none injected), it *also* runs
  `_assert_collection_dim` (lines 205–211) — the fail-fast guard fires exactly on
  the code path that would otherwise silently misbehave.
- Passes explicit `connection_args` with host/port (lines 218–221), which is what
  triggers the MilvusClient construction that the ORM bridge hooks.

**Why the dim check is skipped when embeddings are injected:** if the caller hands
in an embedder (e.g. HyDE wrapping base embeddings, or a test double), it owns the
dimension contract; the guard is only for the "we built it from env" case.

`WORKSPACE_COLLECTION` (line 69) is `global_rag_config.milvus_collection_name`.
The comment (lines 66–68) is load-bearing: both the app and the CLI resolve their
collection through this one constant, so they can no longer read different
collections — a bug that had bitten before.

### Delete helpers — lines 225–305
All three ensure connection, no-op if the collection is missing, and build a fresh
`MilvusClient` over HTTP to issue a filtered delete.
- `delete_file_chunks(file_id, workspace_id, ...)` (lines 225–253): deletes by
  `file_id`, optionally *also* scoped to `workspace_id`. The workspace scoping
  (lines 247–248) is a tenant-safety guard: if two tenants ever reused a file_id,
  an unscoped delete would wipe the wrong tenant's rows.
- `delete_message_chunks(message_id, ...)` (lines 256–278): deletes by a single
  `message_id`; used to keep the chat indexer idempotent on retry and to purge a
  deleted message's vectors.
- `delete_chat_segments_for_messages(message_ids, ...)` (lines 281–305): deletes
  every chat *segment* vector that covers **any** of the given message ids. A
  segment bundles several messages, so its metadata stores a `message_ids` array;
  the filter is
  `source == "chat" && json_contains_any(message_ids, [...])` (line 303).
  `json_contains_any` is Milvus's JSON-array-overlap operator — "does this row's
  `message_ids` array share any element with my list". The indexer calls this
  *before* re-ingesting a batch so a crashed previous tick can't leave duplicate
  segment vectors (docstring, lines 285–288). No-ops on an empty list (lines
  289–290) to avoid building a degenerate `json_contains_any(..., [])` filter.

**Gotcha:** `delete_message_chunks` filters on scalar `message_id`; the segment
delete filters on the `message_ids` *array*. They are not interchangeable — chat
memory is stored as segments, so use the array helper for chat cleanup.

---

## `src/rag/retrieval/compression.py`

**Job in one sentence:** optionally wrap a retriever in a context-compression
stage chosen by `config.compression_type`.

### `compression_retriever(base_retriever, compression_type, config)` — lines 16–44
A `match` over `CompressionType`:
- `LLM` → `LLMChainExtractor` (an LLM rewrites each doc down to the relevant part).
- `EMBEDDINGS` → `EmbeddingsFilter` at `config.compression_similarity_threshold`
  (drops docs below the similarity floor).
- `PIPELINE` → embeddings filter *then* LLM extractor, chained in a
  `DocumentCompressorPipeline` (cheap filter first, expensive LLM second).
- `_` (i.e. `NONE`) → return the base retriever untouched (line 40). This is the
  default, so compression is off unless configured.

When a compressor is chosen it's wrapped in `ContextualCompressionRetriever`
(lines 42–43).

**Why:** the LLM, embeddings, and threshold all come from the passed config
(docstring, lines 21–22), so the eval harness can sweep the threshold and ship
exactly what it validated. The comment on the config default (config.py lines
50–53) records that 0.76 was too aggressive for `text-embedding-3-small`.

**Gotcha:** `LLM`/`PIPELINE` add an LLM call per retrieved doc — real latency and
cost. Default `NONE` is deliberate.

---

## `src/rag/retrieval/query_processing.py`

**Job in one sentence:** build the two optional query-expansion helpers — the LLM
query rewriter and the HyDE embedder.

### `get_query_rewriter(config)` — lines 14–16
`QUERY_REWRITE_PROMPT | get_llm(config=config)` — a LangChain runnable that takes
`{"query": ...}` and returns a rewritten string. See chapter 03 for the prompt
text.

### `get_hyde_embeddings(config)` — lines 19–29
Builds a `HypotheticalDocumentEmbedder`: it asks a small, deterministic
`ChatOpenAI` (temperature 0, `max_completion_tokens=150`) to hallucinate a
plausible answer document, then embeds *that* with the base embeddings, using
LangChain's built-in `web_search` prompt (`prompt_key="web_search"`). The idea:
a hypothetical answer sits closer in vector space to real answer passages than the
bare question does.

**Why both are separate builders gated by config:** each is an *extra LLM call per
query* (rewriter) or per query (HyDE generation). `RAGChain.__init__` only
constructs them when `config.use_query_rewrite` / `config.use_hyde` are set, so a
low-VRAM or latency-sensitive deployment turns them off (rag_chain.py lines
96–97). The `TODO` on line 12 notes the rewriter LLM is currently shared with
generation; ideally retrieval and generation would use different models.

---

## `src/rag/retrieval/chat_selection.py`

**Job in one sentence:** re-rank the chat segments Milvus returned by combining
rank-relevance with time-decay, then greedily drop near-duplicates, down to `k`.

**Read it in this order:** the module docstring (the formula in prose), then
`_age_hours`, `_jaccard`, then `select_chat_context`.

### The scoring formula — derived
The docstring (lines 1–8) states it:

```
score = rank_relevance * (floor + (1 - floor) * 0.5^(age_h / half_life))
```

Broken down, matching the code in `select_chat_context` (lines 42–47):
- `relevance = 1.0 / (1.0 + rank)` (line 44). **Rank-based, not distance-based.**
  Milvus returns candidates already sorted by similarity; using their *position*
  (0, 1, 2, …) instead of raw distances makes the score independent of whichever
  distance metric the collection uses (docstring, lines 5–6). Rank 0 → 1.0, rank
  1 → 0.5, rank 2 → 0.33, …
- `decay = 0.5 ** (age_h / half_life)` (line 45). Pure exponential half-life: a
  segment `half_life_hours` old contributes `decay = 0.5`.
- `recency = _DECAY_FLOOR + (1 - _DECAY_FLOOR) * decay` (line 46), with
  `_DECAY_FLOOR = 0.25` (line 15). This rescales decay from the range `[0,1]` into
  `[0.25, 1.0]`. **Why the floor:** without it, a very old segment decays to ≈0
  and can *never* be recalled even if it's the only relevant thing said. The floor
  guarantees an old-but-uniquely-relevant segment keeps at least 25% of its
  relevance weight (docstring, lines 6–7).
- Final `score = relevance * recency` (line 47).

### `_age_hours(doc, now)` — lines 18–24
Reads `sent_at_end` (segment end) or falls back to `sent_at`, parses it as ISO
8601, returns hours elapsed, clamped at 0 (never negative). On a missing or
unparseable stamp it returns `0.0` — i.e. treats it as brand new (no decay),
failing *toward* keeping the segment rather than dropping it.

### `_jaccard(a, b)` — lines 27–30
Standard Jaccard over two token sets: `|a ∩ b| / |a ∪ b|`, with `0.0` for any
empty set.

### `select_chat_context(candidates, *, k, now, half_life_hours, overlap_threshold, stats)` — lines 33–71
1. Score every candidate (lines 42–47), storing `(score, rank, doc)`.
2. Sort by descending score, ties broken by ascending original rank
   (`key=lambda t: (-t[0], t[1])`, line 48) — a stable, deterministic order.
3. Greedy pick (lines 50–61): walk the sorted list; stop once `k` are picked;
   tokenize each candidate (`page_content.lower().split()`); if its Jaccard
   overlap with **any** already-picked segment exceeds `overlap_threshold`, count
   it as redundant and skip; otherwise keep it and remember its tokens.

**The stats contract** (lines 63–70): when a `stats` dict is passed, it's filled
with `considered`, `dropped_redundant`, `kept`, and `truncated`, and the
invariant is documented (line 67–68):

```
considered == dropped_redundant + kept + truncated
```

`truncated` is computed *by subtraction* (`considered - dropped_redundant - kept`,
line 69) — these are the candidates never even examined because the `k`-cap
`break` fired first. This identity is what `_retrieve_chat` relies on to report
selection stats without re-deriving them.

**Gotcha:** if you change the loop to `break` differently, or examine candidates
after reaching `k`, the `truncated` subtraction stops meaning "unvisited" and the
invariant breaks. The stats are computed, not observed, so the code and the
formula must stay in lockstep.

---

## `src/rag/retrieval/retrievers.py`

**Job in one sentence:** the single definition of how Talos retrieves — dense
(±BM25 hybrid) → optional cross-encoder rerank with candidate widening → optional
compression — shared by production and eval so a toggle moves both.

**Read it in this order:** `_get_cross_encoder`, then `build_rag_pipeline` top to
bottom.

### `_get_cross_encoder(model_name)` — lines 28–32
`@lru_cache(maxsize=1)` around `HuggingFaceCrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")`.
Loads the reranker model **once** per process. The comment (lines 30–31) records
the bug this fixes: without the cache, a fresh transformer was instantiated on
*every chat message* — seconds of load time per request.

### `build_rag_pipeline(config, vectorstore, *, corpus, search_kwargs)` — lines 35–85
The stages, gated by config:

1. **Dense stage** (lines 51–58). Candidate breadth is chosen first:
   `dense_k = config.rerank_fetch_k if config.use_reranking else config.retrieval_top_k`
   (line 52). This is the crux of *why reranking helps*: when reranking is on you
   fetch a **wider** pool (`rerank_fetch_k`, default 50) so the cross-encoder can
   promote docs the dense stage ranked below the final `top_k`; when it's off,
   fetching more than `top_k` is wasted work (comment, lines 50–51). Any
   tenancy/file filter arrives via `search_kwargs` and is merged into the base
   search kwargs (lines 54–55) — that's how `RAGChain` injects the
   `workspace_id`/`source`/`file_id` Milvus expression.
2. **Optional BM25 hybrid** (lines 60–73). Only when `use_hybrid_retrieval` *and*
   a `corpus` is supplied: builds a `BM25Retriever` from the corpus and combines
   it 50/50 with dense in an `EnsembleRetriever`. If hybrid is requested but no
   corpus is given (the production Milvus path passes none), it logs a warning and
   falls back to dense-only (lines 68–72). **This is why hybrid is effectively an
   eval-only feature today** — production has no in-memory corpus to BM25 over.
3. **Optional rerank** (lines 75–81). When `use_reranking`, wrap the base
   retriever in a `ContextualCompressionRetriever` whose compressor is a
   `CrossEncoderReranker` with `top_n=config.retrieval_top_k` — i.e. it narrows the
   wide candidate pool back down to the final top_k.
4. **Optional compression** (lines 83–84). Always the outermost wrap, delegating
   to `compression_retriever` (default `NONE` → pass-through).

**Why this function exists at all:** the docstring (lines 42–48) — it's the *one*
definition of retrieval, shared by `RAGChain` (Milvus-backed) and the eval
`RagVariant` (in-memory). Change a toggle here and both move together, so what the
eval measures is what production ships.

**Gotcha:** `use_reranking` and `rerank_fetch_k` are coupled. If you turn
reranking off but leave `rerank_fetch_k` high expecting a wider pool, you get
nothing — the wider fetch only happens *because* reranking is on (line 52).
Conversely, turning reranking on without a `rerank_fetch_k > retrieval_top_k`
means the cross-encoder just reorders the same top_k, gaining little.

---

## `src/rag/trace.py`

**Job in one sentence:** one dataclass, `RagTrace`, that records everything a
single RAG run actually used, filled once by `RAGChain` and read identically by
the `/ask` debug flag, `scripts/debug_ask.py`, and the eval harness.

### `RagTrace` fields — lines 18–33, and who fills/reads each
Every field is written in `RAGChain._fill_trace` (rag_chain.py lines 203–220) and
read by the three consumers named in the docstring (lines 13–15).

| Field | Filled from | Meaning / who reads |
|---|---|---|
| `model` (18) | `config.openai_model` | the generation model; logged in `ask.trace` |
| `embedding_provider` (19) | `config.embedding_provider` | which embedder ran |
| `request_id` (20) | `self.request_id` | correlation id from `/ask` (uuid7) |
| `retrieval_ms` (21) | `self._retrieval_ms` (timed in `prepare`) | rounded to 0.1ms |
| `generation_ms` (22) | `self._generation_ms` (timed in `stream_answer`) | rounded |
| `effective_config` (23) | every `OVERRIDABLE` key + hybrid/compression | the resolved knobs actually used |
| `config_provenance` (24) | `self.config_provenance` | per-key origin: global/workspace/channel |
| `original_query` (25) | the user's raw question | |
| `rewritten_query` (26) | `last_query_info["rewritten_query"]` | `None` when rewrite off |
| `hyde_used` (27) | `self.hyde is not None` | was HyDE active |
| `file_candidates` (28) | `doc_summary` of `retrieved_docs` | file chunks retrieved (drives citations) |
| `chat_candidates` (29) | `doc_summary` of `last_chat_docs` | tier-2 chat segments recalled |
| `chat_selection` (30) | `self.last_chat_selection` | fetched/dropped/kept counts |
| `injected_tail_size` (31) | `len(self._injected_history)` | tier-1 tail size |
| `final_context` (32) | `self.last_context` | the exact context string sent to the LLM |
| `prompt` (33) | rendered `RAG_PROMPT` messages | the exact prompt, for reproduction |

### `doc_summary(doc)` — lines 35–38
A static method returning `{"metadata": dict(doc.metadata), "snippet": first 240
chars}` — a compact, JSON-safe view so a full trace can be dumped without shipping
whole documents.

### `as_dict()` — lines 40–41
`dataclasses.asdict(self)` — used by the `/ask` debug payload
(`chain.trace.as_dict()`, router.py line 226), serialized with `default=str` to
survive non-JSON types.

**Why one dataclass:** the docstring (lines 11–16) — observability had been
ad-hoc reach-ins into chain internals; now there is one source of truth that three
different tools consume the same way.

**Gotcha:** `effective_config` is built from `OVERRIDABLE` (the whitelist) *plus*
two extra keys tacked on in `_fill_trace` (`use_hybrid_retrieval`,
`compression_type`, lines 201–202). If you add a knob you want to see in traces,
add it to `OVERRIDABLE` or to those two lines — otherwise it's used but invisible.

---

## `src/rag/rag_chain.py`

**Job in one sentence:** `RAGChain` wires config → embeddings → retrievers →
LLM, then answers a question in a retrieve-then-generate split, capturing a full
`RagTrace`.

**Read it in this order:** `PreparedAsk` (the handoff object), `__init__`
(wiring), `prepare` and `stream_answer` (the split, and why), then the retrieval
internals `_rewrite_and_retrieve` and `_retrieve_chat`, then `_fill_trace`, then
the thin wrappers `query` / `stream_query`.

### `PreparedAsk` — lines 22–27
A dataclass holding what retrieval produced: `question`, `context` (the formatted
doc string), and `history` (the injected tier-1 tail). It is the boundary object
between the two halves — `prepare` returns it, `stream_answer` consumes it.

### `__init__` — lines 32–126
Signature notes: `config` defaults to `global_rag_config`; the keyword-only
block after `*` (lines 41–46) is the **injected-test seam** plus observability
inputs (`retriever`, `chat_retriever`, `llm`, `request_id`, `config_provenance`).

Wiring, in order:
- Stashes scope and identity: `collection_name`, `config`, a *copy* of
  `config_provenance` (line 60, so the caller's dict can't mutate under you),
  `workspace_id`, `request_id` (defaults to `""`), `file_ids`, `chatroom_id`
  (lines 58–66).
- Initializes timing accumulators and observability capture fields:
  `_retrieval_ms`, `_generation_ms`, `retrieved_docs`, and the debug captures
  `last_context`, `last_chat_docs`, `last_chat_selection` (lines 63–72). The
  comment (line 69) notes the `/ask` debug flag reads these.
- `self.trace = RagTrace()` (line 74) — an empty trace, replaced per run.
- `_injected_history` (line 78): the tier-1 tail the caller loaded, copied into a
  list. This is injected into the prompt's `chat_history` slot; the indexed body
  (tier 2) is recalled separately via `chat_retriever` (comment, lines 75–77).
- `_exclude_message_ids` (line 83): the "B5" dedupe set. A message can *briefly*
  live in both tiers — its vector is in Milvus before its `indexed_at` commit
  lands — so these ids are dropped from tier-2 recall to keep every message in
  exactly one tier (comment, lines 79–82).

Then the **two construction paths** (lines 87–124):
- **Injected path** (`retriever is not None`, lines 87–93): sets
  `query_rewriter`, `hyde`, `vectorstore` all to `None` and uses the passed
  `retriever`. This is the embedding-free/test path — the chain runs with no
  Milvus, no LLM building, no model downloads.
- **Real path** (lines 94–124):
  - Builds `query_rewriter`/`hyde` **only if** their config flags are set (lines
    96–97) — each is an extra LLM call per query.
  - **Workspace path** (`workspace_id` set, lines 99–117): the product path.
    - File vectorstore is `get_workspace_vectorstore(embeddings=self.hyde)` —
      note it retrieves with HyDE embeddings when HyDE is on.
    - Tenancy expression is built as a list of Milvus predicates (lines 103–106):
      `workspace_id == "..."` and `source == "file"` always; plus
      `file_id in [...]` when `file_ids` is given. The `source == "file"` clause
      is what keeps chat-memory vectors out of file retrieval in the shared
      `talos_documents` collection (comment, lines 101–102). Joined with `&&` into
      `extra_search_kwargs = {"expr": ...}` (line 107).
    - **Chat retriever** (`chatroom_id` set, lines 112–117): a *separate*
      retriever over the same collection, filtered to
      `chatroom_id == "..." && source == "chat"`, fetching `chat_recall_fetch_k`.
      Crucially it uses **base embeddings, not HyDE** (line 113): hypothetical-
      document expansion is tuned for corpus QA, not conversational recall
      (comment, lines 109–111).
  - **CLI path** (no `workspace_id`, lines 118–120): plain `get_vectorstore`, no
    tenancy expr.
  - `self.retriever = build_rag_pipeline(config, vectorstore, search_kwargs=extra_search_kwargs)`
    (lines 122–124) — the file pipeline, tenancy filter injected.
- `self.llm` (line 126): injected `llm` or `get_llm(config=config)`.

**Gotcha:** the file retriever and chat retriever are deliberately different
objects with different embeddings and different filters. If you "simplify" them to
share one retriever, you either leak chat vectors into file results or embed
conversation with the wrong model.

### `prepare(question)` — lines 228–250
The **retrieval half**, run eagerly.
- Resets `last_query_info` (lines 233–239).
- Times `_rewrite_and_retrieve` → `_format_docs`, storing `_retrieval_ms` (lines
  240–243).
- Records retrieved-doc bookkeeping and returns a `PreparedAsk` carrying the
  question, formatted context, and a *copy* of the injected history (lines
  244–250).

**Why it raises instead of swallowing:** the docstring (lines 229–232) is the
whole design point. `prepare` runs *before* any HTTP response is committed, so a
Milvus outage or a rewrite-LLM failure raises here and the HTTP layer can turn it
into a real 502 — *before* any bytes stream. Contrast this with generation, which
can only fail *after* the response is already 200.

### `stream_answer(prepared, include_citations)` — lines 252–272
The **generation half**.
- Renders `RAG_PROMPT` with the prepared context/question/history (lines 257–261).
- Streams tokens from `self.llm | StrOutputParser()`, yielding each chunk, timing
  the whole stream into `_generation_ms` (lines 262–265).
- **After** the answer completes, calls `_fill_trace` (line 267) — the trace is
  only complete once generation timing is known.
- If `include_citations`, yields a `"\n\nSources:"` footer and one line per
  `format_citations(self.retrieved_docs)` entry (lines 269–272). Note citations
  come from **file** docs only (`retrieved_docs`), never chat segments.

### The prepare/stream split — WHY
This is the single most important design decision in the file. Retrieval is
fallible and must fail *loudly and early* (→ 502 before headers). Generation is a
long stream that, once started, has already sent a 200; a failure there can only
be signalled *inside* the stream (the `[ask:error]` marker in the router). Keeping
them as two methods lets the router run `prepare` on a worker thread inside a
`try/except → 502`, then stream `stream_answer` separately. `stream_query` (below)
re-fuses them for callers that don't need the split.

### `_rewrite_and_retrieve(question)` — lines 128–142
- If a rewriter exists, invoke it and normalize its output to a stripped string
  (handling the list-content case, lines 129–132); else use the raw question and
  skip the extra LLM call (lines 133–134).
- Store the rewritten query, retrieve **file** docs into `self.retrieved_docs`
  (which drives citations, line 139), retrieve **chat** docs via `_retrieve_chat`,
  capture them, and return `docs + chat_docs` so the context sees files *and*
  channel memory (lines 136–142).

### `_retrieve_chat(query)` — lines 144–184
Channel-scoped tier-2 recall. The **degradation guard** is the theme: it must
*never* error the answer.
- No chat retriever → `[]` (lines 149–150).
- Otherwise, inside a `try` (lines 151–178):
  - `invoke` the chat retriever; record `fetched` count.
  - **Tail-dedupe** (lines 154–162): if `_exclude_message_ids` is non-empty, drop
    any doc whose messages overlap the injected tail. `_overlaps_tail` reads the
    segment's `message_ids` array, falling back to a legacy single `message_id`
    (lines 156–160). `dropped_tail` = how many were removed. This is the other
    half of the "exactly one tier" guarantee — the tail is injected verbatim, so
    its messages must not *also* appear in recall.
  - `select_chat_context` (lines 164–171) applies the re-rank + redundancy math,
    passing a `sel_stats` dict to capture counts.
  - Records `last_chat_selection` with fetched/dropped_tail/dropped_redundant/
    truncated/kept (lines 172–178).
- On **any** exception (lines 179–183): log a warning with `exc_info`, clear
  `last_chat_selection`, and return `[]` — degrade to file-only context. The
  docstring (lines 145–148) explains why it logs rather than swallowing silently:
  a real misconfig (missing collection, dim mismatch) would otherwise masquerade
  as an innocent "no memory," hiding the bug.

**Gotcha:** the degradation is intentional and total — a broken chat corpus still
returns a file-only answer. If you want chat failures to be fatal, this is the
method to change, but you'd lose graceful degradation.

### `_format_docs(docs)` — lines 187–189
Joins `page_content` with blank lines, stores it in `last_context`, returns it.
(The `TODO` on line 186 wants this templated.)

### `_fill_trace(question, history_at_prompt)` — lines 191–220
Builds the exact prompt string by formatting `RAG_PROMPT` with the *same* context,
question, and the history the chain actually saw (`history_at_prompt` is captured
before the turn is recorded — docstring, lines 192–193). Assembles `effective`
from every `OVERRIDABLE` key plus hybrid/compression (lines 200–202), then
constructs a fresh `RagTrace` from all the captured fields (lines 203–220). See
the trace table above for the full field map.

### `query` / `stream_query` — lines 222–226, 274–278
- `stream_query(question, include_citations)` (lines 274–278): the back-compat
  wrapper — `prepare` then `yield from stream_answer` in one sync generator. Used
  by `query()`, the eval harness, and `scripts/debug_ask.py`.
- `query(question, include_citations)` (lines 222–226): drains `stream_query` into
  a single string. The non-streaming convenience path.

### `ingest_documents(file_paths)` — lines 280–284
Async: load documents via `load_documents` and `add_documents` them to the
vectorstore. The CLI ingestion path; unused by `/ask`.

### Owner self-test — RAG core
1. **Why does retrieval run in `prepare` and generation in `stream_answer`, as
   two methods?** So retrieval failures raise *before* the HTTP response is
   committed and become a clean 502; once generation starts the response is
   already 200 and can only signal failure inside the stream.
2. **A message just got indexed but is still in the un-indexed tail. Why doesn't
   it show up twice in the context?** `__init__` receives its id in
   `_exclude_message_ids`; `_retrieve_chat`'s tail-dedupe (`_overlaps_tail`) drops
   any recalled segment covering a tail message, so it stays in tier 1 only.
3. **Why does the chat retriever use base embeddings while the file retriever uses
   HyDE?** HyDE (hypothetical-document expansion) is tuned for corpus QA, not
   conversational recall, so chat memory embeds/searches with the base model.
4. **The chat collection is misconfigured and every recall throws. What does the
   user see?** A normal, file-only answer — `_retrieve_chat` catches, logs a
   warning with `exc_info`, and returns `[]`. The failure is visible in logs, not
   to the user.
5. **You turned reranking off but recall got worse. Why?** With `use_reranking`
   False, `build_rag_pipeline` fetches only `retrieval_top_k` (not
   `rerank_fetch_k`), so the wide candidate pool that reranking depended on is
   gone.

---

## `src/rag/router.py`

**Job in one sentence:** the authenticated, streaming `/ask` HTTP endpoint —
resolve config, run retrieval off the event loop, stream generation, then persist
and broadcast the exchange.

**Read it in this order:** the module docstring + marker constants, `AskRequest`,
then the three helpers `_load_unindexed_tail`, `_persist_exchange`,
`_broadcast_ai_message`, then the endpoint `ask_question` (which orchestrates all
three).

### Module docstring + markers — lines 1–51
The docstring (lines 1–12) states the mount point and the two-tier context model.
Three marker constants matter because a client parses the raw text stream on them:
- `_CITATION_MARKER = "\n\nSources:"` (line 45): matches the footer
  `stream_answer` appends; kept **out** of the stored assistant content so the next
  turn's history isn't polluted with citation text.
- `_DEBUG_MARKER = "\n\n__ASK_DEBUG__\n"` (line 48): precedes the JSON debug
  payload when `debug=True`, so the client can split it off.
- `_ERROR_MARKER = "\n\n[ask:error]"` (line 51): appended to an already-200 stream
  when generation dies mid-way, so the client can tell "model finished" from
  "backend died."

### `AskRequest` — lines 54–58
`question` (1–8000 chars), optional `file_ids`, `include_citations` (default True),
`debug` (default False).

### `_load_unindexed_tail(channel_id, cap, char_budget)` — lines 61–117
Loads tier 1 — the channel's un-indexed tail, **doubly bounded**: `cap` limits
the COUNT of messages (SQL `LIMIT`), `char_budget` limits their total LENGTH
(`chat_context_char_budget`, default 16,000 chars ≈ 4k tokens) so a burst of
huge un-indexed messages can't blow the model's context window.
- `cap <= 0` → empty.
- Query: messages where `channel_id` matches, `indexed_at IS NULL`,
  and `role != SYSTEM`, ordered `sent_at DESC`, limited to `cap`. **SYSTEM rows
  (join/leave notices) are skipped — they are not conversation.**
- If the result *fills* the cap, warn that the indexer may be lagging — a full
  tail means messages are aging out of tier 1 faster than tier 2 absorbs them.
- **Budget walk** (lines ~96–108): rows are newest-first; accumulate
  `len(message_text(m))` and stop before the message that would exceed the
  budget. Two deliberate rules: the **newest message is always kept whole**
  (the budget stops accumulation, it never truncates content — never-empty
  guarantee), and a truncation logs a structured warning with kept/dropped
  counts.
- Reverse the *included* rows to chronological order and map each to an
  `AIMessage` (assistant) or `HumanMessage` (everyone else) via `message_text`.
- Returns `(history, tail_ids)` where `tail_ids` contains **only the injected
  messages** — budget-dropped messages are deliberately NOT excluded from
  tier-2 recall, so if their vectors already exist in Milvus they remain
  recallable: dropped context degrades to "recallable", never to "gone".

**Gotchas:** the query orders `DESC` then reverses; if you drop the reverse the
prompt gets the conversation backwards. The `role != SYSTEM` filter must stay or
system notices pollute the model's view. And if you ever add ids of *dropped*
messages to `tail_ids`, you re-open the hole: they'd be excluded from recall
while also absent from the tail — in neither tier.

### `_persist_exchange(channel_id, user_id, question, asked_at, answer)` — lines 120–141
Persists the question + answer together, **only after** a successful stream.
- Creates a `USER` message with `sent_at=asked_at` and an `ASSISTANT` message with
  `sender_id=None` (assistant rows have no sender), adds both, commits, returns
  their ids (lines 109–116).
- **Semantics:** an exchange is recorded *only* when the answer was actually
  delivered — a mid-stream failure or client disconnect persists nothing, so the
  tail never accumulates dangling human turns with no answer (docstring, lines
  96–103).
- **The clock note** (lines 105–108): `asked_at` is the *app server's* clock
  (captured at request start), but the answer's `sent_at` defaults to the *DB
  server's* `now()`. Ordering (question before answer) relies on generation time
  exceeding any clock skew between the two hosts — safe on a same-host deployment,
  a latent risk if you ever split app and DB across clocks.
- It uses the ORM directly rather than `MessageSchema` because that schema requires
  a non-null `sender_id`, which assistant rows violate (docstring, lines 101–103).

### `_broadcast_ai_message(...)` — lines 119–142
Fans the finished answer to everyone in the channel room over Socket.IO. Without
this, a plain HTTP `/ask` stream is visible only to the asker.
- Imports `sio` from the teammate module `chat.realtime` *inside the function*
  (line 127) — the comment marks it "import-only, never modified," respecting the
  ownership boundary.
- Emits a **custom `"ai_message"` event, not the standard chat `"message"` event**
  (lines 128–140), because `MessageSchema`/the message event requires a non-null
  `sender_id` that assistant rows lack (docstring, lines 123–125).
- Wrapped in a bare `try/except` that only warns (lines 126, 141–142):
  **best-effort — a broadcast failure must never fail the request.**

### `ask_question(channel_id, body, session)` — lines ~170–257
The orchestrator. Its flow, in order (the docstring summarizes the intent):

1. **404 resolve**: look up the channel's `workspace_id`; if the
   channel doesn't exist, `404`.
2. **Request id + tier-1 load**: mint a `uuid7` `request_id`; load
   the un-indexed tail (`history`, `tail_ids`) doubly bounded by
   `global_rag_config.chat_context_cap` (count) and
   `chat_context_char_budget` (length); capture `asked_at` at request start;
   resolve `user_id` from the session.
3. **`_build_and_prepare` on a worker thread** (lines 168–191). Inside a
   `def` run via `asyncio.to_thread`:
   - Open a **sync** `SessionLocal` and `resolve_ai_config(workspace_id,
     channel_id, db)` to get the effective config + provenance (lines 173–176).
   - Construct the `RAGChain` with all scope, the tier-1 `history`, the
     `exclude_message_ids=tail_ids`, and `request_id` (lines 177–187).
   - Return `(chain, chain.prepare(body.question))` (line 188).
   - **Why a thread:** on the first request per process, construction loads the
     embedding model and cross-encoder (cached afterward), which would otherwise
     block the event loop for seconds (comment, lines 169–172). `prepare` (the
     retrieval, which also does LLM rewrite/HyDE) is kept off the loop *together*
     with construction.
4. **502 on retrieval failure** (lines 190–194): the whole `to_thread` is wrapped;
   any exception logs and becomes `HTTPException(502, "retrieval failed")` —
   this is exactly the "fail before any bytes" contract `prepare` was designed for.
5. **Threadpool streaming** (lines 196–206): the inner `stream()` async generator
   drives `chain.stream_answer(...)` through `iterate_in_threadpool`, so the
   blocking LLM/token work runs in a threadpool and never blocks the event loop.
   Each chunk is appended to `parts` and yielded.
6. **`[ask:error]` on mid-stream failure** (lines 203–206): if generation throws
   *after* the response is already 200, log and yield `_ERROR_MARKER`, then
   return — the client sees the marker and knows the backend died mid-answer.
7. **Persist** (lines 207–210): join the collected `parts`, strip everything from
   `_CITATION_MARKER` on (so only the model answer is stored), strip whitespace;
   if non-empty, `_persist_exchange` records the exchange.
8. **Broadcast** (line 211): `_broadcast_ai_message` fans it out.
9. **Trace log** (lines 212–223): pull `chain.trace` and log an `ask.trace` line
   with model, candidate counts, timings, and answer length — structured
   observability keyed by `request_id`.
10. **Debug tail** (lines 224–230): if `body.debug`, log an `ask.debug` summary and
    stream `_DEBUG_MARKER + json.dumps(chain.trace.as_dict(), default=str)` after
    the answer, so a debug client gets the full trace inline.
11. Returns a `StreamingResponse` of `stream()` as `text/plain` (line 232).

**Gotcha — ordering of persist vs. citations:** persistence strips the citation
footer using the *same* `_CITATION_MARKER` string the chain appends. If those two
strings ever drift apart, citation text leaks into stored history and pollutes the
next turn's tail. They must stay identical.

**Gotcha — the two DB session styles:** `_build_and_prepare` uses the *sync*
`SessionLocal` (because it runs in a thread and calls sync `resolve_ai_config`),
while the tail load and persist use the *async* `AsyncSessionLocal`. Don't
cross-wire them.

### Owner self-test — /ask router
1. **What makes an `/ask` exchange get persisted?** Only a fully-delivered answer:
   `_persist_exchange` runs after the stream completes and only if the stripped
   answer is non-empty. A mid-stream error or disconnect persists nothing.
2. **Why is `RAGChain` built inside `asyncio.to_thread`, not on the event loop?**
   First-request construction loads the embedding model and cross-encoder (seconds
   of blocking work); `prepare`'s retrieval also blocks. Threading it keeps the
   event loop responsive.
3. **A retrieval failure vs. a generation failure — what does the client get?**
   Retrieval failure → HTTP `502` before any bytes. Generation failure → a 200
   stream that ends with the `\n\n[ask:error]` marker.
4. **Why is the finished answer sent as a custom `ai_message` Socket.IO event
   instead of a normal chat message?** Assistant rows have `sender_id = NULL`, but
   the standard message event / `MessageSchema` require a non-null sender.
5. **Why does `_load_unindexed_tail` filter out `SYSTEM` rows and order DESC then
   reverse?** SYSTEM rows are join/leave notices, not conversation. The query
   takes the newest `cap` messages (DESC + limit), then reverses them to feed the
   prompt in chronological order.
