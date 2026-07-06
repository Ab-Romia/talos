"""Task 2 — one Milvus collection. The product, ingestion, indexer, and CLI must
all read/write the same collection; the split (config default documents_v2 vs the
hardcoded talos_documents) is gone."""

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
