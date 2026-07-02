from enum import Enum
from typing import Literal, ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["global_rag_config", "RagConfig", "LoggingConfig", "CompressionType"]


class CompressionType(str, Enum):
    LLM = "llm"
    EMBEDDINGS = "embeddings"
    PIPELINE = "pipeline"
    NONE = "none"


class RagConfig(BaseSettings):
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "openai"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "talos_documents"

    retrieval_top_k: int = 5
    # Candidate pool the dense stage fetches BEFORE the cross-encoder reranks
    # down to retrieval_top_k. Widening here is what lets reranking improve
    # recall rather than merely reorder the same top_k. Ignored when
    # use_reranking is False.
    rerank_fetch_k: int = 20
    use_hybrid_retrieval: bool = False
    use_reranking: bool = True
    # HyDE and query rewriting each add an LLM call per query (latency + cost).
    # Gated so they can be turned off (e.g. local/low-VRAM runs, or the
    # technical-corpus regimes where they don't help). Default preserves the
    # prior always-on behaviour.
    use_hyde: bool = True
    use_query_rewrite: bool = True

    compression_type: CompressionType = CompressionType.NONE
    # Similarity floor for the embeddings-filter compressor. Configurable so the
    # eval can calibrate it (0.76 was found too aggressive for
    # text-embedding-3-small) and so what eval sweeps is what prod can ship.
    compression_similarity_threshold: float = 0.76

    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunking_strategy: str = "recursive"

    # Chat-memory indexing: the cron embeds messages older than the grace window
    # (so live messages still in the un-indexed tail aren't indexed prematurely);
    # chat_context_cap bounds the un-indexed tail injected directly per ask.
    chat_index_interval_minutes: int = 5
    chat_index_grace_seconds: int = 300
    chat_index_batch_size: int = 500
    chat_recall_k: int = 3
    chat_context_cap: int = 50

    llm_temperature: float = 0.0
    llm_streaming: bool = True

    langchain_tracing_v2: bool = False
    langchain_api_key: SecretStr | None = None
    langchain_project: str = "gp-artifact-rag"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    # Logging level
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Log format string
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # Log file path
    file_path: str | None = None
    # Enable rich console logging
    enable_rich: bool = True
    # Enable metrics logging
    enable_metrics: bool = True


global_rag_config = RagConfig()
# logging_config = LoggingConfig()
