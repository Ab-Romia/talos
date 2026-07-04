"""Task 7 — eval == ship. The eval harness must drive the PRODUCTION
build_rag_pipeline + RAG_PROMPT, not a parallel reimplementation, and its
`production_default` row must mirror the live shipped config."""

import importlib.util
import pathlib
import sys


def _eval_path():
    return pathlib.Path(__file__).resolve().parents[1] / "rag_evaluation" / "eval_utils.py"


def _eval_src():
    return _eval_path().read_text()


def _load_eval_utils():
    name = "eval_utils_under_test"
    spec = importlib.util.spec_from_file_location(name, _eval_path())
    m = importlib.util.module_from_spec(spec)
    # Register before exec: dataclass string-annotation resolution (the module
    # uses `from __future__ import annotations`) looks the module up in sys.modules.
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_no_private_retrieval_reimplementation():
    src = _eval_src()
    assert "build_rag_pipeline" in src
    assert "to_rag_config" in src
    assert "Mirror of" not in src
    assert "def _compression_retriever" not in src
    assert "def _cross_encoder" not in src
    # RagVariant now uses the production RAG_PROMPT, not the memoryless twin.
    assert "RAG_PROMPT_WITHOUT_MEMORY" not in src


def test_production_default_mirrors_shipped_config():
    eu = _load_eval_utils()
    from config import global_rag_config as c
    pd = next(v for v in eu.default_variants() if v.name == "production_default")
    assert pd.use_rewrite == c.use_query_rewrite
    assert pd.use_hyde == c.use_hyde
    assert pd.use_rerank == c.use_reranking
    assert pd.use_hybrid == c.use_hybrid_retrieval


def test_variant_config_maps_to_rag_config():
    eu = _load_eval_utils()
    from config import CompressionType
    vc = eu.VariantConfig(name="t", use_rewrite=True, use_hyde=False, use_rerank=True,
                          use_hybrid=True, compression="embeddings",
                          compression_threshold=0.5, top_k=7)
    rc = vc.to_rag_config()
    assert rc.use_query_rewrite is True
    assert rc.use_reranking is True
    assert rc.use_hybrid_retrieval is True
    assert rc.compression_type == CompressionType.EMBEDDINGS
    assert rc.compression_similarity_threshold == 0.5
    assert rc.retrieval_top_k == 7


def test_ragvariant_builds_retriever_via_production_pipeline(monkeypatch):
    eu = _load_eval_utils()
    from langchain_core.documents import Document
    from langchain_core.embeddings import DeterministicFakeEmbedding
    from langchain_core.messages import AIMessage
    import rag.retrieval.retrievers as prod

    calls = []
    real = prod.build_rag_pipeline

    def spy(cfg, vs, **kw):
        calls.append(kw)
        return real(cfg, vs, **kw)

    monkeypatch.setattr(prod, "build_rag_pipeline", spy)

    chunks = [Document(page_content=f"doc {i}", metadata={"chunk_id": f"a::chunk_{i}"}) for i in range(5)]
    emb = DeterministicFakeEmbedding(size=16)

    class _LLM:
        def invoke(self, _msg):
            return AIMessage(content="ans")

    cfg = eu.VariantConfig(name="t", use_rerank=False)
    eu.RagVariant(cfg, chunks, emb, _LLM())
    assert calls, "RagVariant must build its retriever via production build_rag_pipeline"
    assert calls[0].get("corpus") == chunks
