# RAG Production Hardening — Design Spec

**Date:** 2026-07-01
**Branch:** `feature/chat-message-memory` (worktree `/home/romia/talos-main`, off `origin/main`)
**Status:** Design — awaiting review before implementation plan.

## Problem

Talos runs **two divergent RAG pipelines**, and the one that is evaluated is not the one that ships.

- **Prod** (`RAGChain`, `src/rag/`): Milvus (`talos_documents`), prompt `RAG_PROMPT` (with memory placeholder), streamed LangChain chain, config from the process-global `global_rag_config` singleton — HyDE **on**, query-rewrite **on**, rerank **on**.
- **Eval** (`tests/rag_evaluation/eval_utils.py`, `RagVariant`): a hand-reimplemented pipeline over an **in-memory** vector store, prompt `RAG_PROMPT_WITHOUT_MEMORY`, non-streamed `llm.invoke`, config from a per-row `VariantConfig` dataclass. It never imports `RAGChain`, `get_retriever`, or Milvus.

The eval variant named `production_default` sets only `use_rerank=True`, while the shipped config also has `use_hyde=True` and `use_query_rewrite=True`. **The headline eval number measures a configuration the product does not run.**

Compounding this, the config seam is decorative and several toggles silently lie (see Findings).

## Goals

1. **One pipeline.** Prod and eval assemble retrieval + generation through the *same* code, so a config/toggle change moves both. (Vector store stays injectable: Milvus in prod, in-memory in eval.)
2. **Real configurability.** HyDE, query-rewrite, rerank, hybrid, compression, model, embeddings, and collection are toggled through one honest config path that actually reaches every component.
3. **Traceability.** A single structured trace object per run, consumed by `/ask` debug, `scripts/debug_ask.py`, and eval alike.
4. **Eval == ship.** After unification, eval picks the shipped defaults: run the harness, set defaults to the winning variant.
5. **Honest toggles.** Fix the correctness bugs that make a toggle a silent no-op (otherwise eval measurements are meaningless).

## Non-goals (explicitly deferred — YAGNI)

- Per-request / per-workspace runtime config override.
- YAML loading for `RagConfig` (env/`.env` is sufficient; the dead `yaml_file`/`rag_config.example.yaml`/`config/prompts/*.yaml` are removed, not wired).
- A Milvus-backed eval mode (eval stays hermetic/in-memory).
- **B7** embedding-dimension namespacing guard → documented as an ops note, not built.

## Constraints

- **No teammate code is touched.** All changes live in our lanes: `src/rag/`, `src/processing/`, the RAG-only parts of `src/config/` (`config.py`, `prompts.py`), `tests/rag_evaluation/`, `scripts/`. `src/config/config_.py` (auth/db/minio), `src/auth/`, `src/chat/`, `src/workspace/` are out of bounds.
- Simplicity over cleverness. The smallest change that achieves the goals.
- The full test suite stays green; new behavior is covered by tests.

## Decisions (confirmed with owner, 2026-07-01)

1. **Shared boundary:** share retriever + generation assembly; keep vector stores separate (eval in-memory, prod Milvus).
2. **Defaults:** data-driven — after unification, run eval and set shipped defaults to the winning variant.
3. **Bug scope:** fix the toggle-breaking bugs (B1, B2, B3, C-collection) + cheap hygiene (B4, B5, B6); defer B7 to an ops note.

## Verified Findings (the work list)

**Config / configurability**
- **C1** `config=` seam is fake: `get_llm`, `get_embeddings`, `get_hyde_embeddings`, `get_query_rewriter` read `global_rag_config` directly (`generation.py:21`, `query_processing.py:53-58`, `vector_store.py:85`). Two configs cannot coexist in one process.
- **C2** HyDE model hardcoded `gpt-3.5-turbo`, ignores `openai_model` (`query_processing.py:54`).
- **C3** Collection split: config default `documents_v2` is CLI-only + a dead fallback; product/ingest/indexer hardcode `talos_documents` (`config.py:27` vs `vector_store.py:65`). In the `workspace_id` path the `collection_name` argument to `RAGChain` is ignored (`rag_chain.py:60`).
- **C4** `RagConfig.yaml_file`, `config/rag_config.example.yaml`, `config/prompts/*.yaml` are dead. Prompts are hardcoded in `prompts.py`; HyDE uses LangChain's built-in `web_search` prompt.

