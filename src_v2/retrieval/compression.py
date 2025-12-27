#Context compression using CLaRa techniques.

from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import (
    LLMChainExtractor,
    EmbeddingsFilter,
    DocumentCompressorPipeline
)
from src_v2.generation.chains import get_llm
from src_v2.vectorstore.embeddings import get_embeddings
from src_v2.config.settings import settings


def get_compression_retriever(base_retriever, compression_type: str = "llm"):
    if compression_type == "llm":
        compressor = LLMChainExtractor.from_llm(get_llm())

    elif compression_type == "embeddings":
        compressor = EmbeddingsFilter(
            embeddings=get_embeddings(),
            similarity_threshold=0.76
        )

    elif compression_type == "pipeline":
        embeddings_filter = EmbeddingsFilter(
            embeddings=get_embeddings(),
            similarity_threshold=0.76
        )
        llm_extractor = LLMChainExtractor.from_llm(get_llm())

        compressor = DocumentCompressorPipeline(
            transformers=[embeddings_filter, llm_extractor]
        )

    else:
        raise ValueError(f"Unknown compression type: {compression_type}")

    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever
    )
