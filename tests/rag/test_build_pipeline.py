"""Task 3 — build_rag_pipeline is the single shared retrieval composition.
Proves the two toggle-lies are fixed: reranking widens the candidate pool
(fetch rerank_fetch_k, return retrieval_top_k) and hybrid can no longer be a
silent no-op."""

import pytest
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.cross_encoders.base import BaseCrossEncoder

from config import RagConfig
import rag.retrieval.retrievers as retrievers
from rag.retrieval.retrievers import build_rag_pipeline

CORPUS = [Document(page_content=f"doc {i} about topic {i}", metadata={"id": i}) for i in range(30)]


class _FakeCE(BaseCrossEncoder):
    """Structural stub so tests don't load the 10s HuggingFace cross-encoder."""

    def score(self, text_pairs):
        return [0.0 for _ in text_pairs]


@pytest.fixture(autouse=True)
def _fast_cross_encoder(monkeypatch):
    monkeypatch.setattr(retrievers, "_get_cross_encoder", lambda: _FakeCE())


def _store():
    return InMemoryVectorStore.from_documents(CORPUS, DeterministicFakeEmbedding(size=32))


def test_rerank_widens_then_narrows():
    cfg = RagConfig(use_reranking=True, retrieval_top_k=5, rerank_fetch_k=20)
    r = build_rag_pipeline(cfg, _store())
    # dense stage fetches the wide pool; reranker narrows to top_k
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


def test_hybrid_without_corpus_warns_and_falls_back(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(retrievers.logger, "warning",
                        lambda msg, *a, **k: warnings.append(msg))
    cfg = RagConfig(use_hybrid_retrieval=True, use_reranking=False)
    r = build_rag_pipeline(cfg, _store())
    assert not isinstance(r, EnsembleRetriever)
    assert any("hybrid" in w.lower() for w in warnings)


def test_search_kwargs_merge_into_dense():
    cfg = RagConfig(use_reranking=False, use_hybrid_retrieval=False, retrieval_top_k=5)
    r = build_rag_pipeline(cfg, _store(), search_kwargs={"expr": 'source == "file"'})
    assert r.search_kwargs["expr"] == 'source == "file"'
    assert r.search_kwargs["k"] == 5