**Correctness (adversarially confirmed)**
- **B1** BM25/hybrid never runs — sole caller passes `documents=[]`, so `use_hybrid_retrieval=True` is a silent no-op (`retrievers.py:44`, `rag_chain.py:80`).
- **B2** Reranking never widens — dense `k = top_k = 5`, reranker `top_n = top_k = 5`; reorders the same 5, never surfaces dense-rank #6+ (`retrievers.py:37,56`).
- **B3** Legacy/keyless Milvus rows silently excluded by the `source == "file"` filter (`rag_chain.py:63`).
- **B4** Current question double-counted — `memory.add_user_message(question)` runs before the chain reads the `chat_history` lambda, so the live question fills both the `chat_history` and `question` slots (`rag_chain.py:157` vs `99-101`).
- **B5** Indexer tier race — a message's vector reaches Milvus (tier-2 recall) before its `indexed_at` commit, so a concurrent `/ask` counts it in both tier-1 tail and tier-2 recall (`chat_indexing.py:104` vs `109`).
- **B6** Chat recall runs through HyDE (semantic mismatch) and `_retrieve_chat` swallows all exceptions as "no memory" (`rag_chain.py:73,130-133`). (Refuted: HyDE does **not** corrupt stored-doc vectors — it is query-only.)
- **B7** (deferred) No collection namespacing by embedding dim — flipping `embedding_provider` between ingest and query → Milvus dim error, unguarded.

**Traceability**
- **T1** Debug data is assembled by reaching into `chain.last_context`/`last_chat_docs`/`last_query_info` in the router and streamed as a `__ASK_DEBUG__` string marker. No structured trace; eval can't reuse it.

## Design

### 1. Real config seam
Thread an explicit `config: RagConfig` parameter through the factories that currently bypass it: `get_llm(config)`, `get_embeddings(config)`, `get_hyde_embeddings(config)`, `get_query_rewriter(config)`. Each defaults to `global_rag_config` for backward compatibility but honors an explicit argument. HyDE reads `config.openai_model` (fixes C2). `get_embeddings` cache key becomes `(provider, model)` so two models in one process don't collide.

### 2. One shared pipeline builder
Extract the retriever composition into a single function used by both prod and eval:

```python
def build_rag_pipeline(
    config: RagConfig,
    vectorstore: VectorStore,
    *,
    corpus: list[Document] | None = None,   # enables BM25/hybrid when provided
    search_kwargs: dict | None = None,       # Milvus expr filters (prod only)
) -> BaseRetriever:
    """Compose dense (+ optional BM25 hybrid) → optional cross-encoder rerank
    (with candidate widening) → optional compression. The single definition of
    'how Talos retrieves', shared by RAGChain (Milvus) and eval RagVariant
    (in-memory)."""
```

- `RAGChain` calls it with the Milvus vectorstore + `search_kwargs` (the `workspace_id`/`source`/`file_id` expr).
- Eval `RagVariant` calls it with its `InMemoryVectorStore` + `corpus` (so hybrid actually works in eval).
- Generation is shared too: both use `RAG_PROMPT` (eval passes `chat_history=[]`) and `get_llm(config)`. Eval reads the full string; prod streams. `RAG_PROMPT_WITHOUT_MEMORY` and its uses are removed.

### 3. Rerank candidate widening (B2)
Add `rerank_fetch_k: int = 20` to `RagConfig`. When reranking, the dense retriever fetches `rerank_fetch_k` and the `CrossEncoderReranker` returns `top_n = retrieval_top_k`. Reranking now improves recall, not just ordering.

