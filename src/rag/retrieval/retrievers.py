from collections.abc import Iterable
from functools import lru_cache

from langchain_classic.retrievers import (
    EnsembleRetriever,
    ContextualCompressionRetriever,
)
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from config import RagConfig
from config import global_rag_config
from utils.logger import get_logger

from .compression import compression_retriever

__all__ = ["build_rag_pipeline"]

logger = get_logger(__name__)

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def _get_cross_encoder(model_name: str = CROSS_ENCODER_MODEL) -> HuggingFaceCrossEncoder:
    """Load the reranker once and reuse it for every request. Without this,
    a fresh transformer was being instantiated on every chat message."""
    return HuggingFaceCrossEncoder(model_name=model_name)


def build_rag_pipeline(
    config: RagConfig,
    vectorstore: VectorStore,
    *,
    corpus: Iterable[Document] | None = None,
    search_kwargs: dict | None = None,
) -> BaseRetriever:
    """The single definition of how Talos retrieves. Shared by RAGChain
    (Milvus) and the eval RagVariant (in-memory), so a config/toggle change
    moves both.

    Composition: dense (+ optional BM25 hybrid when a corpus is given) ->
    optional cross-encoder rerank with candidate widening -> optional
    compression.
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

    return compression_retriever(
        base_retriever, compression_type=config.compression_type, config=config
    )
