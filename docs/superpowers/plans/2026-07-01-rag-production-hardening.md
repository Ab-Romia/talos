# RAG Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Talos's production and evaluation RAG onto one configurable, traceable pipeline so "what we evaluate is what we ship."

**Architecture:** Make `RagConfig` a real injected dependency (kill the global-singleton bypass), extract one `build_rag_pipeline(config, vectorstore, corpus=…)` shared by `RAGChain` (Milvus) and eval `RagVariant` (in-memory), attach a structured `RagTrace` per run, unify collections on `talos_documents`, and fix the toggle-breaking bugs so ablations are meaningful.

**Tech Stack:** Python 3.14, LangChain (`langchain_classic`, `langchain_milvus`, `langchain_core`), pydantic-settings, Milvus, pytest. Worktree `/home/romia/talos-main`, branch `feature/chat-message-memory`.

## Global Constraints

- **No teammate code.** Touch only `src/rag/`, `src/processing/`, RAG-only `src/config/` (`config.py`, `prompts.py`, `__init__.py`), `tests/rag_evaluation/`, `scripts/`, `rag_cli.py`. Never `src/config/config_.py`, `src/auth/`, `src/chat/`, `src/workspace/`, `src/filesystem/`.
- **Imports are absolute from `src/`** (e.g. `from config import global_rag_config`). `PYTHONPATH=src` is set by pyproject for pytest.
- **Run tests with** `IS_TEST=1 uv run python -m pytest <path> -q` (NOT bare `uv run pytest` — that hits a stale global). New unit tests must not require Milvus/OpenAI; use fakes/monkeypatch.
- **Commit identity** `Ab-Romia <aabouroumia@gmail.com>`. No AI attribution/co-author footers anywhere.
- Every factory that gains a `config` parameter keeps `global_rag_config` as its default, so existing call sites keep working.
- Design spec: `docs/superpowers/specs/2026-07-01-rag-production-hardening-design.md`.

---

### Task 1: Real config seam through the bypassing factories

**Files:**
- Modify: `src/rag/generation.py` (`get_llm`)
- Modify: `src/rag/retrieval/query_processing.py` (`get_hyde_embeddings`, `get_query_rewriter`)
- Modify: `src/rag/vector_store.py` (`get_embeddings` cache key)
- Modify: `src/config/config.py` (add `rerank_fetch_k`)
- Test: `tests/rag/test_config_seam.py` (create)

**Interfaces:**
- Produces: `get_llm(provider="openai", streaming=None, config=global_rag_config)`, `get_embeddings(provider=None, config=global_rag_config)`, `get_hyde_embeddings(config=global_rag_config)`, `get_query_rewriter(config=global_rag_config)`. All read model/keys from the passed `config`, not the module global.
- Consumes (later tasks): these signatures.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_config_seam.py`:

```python
from config import RagConfig
from rag.generation import get_llm
from rag.vector_store import get_embeddings


def test_get_llm_honors_passed_config_model():
    cfg = RagConfig(openai_model="gpt-4o", openai_api_key="sk-test")
    llm = get_llm(config=cfg)
    assert llm.model_name == "gpt-4o"


def test_get_llm_default_is_global():
    from config import global_rag_config
    llm = get_llm()
    assert llm.model_name == global_rag_config.openai_model


def test_get_embeddings_cache_keyed_on_model():
    cfg_a = RagConfig(embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="sk-test")
    cfg_b = RagConfig(embedding_provider="openai", embedding_model="text-embedding-3-large", openai_api_key="sk-test")
    emb_a = get_embeddings(config=cfg_a)
    emb_b = get_embeddings(config=cfg_b)
    assert emb_a.model != emb_b.model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_config_seam.py -q`
Expected: FAIL (`get_llm() got an unexpected keyword argument 'config'`).

- [ ] **Step 3: Add `rerank_fetch_k` to config**

In `src/config/config.py`, after `retrieval_top_k: int = 5` (line ~29) add:

```python
    # Candidate pool the dense stage fetches BEFORE the cross-encoder reranks
    # down to retrieval_top_k. Widening here is what makes reranking improve
    # recall rather than merely reorder the top_k. Ignored when use_reranking
    # is False.
    rerank_fetch_k: int = 20
