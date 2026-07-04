"""HF embedder selection: honor config.embedding_model; bge gets query instruction."""
import pytest

import rag.vector_store as vs


class _FakeEmb:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_hf_branch_honors_model_name(monkeypatch):
    captured = {}
    monkeypatch.setattr(vs, "HuggingFaceEmbeddings", lambda **kw: captured.update(kw) or _FakeEmb(**kw))
    vs._build_embeddings.cache_clear()
    vs._build_embeddings("huggingface", "thenlper/gte-small", None)
    assert captured["model_name"] == "thenlper/gte-small"


def test_bge_model_gets_query_instruction(monkeypatch):
    captured = {}

    class _FakeBge(_FakeEmb):
        def __init__(self, **kw):
            captured.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(vs, "_bge_embeddings_cls", lambda: _FakeBge)
    vs._build_embeddings.cache_clear()
    vs._build_embeddings("huggingface", "BAAI/bge-small-en-v1.5", None)
    assert captured["model_name"] == "BAAI/bge-small-en-v1.5"
    assert captured["query_instruction"] == vs.BGE_QUERY_INSTRUCTION
    assert captured["encode_kwargs"] == {"normalize_embeddings": True}


def test_unknown_provider_still_raises():
    vs._build_embeddings.cache_clear()
    with pytest.raises(ValueError):
        vs._build_embeddings("nope", "x", None)
