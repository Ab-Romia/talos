from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import (
    LLMChainExtractor,
    EmbeddingsFilter,
    DocumentCompressorPipeline,
)
from langchain_core.retrievers import BaseRetriever

from ..generation import get_llm
from ..vector_store import get_embeddings

__all__ = ["compression_retriever"]


def compression_retriever(
        base_retriever: BaseRetriever,
        compression_type: str = "none",
):
    """Context compression using CLaRa techniques."""
    match compression_type:
        case "llm":
            compressor = LLMChainExtractor.from_llm(get_llm())
        case "embeddings":
            compressor = EmbeddingsFilter(
                embeddings=get_embeddings(), similarity_threshold=0.76
            )
        case "pipeline":
            embeddings_filter = EmbeddingsFilter(
                embeddings=get_embeddings(), similarity_threshold=0.76
            )
            llm_extractor = LLMChainExtractor.from_llm(get_llm())
            compressor = DocumentCompressorPipeline(
                transformers=[embeddings_filter, llm_extractor]
            )
        case _:
            return base_retriever

    return ContextualCompressionRetriever(
        base_compressor=compressor, base_retriever=base_retriever
    )