```

- [ ] **Step 4: Thread config through `get_llm`**

In `src/rag/generation.py`, replace `get_llm`:

```python
def get_llm(provider: str = "openai", streaming: bool | None = None,
            config: "RagConfig" = global_rag_config):
    if streaming is None:
        streaming = config.llm_streaming
    if provider == "openai":
        return ChatOpenAI(
            model=config.openai_model,
            temperature=config.llm_temperature,
            streaming=streaming,
            api_key=config.openai_api_key,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
```

Add `RagConfig` to the import at the top: `from config import global_rag_config, RagConfig`.

- [ ] **Step 5: Thread config through HyDE + query rewriter (fixes C2)**

In `src/rag/retrieval/query_processing.py`:

```python
def get_query_rewriter(config=global_rag_config):
    llm = get_llm(config=config)
    return QUERY_REWRITE_PROMPT | llm


def get_hyde_embeddings(config=global_rag_config):
    base_embeddings = get_embeddings(config=config)
    hyde_llm = ChatOpenAI(
        model=config.openai_model,          # was hardcoded "gpt-3.5-turbo"
        temperature=0.0,
        max_completion_tokens=150,
        api_key=config.openai_api_key,
    )
    return HypotheticalDocumentEmbedder.from_llm(
        llm=hyde_llm, base_embeddings=base_embeddings, prompt_key="web_search"
    )
```

- [ ] **Step 6: Re-key the embeddings cache on (provider, model)**

In `src/rag/vector_store.py`, replace `get_embeddings`:

```python
@lru_cache(maxsize=None)
def _build_embeddings(provider: str, model: str, api_key: str | None) -> Embeddings:
    if provider == "openai":
        return OpenAIEmbeddings(model=model, api_key=api_key)
    elif provider == "huggingface":
        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    raise ValueError(f"Unknown embedding provider: {provider}")


def get_embeddings(provider: str | None = None, config=global_rag_config) -> Embeddings:
    # Cached by (provider, model): constructing the embedder (esp. the HF
    # sentence-transformer) costs ~3.5s, but two different models must not
    # collide in the cache.
    provider = provider or config.embedding_provider
    key = config.openai_api_key.get_secret_value() if config.openai_api_key else None
    return _build_embeddings(provider, config.embedding_model, key)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_config_seam.py -q`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add src/rag/generation.py src/rag/retrieval/query_processing.py src/rag/vector_store.py src/config/config.py tests/rag/test_config_seam.py
git commit -m "feat(rag): make RagConfig a real injected dependency; HyDE model from config"
```

---

### Task 2: Unify Milvus collections on `talos_documents`

**Files:**
- Modify: `src/config/config.py` (`milvus_collection_name` default)
- Modify: `src/rag/vector_store.py` (`WORKSPACE_COLLECTION` references config)
- Test: `tests/rag/test_collection_unified.py` (create)

**Interfaces:**
- Produces: a single collection name (`talos_documents`) reachable via both `WORKSPACE_COLLECTION` and `global_rag_config.milvus_collection_name`.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_collection_unified.py`:

```python
from config import global_rag_config
from rag.vector_store import WORKSPACE_COLLECTION


def test_collection_name_is_unified():
    assert WORKSPACE_COLLECTION == "talos_documents"
    assert global_rag_config.milvus_collection_name == WORKSPACE_COLLECTION


def test_documents_v2_is_gone():
    import rag.vector_store as vs
    import config.config as cfg
    src = open(vs.__file__).read() + open(cfg.__file__).read()
    assert "documents_v2" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_collection_unified.py -q`
Expected: FAIL (`documents_v2` still present; names differ).

- [ ] **Step 3: Change the config default**

In `src/config/config.py`, change:

```python
    milvus_collection_name: str = "talos_documents"
```

- [ ] **Step 4: Make `WORKSPACE_COLLECTION` the single source of truth**

In `src/rag/vector_store.py`, replace `WORKSPACE_COLLECTION = "talos_documents"` with:

```python
WORKSPACE_COLLECTION = global_rag_config.milvus_collection_name
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_collection_unified.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/config/config.py src/rag/vector_store.py tests/rag/test_collection_unified.py
git commit -m "fix(rag): unify Milvus collection on talos_documents, retire documents_v2"
```

---

### Task 3: `build_rag_pipeline` — one shared composition with rerank widening + honest hybrid

**Files:**
- Modify: `src/rag/retrieval/retrievers.py` (replace `get_retriever` with `build_rag_pipeline`, fold in compression)
- Test: `tests/rag/test_build_pipeline.py` (create)

**Interfaces:**
- Produces: `build_rag_pipeline(config, vectorstore, *, corpus=None, search_kwargs=None) -> BaseRetriever`. Composes dense (+ optional BM25 hybrid when `corpus` given) → optional cross-encoder rerank (dense fetches `rerank_fetch_k`, reranker returns `retrieval_top_k`) → optional compression. Logs a warning if `use_hybrid_retrieval` is set but no `corpus` is provided.
- Consumes: `config.retrieval_top_k`, `config.rerank_fetch_k`, `config.use_hybrid_retrieval`, `config.use_reranking`, `config.compression_type`; `compression_retriever` from `..retrieval.compression`.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_build_pipeline.py`:

```python
import logging
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_classic.retrievers import EnsembleRetriever

from config import RagConfig
from rag.retrieval.retrievers import build_rag_pipeline

CORPUS = [Document(page_content=f"doc {i} about topic {i}", metadata={"id": i}) for i in range(30)]


def _store():
    return InMemoryVectorStore.from_documents(CORPUS, DeterministicFakeEmbedding(size=32))


def test_rerank_widens_then_narrows():
    cfg = RagConfig(use_reranking=True, retrieval_top_k=5, rerank_fetch_k=20)
    r = build_rag_pipeline(cfg, _store())
    # base_retriever under the compression wrapper fetches rerank_fetch_k
    assert r.base_retriever.search_kwargs["k"] == 20
    assert r.base_compressor.top_n == 5


def test_no_rerank_returns_dense_at_top_k():
    cfg = RagConfig(use_reranking=False, use_hybrid_retrieval=False, retrieval_top_k=5)
    r = build_rag_pipeline(cfg, _store())
    assert r.search_kwargs["k"] == 5


def test_hybrid_with_corpus_builds_ensemble():
    cfg = RagConfig(use_hybrid_retrieval=True, use_reranking=False)
    r = build_rag_pipeline(cfg, _store(), corpus=CORPUS)
    assert isinstance(r, EnsembleRetriever)


def test_hybrid_without_corpus_warns_and_falls_back(caplog):
    cfg = RagConfig(use_hybrid_retrieval=True, use_reranking=False)
    with caplog.at_level(logging.WARNING):
        r = build_rag_pipeline(cfg, _store())
    assert not isinstance(r, EnsembleRetriever)
    assert any("hybrid" in rec.message.lower() for rec in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_build_pipeline.py -q`
Expected: FAIL (`cannot import name 'build_rag_pipeline'`).

- [ ] **Step 3: Implement `build_rag_pipeline`**

In `src/rag/retrieval/retrievers.py`, replace `get_retriever` with (keep `_get_cross_encoder` and imports; add the compression import and logger):

```python
from utils.logger import get_logger
from .compression import compression_retriever

logger = get_logger(__name__)

__all__ = ["build_rag_pipeline"]


def build_rag_pipeline(
    config: RagConfig,
    vectorstore: VectorStore,
    *,
    corpus: Iterable[Document] | None = None,
    search_kwargs: dict | None = None,
) -> BaseRetriever:
    """The single definition of how Talos retrieves. Shared by RAGChain
    (Milvus) and the eval RagVariant (in-memory).

    dense (+ optional BM25 hybrid) -> optional cross-encoder rerank with
    candidate widening -> optional compression.
    """
    # When reranking, fetch a wider candidate pool so the cross-encoder can
    # surface docs the dense stage ranked below top_k; otherwise fetch top_k.
    dense_k = config.rerank_fetch_k if config.use_reranking else config.retrieval_top_k
    base_search_kwargs = {"k": dense_k}
    if search_kwargs:
        base_search_kwargs.update(search_kwargs)
    dense_retriever = vectorstore.as_retriever(
        search_type="similarity", search_kwargs=base_search_kwargs
    )

    corpus = list(corpus) if corpus else []
    if config.use_hybrid_retrieval and corpus:
        bm25 = BM25Retriever.from_documents(corpus)
        bm25.k = dense_k
        base_retriever: BaseRetriever = EnsembleRetriever(
            retrievers=[dense_retriever, bm25], weights=[0.5, 0.5]
        )
    else:
        if config.use_hybrid_retrieval and not corpus:
            logger.warning(
                "hybrid retrieval requested but no corpus provided; "
                "falling back to dense-only"
            )
        base_retriever = dense_retriever

    if config.use_reranking:
        compressor = CrossEncoderReranker(
            model=_get_cross_encoder(), top_n=config.retrieval_top_k
        )
        base_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=base_retriever
        )

    return compression_retriever(base_retriever, compression_type=config.compression_type)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_build_pipeline.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/rag/retrieval/retrievers.py tests/rag/test_build_pipeline.py
git commit -m "feat(rag): build_rag_pipeline with rerank widening and honest hybrid"
```

---

### Task 4: `RagTrace` structured trace object

**Files:**
- Create: `src/rag/trace.py`
- Test: `tests/rag/test_trace.py` (create)

**Interfaces:**
- Produces: `RagTrace` dataclass with `as_dict() -> dict`. Fields: `model`, `embedding_provider`, `effective_config: dict`, `original_query`, `rewritten_query`, `hyde_used`, `file_candidates: list[dict]`, `chat_candidates: list[dict]`, `injected_tail_size`, `final_context`, `prompt`. Plus `RagTrace.doc_summary(doc) -> dict` helper.
- Consumes (Task 5): filled by `RAGChain`.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_trace.py`:

```python
from langchain_core.documents import Document
from rag.trace import RagTrace


def test_trace_round_trips():
    t = RagTrace(model="gpt-4o-mini", embedding_provider="openai",
                 effective_config={"use_hyde": False}, original_query="q",
                 rewritten_query="q2", hyde_used=False,
                 file_candidates=[], chat_candidates=[],
                 injected_tail_size=2, final_context="ctx", prompt="p")
    d = t.as_dict()
    assert d["model"] == "gpt-4o-mini"
    assert d["rewritten_query"] == "q2"
    assert d["injected_tail_size"] == 2


def test_doc_summary_extracts_id_and_snippet():
    doc = Document(page_content="hello world " * 50, metadata={"message_id": "m1", "source": "chat"})
    s = RagTrace.doc_summary(doc)
    assert s["metadata"]["message_id"] == "m1"
    assert len(s["snippet"]) <= 240
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_trace.py -q`
Expected: FAIL (`No module named 'rag.trace'`).

- [ ] **Step 3: Implement `RagTrace`**

Create `src/rag/trace.py`:

```python
from dataclasses import dataclass, field, asdict

from langchain_core.documents import Document

__all__ = ["RagTrace"]


@dataclass
class RagTrace:
    """Everything a single RAG run actually used — model, effective config,
    queries, retrieved candidates, final context, and the exact prompt.
    Filled once per run by RAGChain and consumed by /ask debug, debug_ask.py,
    and the eval harness."""

    model: str = ""
    embedding_provider: str = ""
    effective_config: dict = field(default_factory=dict)
    original_query: str = ""
    rewritten_query: str | None = None
    hyde_used: bool = False
    file_candidates: list[dict] = field(default_factory=list)
    chat_candidates: list[dict] = field(default_factory=list)
    injected_tail_size: int = 0
    final_context: str = ""
    prompt: str = ""

    @staticmethod
    def doc_summary(doc: Document) -> dict:
        return {"metadata": dict(doc.metadata), "snippet": doc.page_content[:240]}

    def as_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_trace.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/rag/trace.py tests/rag/test_trace.py
git commit -m "feat(rag): structured RagTrace for observability"
```

---

### Task 5: Rewire `RAGChain` onto the shared pipeline + trace + B4/B6 fixes

**Files:**
- Modify: `src/rag/rag_chain.py`
- Test: `tests/rag/test_rag_chain.py` (create)

**Interfaces:**
- Consumes: `build_rag_pipeline` (Task 3), `RagTrace` (Task 4), `get_llm(config=…)`, `get_query_rewriter(config=…)`, `get_hyde_embeddings(config=…)`, `get_embeddings(config=…)`.
- Produces: `RAGChain.trace: RagTrace` populated after each `stream_query`. `chat_retriever` uses **base** embeddings (no HyDE). Live question no longer double-injected.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_rag_chain.py`:

```python
from unittest.mock import patch
from langchain_core.documents import Document
from config import RagConfig


def _fake_pipeline_docs(monkeypatch_docs):
    class _R:
        def invoke(self, q): return monkeypatch_docs
    return _R()


def test_live_question_not_in_chat_history(monkeypatch):
    # The current question must appear only in the `question` slot, never in
    # chat_history (B4 double-count regression guard).
    from rag import rag_chain as rc

    captured = {}

    class _LLM:
        def stream(self, msgs): 
            captured["msgs"] = msgs
            yield "ok"
    # ... build a RAGChain with stubbed retriever/llm (see harness below) and
    # assert the rendered chat_history contains none of the live question text.


def test_trace_populated_after_query():
    # After stream_query, RAGChain.trace.original_query == question and
    # trace.prompt is non-empty.
    ...
```

> Note for implementer: `RAGChain.__init__` does heavy Milvus/embedding work. Add a test seam — accept optional injected `retriever`, `chat_retriever`, and `llm` in `__init__` (all default `None` → built as today). This keeps unit tests hermetic without Milvus. Write the seam in Step 3, then flesh out the two tests above against it.

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_rag_chain.py -q`
Expected: FAIL (seam/trace absent).

- [ ] **Step 3: Rewire `RAGChain`**

In `src/rag/rag_chain.py`:

1. Import at top: `from .trace import RagTrace`.
2. In `__init__`, replace the retriever assembly (the `get_retriever(...)` + `compression_retriever(...)` block, lines ~80-89) with a single call:

```python
        from rag import build_rag_pipeline
        self.retriever = build_rag_pipeline(
            config, self.vectorstore, search_kwargs=extra_search_kwargs
        )
```

3. Build `chat_retriever` from a **base-embeddings** view (no HyDE) so conversational recall isn't run through hypothetical-document expansion:

```python
            if chatroom_id:
                from rag import get_workspace_vectorstore
                chat_vs = get_workspace_vectorstore(embeddings=get_embeddings(config=config))
                chat_expr = f'chatroom_id == "{chatroom_id}" && source == "chat"'
                self.chat_retriever = chat_vs.as_retriever(
                    search_kwargs={"k": config.chat_recall_k, "expr": chat_expr}
                )
```

4. Add `self.config = config` and `self.trace = RagTrace()` in `__init__`. Accept the test seam: `retriever=None, chat_retriever=None, llm=None` params, and use them when provided (skip the build).

5. In `_retrieve_chat`, log before degrading:

```python
    def _retrieve_chat(self, query: str):
        if not self.chat_retriever:
            return []
        try:
            return self.chat_retriever.invoke(query)
        except Exception:
            logger.warning("chat recall failed; degrading to file-only",
                           chatroom_id=self.chatroom_id, exc_info=True)
            return []
```

(Add `from utils.logger import get_logger; logger = get_logger(__name__)` at module top.)

6. **B4 fix** in `stream_query`: move `self.memory.add_user_message(question)` from before the stream to *after* the stream loop (just before `self.memory.add_ai_message(full_response)`).

7. At the end of `stream_query` (after streaming), fill the trace:

```python
        self.trace = RagTrace(
            model=self.config.openai_model,
            embedding_provider=self.config.embedding_provider,
            effective_config={
                "use_hyde": self.config.use_hyde,
                "use_query_rewrite": self.config.use_query_rewrite,
                "use_reranking": self.config.use_reranking,
                "use_hybrid_retrieval": self.config.use_hybrid_retrieval,
                "compression_type": self.config.compression_type.value,
                "retrieval_top_k": self.config.retrieval_top_k,
                "rerank_fetch_k": self.config.rerank_fetch_k,
            },
            original_query=question,
            rewritten_query=self.last_query_info.get("rewritten_query"),
            hyde_used=self.hyde is not None,
            file_candidates=[RagTrace.doc_summary(d) for d in self.retrieved_docs],
            chat_candidates=[RagTrace.doc_summary(d) for d in self.last_chat_docs],
            injected_tail_size=len(self._injected_history),
            final_context=self.last_context,
            prompt="",  # filled by the router which has the rendered prompt; optional here
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_rag_chain.py -q`
Expected: PASS.

- [ ] **Step 5: Run the chat suite for regressions**

Run: `IS_TEST=1 uv run python -m pytest tests/chat -q`
Expected: PASS (21 tests — no regression).

- [ ] **Step 6: Commit**

```bash
git add src/rag/rag_chain.py tests/rag/test_rag_chain.py
git commit -m "feat(rag): RAGChain on shared pipeline + RagTrace; fix double-count and off-HyDE chat recall"
```

---

### Task 6: `/ask` router — serialize `RagTrace` + B5 tier dedupe

**Files:**
- Modify: `src/rag/router.py`
- Modify: `scripts/debug_ask.py`
- Test: `tests/rag/test_router_dedupe.py` (create)

**Interfaces:**
- Consumes: `RAGChain.trace`, `_load_unindexed_tail`.
- Produces: `_debug_payload` returns `chain.trace.as_dict()` (with `prompt` filled from the rendered prompt). Tier-2 chat docs whose `message_id` is in the tier-1 tail are dropped before display.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_router_dedupe.py`:

```python
from rag.router import _dedupe_chat_against_tail


def test_chat_doc_in_tail_is_dropped():
    tail_ids = {"m1", "m2"}
    chat_docs = [{"message_id": "m1"}, {"message_id": "m3"}]
    kept = _dedupe_chat_against_tail(chat_docs, tail_ids)
    assert [d["message_id"] for d in kept] == ["m3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_router_dedupe.py -q`
Expected: FAIL (`cannot import name '_dedupe_chat_against_tail'`).

- [ ] **Step 3: Implement dedupe + trace serialization**

In `src/rag/router.py`:

1. Add helper:

```python
def _dedupe_chat_against_tail(chat_docs: list[dict], tail_message_ids: set[str]) -> list[dict]:
    """B5: a message can briefly be both in the un-indexed tail (indexed_at
    NULL, not yet committed) and in Milvus chat recall. Drop tier-2 recall for
    any message already in the tier-1 tail so it counts in exactly one tier."""
    return [d for d in chat_docs if d.get("message_id") not in tail_message_ids]
```

2. `_load_unindexed_tail` currently returns `list[BaseMessage]`. Add a sibling that also returns the id set, or capture the ids where the tail is loaded (the `rows` carry `m.id`). Simplest: have `ask_question` load the ids alongside the history and thread them into the debug payload. Keep the history return type unchanged; add `tail_ids: set[str]` as a second loaded value.

3. Replace `_debug_payload` body to build from the trace:

```python
def _debug_payload(chain, history, question: str, tail_ids: set[str]) -> dict:
    from config import RAG_PROMPT
    prompt = "\n\n".join(
        f"[{m.type}] {m.content}"
        for m in RAG_PROMPT.format_messages(
            context=chain.last_context, question=question, chat_history=history)
    )
    d = chain.trace.as_dict()
    d["prompt"] = prompt
    d["chat_candidates"] = _dedupe_chat_against_tail(
        [{"message_id": c["metadata"].get("message_id"), **c} for c in d["chat_candidates"]],
        tail_ids,
    )
    return d
```

(Adjust the `stream()` closure to pass `tail_ids`. The `__ASK_DEBUG__` marker + JSON streaming stays as-is — only the payload source changes.)

- [ ] **Step 4: Update `scripts/debug_ask.py` to print the trace**

Point the script at `chain.trace.as_dict()` after a query instead of re-deriving fields, so it and `/ask` share one source. Keep its existing CLI/formatting.

- [ ] **Step 5: Run tests to verify they pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_router_dedupe.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rag/router.py scripts/debug_ask.py tests/rag/test_router_dedupe.py
git commit -m "feat(rag): /ask serializes RagTrace and dedupes chat recall vs tail"
```

---

### Task 7: Unify the eval harness onto `build_rag_pipeline`

**Files:**
- Modify: `tests/rag_evaluation/eval_utils.py` (`RagVariant`, `default_variants`)
- Modify: `src/config/prompts.py` (remove `RAG_PROMPT_WITHOUT_MEMORY`)
- Test: `tests/rag/test_eval_uses_production_path.py` (create)

**Interfaces:**
- Consumes: `build_rag_pipeline(config, vectorstore, corpus=…)`, `get_llm(config=…)`, `RAG_PROMPT`, `RagConfig`.
- Produces: `RagVariant` that retrieves and generates via the production functions; `VariantConfig` → `RagConfig` translation; `production_default` variant matching real shipped defaults.

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_eval_uses_production_path.py`:

```python
from unittest.mock import patch
from langchain_core.documents import Document
import tests.rag_evaluation.eval_utils as eu  # noqa


def test_ragvariant_calls_build_rag_pipeline():
    with patch("tests.rag_evaluation.eval_utils.build_rag_pipeline") as m:
        # constructing/answering a variant must route through the production
        # pipeline builder, not a private reimplementation
        ...
        assert m.called


def test_no_private_retriever_reimplementation():
    src = open(eu.__file__).read()
    # the mirror comment + local build_retriever must be gone
    assert "Mirror of" not in src
    assert "def build_retriever" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_eval_uses_production_path.py -q`
Expected: FAIL (private reimplementation still present).

- [ ] **Step 3: Rewrite `RagVariant` onto the production path**

In `tests/rag_evaluation/eval_utils.py`:
1. Import: `from rag.retrieval.retrievers import build_rag_pipeline`, `from rag.generation import get_llm`, `from config import RAG_PROMPT, RagConfig`.
2. Add a `VariantConfig.to_rag_config() -> RagConfig` that maps the row's flags (`use_hyde`, `use_rewrite`→`use_query_rewrite`, `use_rerank`→`use_reranking`, `use_hybrid`→`use_hybrid_retrieval`, `compression`, `top_k`→`retrieval_top_k`) onto a `RagConfig`.
3. Delete `build_retriever`, `_hyde_embeddings`, `_compression_retriever` (the mirrors). `RagVariant.__init__` builds `self.retriever = build_rag_pipeline(cfg, in_memory_store, corpus=chunks)`.
4. `RagVariant.answer` renders `RAG_PROMPT` with `chat_history=[]` and calls `get_llm(config=cfg)` — same components as prod. Query rewrite via `get_query_rewriter(config=cfg)` when enabled.
5. Attach `variant.last_trace` per question (reuse `RagTrace.doc_summary`) for error analysis.

- [ ] **Step 4: Remove the unused prompt twin**

In `src/config/prompts.py`, delete `RAG_PROMPT_WITHOUT_MEMORY` (and add `__all__ = ["RAG_PROMPT", "QUERY_REWRITE_PROMPT"]` to stop `import *` leakage).

- [ ] **Step 5: Fix `production_default`**

In `default_variants()`, set the `production_default` row's flags to the real shipped defaults (`use_hyde=True`, `use_query_rewrite=True`, `use_reranking=True`, `use_hybrid=False`, `compression=NONE`) and correct its docstring.

- [ ] **Step 6: Run tests + a fast eval smoke**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_eval_uses_production_path.py -q`
Expected: PASS.
Then a minimal harness import/build smoke (no OpenAI): construct one variant over a tiny in-memory corpus with `use_reranking=False, use_hyde=False, use_query_rewrite=False` and assert `retriever.invoke("q")` returns docs.

- [ ] **Step 7: Commit**

```bash
git add tests/rag_evaluation/eval_utils.py src/config/prompts.py tests/rag/test_eval_uses_production_path.py
git commit -m "feat(eval): drive eval through production build_rag_pipeline + RAG_PROMPT"
```

---

### Task 8: Data-driven defaults + dead-config cleanup + ops notes

**Files:**
- Modify: `src/config/config.py` (set defaults to eval winner)
- Delete: `config/rag_config.example.yaml`, `config/prompts/qa_prompt.yaml`, `config/prompts/query_rewrite_prompt.yaml`, `config/prompts/hyde_prompt.yaml`; remove `RagConfig.yaml_file`
- Create: `docs/rag-ops-notes.md`

- [ ] **Step 1: Run the full ablation harness**

Open `tests/rag_evaluation/rag_evaluation_talos.ipynb` and run the grid (needs `OPENAI_API_KEY`). Record the winning variant by the primary metric (faithfulness + answer-correctness, with recall@5 as tiebreak) and its bootstrap CI vs `production_default`.

- [ ] **Step 2: Set shipped defaults to the winner**

In `src/config/config.py`, set `use_hyde`, `use_query_rewrite`, `use_reranking`, `use_hybrid_retrieval`, `compression_type`, `retrieval_top_k`, `rerank_fetch_k` to the winning variant's values. Add a one-line comment citing the run id/date.

- [ ] **Step 3: Remove dead config**

Delete the dead YAML files and the `yaml_file` field from `RagConfig`. Run: `IS_TEST=1 uv run python -m pytest tests/rag -q` to confirm nothing referenced them.

- [ ] **Step 4: Write ops notes (B3, B7)**

Create `docs/rag-ops-notes.md` documenting: (a) pre-`source` Milvus rows must be re-ingested to appear in file retrieval (B3); (b) `talos_documents` is not namespaced by embedding dimension — never change `embedding_provider`/`embedding_model` against a populated collection without dropping + re-ingesting (B7).

- [ ] **Step 5: Full-suite regression**

Run: `IS_TEST=1 uv run python -m pytest tests/chat tests/rag -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/config/config.py docs/rag-ops-notes.md
git rm config/rag_config.example.yaml config/prompts/qa_prompt.yaml config/prompts/query_rewrite_prompt.yaml config/prompts/hyde_prompt.yaml
git commit -m "chore(rag): eval-driven defaults, remove dead config, add ops notes"
```

---

## Self-Review

**Spec coverage:** C1→Task 1; C2→Task 1 (HyDE model); C3→Task 2; C4→Task 8 (dead config); B1→Task 3 (honest hybrid); B2→Task 3 (widening); B3→Task 8 (ops note); B4→Task 5; B5→Task 6; B6→Task 5; T1→Tasks 4-6; eval unification→Task 7; data-driven defaults→Task 8. All spec sections mapped.

**Type consistency:** `build_rag_pipeline(config, vectorstore, *, corpus, search_kwargs)` used identically in Tasks 3, 5, 7. `RagTrace` fields/`as_dict()`/`doc_summary` consistent across Tasks 4-7. `get_llm/get_embeddings/get_hyde_embeddings/get_query_rewriter(config=…)` signatures consistent Tasks 1, 5, 7.

**Placeholder scan:** Task 5 Step 1 and Task 7 Step 1 contain intentional `...` skeletons with an explicit implementer note (the hermetic test seam must be built in Step 3 before the assertions can be written concretely). All other steps carry complete code.

**Ordering:** 1 (config seam) → 2 (collections) → 3 (pipeline) → 4 (trace) → 5 (RAGChain) → 6 (router) → 7 (eval) → 8 (defaults+cleanup). Each task is independently testable and commits on green.
