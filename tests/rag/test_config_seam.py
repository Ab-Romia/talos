"""Task 1 — prove RagConfig is a real injected dependency, not a decorative
parameter that every factory ignores in favour of the global singleton."""

from config import RagConfig, global_rag_config
from rag.generation import get_llm
from rag.vector_store import get_embeddings


def test_get_llm_honors_passed_config_model():
    cfg = RagConfig(openai_model="gpt-4o", openai_api_key="sk-test")
    llm = get_llm(config=cfg)
    assert llm.model_name == "gpt-4o"


def test_get_llm_default_is_global():
    llm = get_llm()
    assert llm.model_name == global_rag_config.openai_model


def test_get_embeddings_cache_keyed_on_model():
    cfg_a = RagConfig(embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="sk-test")
    cfg_b = RagConfig(embedding_provider="openai", embedding_model="text-embedding-3-large", openai_api_key="sk-test")
    emb_a = get_embeddings(config=cfg_a)
    emb_b = get_embeddings(config=cfg_b)
    assert emb_a.model != emb_b.model


def test_get_hyde_uses_config_model_not_hardcoded(monkeypatch):
    """C2: HyDE must stop hardcoding gpt-3.5-turbo and use config.openai_model."""
    import rag.retrieval.query_processing as qp
    captured = {}
    real = qp.ChatOpenAI

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(qp, "ChatOpenAI", spy)
    cfg = RagConfig(openai_model="gpt-4o-mini", openai_api_key="sk-test")
    qp.get_hyde_embeddings(config=cfg)
    assert captured["model"] == "gpt-4o-mini"
