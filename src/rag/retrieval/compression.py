from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import (
    LLMChainExtractor,
    EmbeddingsFilter,
    DocumentCompressorPipeline,
)
from langchain_core.retrievers import BaseRetriever

from config import CompressionType, RagConfig, global_rag_config
from ..generation import get_llm
from ..vector_store import get_embeddings

__all__ = ["compression_retriever"]


def compression_retriever(
        base_retriever: BaseRetriever,
        compression_type: CompressionType = CompressionType.NONE,
        config: RagConfig = global_rag_config,
):
    """Context compression using CLaRa techniques. LLM, embeddings, and the
    similarity threshold all come from the passed config."""
    threshold = config.compression_similarity_threshold
    match compression_type:
        case CompressionType.LLM:
            compressor = LLMChainExtractor.from_llm(get_llm(config=config))
        case CompressionType.EMBEDDINGS:
            compressor = EmbeddingsFilter(
                embeddings=get_embeddings(config=config), similarity_threshold=threshold
            )
        case CompressionType.PIPELINE:
            embeddings_filter = EmbeddingsFilter(
                embeddings=get_embeddings(config=config), similarity_threshold=threshold
            )
            llm_extractor = LLMChainExtractor.from_llm(get_llm(config=config))
            compressor = DocumentCompressorPipeline(
                transformers=[embeddings_filter, llm_extractor]
            )
        case _:
            return base_retriever

    return ContextualCompressionRetriever(
        base_compressor=compressor, base_retriever=base_retriever
    )