### 4. Honest hybrid (B1)
`build_rag_pipeline` builds BM25 only when `use_hybrid_retrieval and corpus`. Prod cannot cheaply feed BM25 the whole Milvus corpus, so prod passes no corpus and, if `use_hybrid_retrieval=True` with no corpus, logs a warning ("hybrid requested but no corpus; dense-only"). Eval passes its corpus, so hybrid is genuinely exercised. Toggle can no longer lie silently.

### 5. Collection unification (C3)
`RagConfig.milvus_collection_name` default becomes `"talos_documents"`; `WORKSPACE_COLLECTION` references it (single source of truth). `documents_v2` is retired. The `workspace_id` path honors an explicitly-passed `collection_name`. CLI and app then read the same collection.

### 6. Structured trace (T1)
A dataclass populated once per run:

```python
@dataclass
class RagTrace:
    model: str
    embedding_provider: str
    effective_config: dict      # the toggles actually used this run
    original_query: str
    rewritten_query: str | None
    hyde_used: bool
    file_candidates: list[dict]  # id/metadata/snippet (+score where available)
    chat_candidates: list[dict]
    injected_tail_size: int
    final_context: str
    prompt: str
```

`RAGChain` fills `self.trace` each run. `/ask` debug serializes `self.trace`; `debug_ask.py` prints it; eval attaches it per question for error analysis. The `__ASK_DEBUG__` stream marker stays (client contract) but its payload is `trace.as_dict()`.

### 7. Correctness hygiene
- **B4:** move `memory.add_user_message(question)` to after the stream (before `add_ai_message`), so the live question isn't double-injected.
- **B5:** the `/ask` router dedupes tier-2 chat recall against the tier-1 tail by `message_id`, guaranteeing "exactly one tier" regardless of the insert-vs-stamp race. (Local to our router; no cross-store transaction needed.)
- **B6:** `chat_retriever` uses **base** embeddings (no HyDE) — hypothetical-document expansion doesn't fit conversational recall; and `_retrieve_chat` logs the exception (with `chatroom_id`) before degrading to `[]`, so misconfig is visible.

### 8. Eval unification + data-driven defaults
- `RagVariant` is rewritten to call `build_rag_pipeline` + `get_llm(config)` + `RAG_PROMPT`, driven by a `RagConfig` built from each `VariantConfig` row (delete the parallel retrieval/HyDE/compression reimplementations).
- `production_default` variant = the *real* shipped config defaults.
- After the harness runs green on the unified path, run the ablation grid and set `RagConfig` defaults to the winning variant. HyDE's default-on question is answered by the data.

## Testing strategy

- **Config seam:** construct two `RagConfig`s (e.g. `use_query_rewrite` on/off, different `openai_model`) in one process and assert the built components differ — proves the singleton bypass is gone.
- **Pipeline builder:** with reranking on, assert the dense stage requests `rerank_fetch_k` candidates and the reranker returns `retrieval_top_k`; with `use_hybrid_retrieval` + a corpus, assert an `EnsembleRetriever` is built; without a corpus, assert dense-only + a warning.
- **Collection:** assert every product path resolves to `talos_documents` and `documents_v2` is gone.
- **Trace:** assert `RAGChain.trace` is populated after a query and round-trips through `as_dict()`.
- **B4:** assert the live question appears once (in the `question` slot, not `chat_history`).
- **B5:** given a message present in both the tail and chat recall, assert the router emits it once.
- **Eval parity:** a spy/monkeypatch test asserting `RagVariant` now calls `build_rag_pipeline` (no private retrieval reimplementation remains).
- Existing `tests/chat` indexer tests and the full suite stay green.

## Risks

- **Eval re-run cost** (data-driven defaults) — one paid OpenAI harness run. Acceptable; it's the point.
- **HyDE without OpenAI** — local runs alias `gpt-3.5-turbo`; with C2 fixed, HyDE uses `config.openai_model`, so the alias hack is no longer needed but stays harmless.
- **Legacy Milvus rows (B3)** — unifying collections doesn't re-key old rows; a re-ingest or a documented migration is still needed for pre-`source` data. Called out as an ops note, not silently assumed.
