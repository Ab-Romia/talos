from enum import Enum
from pathlib import Path
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
    # OpenAI-compatible endpoint override (e.g. https://openrouter.ai/api/v1)
    openai_base_url: str | None = None

    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "openai"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "documents_v2"

    retrieval_top_k: int = 5
    use_hybrid_retrieval: bool = False
    use_reranking: bool = True

    compression_type: CompressionType = CompressionType.NONE

    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunking_strategy: str = "recursive"

    conversation_memory_k: int = 3

    llm_temperature: float = 0.0
    llm_streaming: bool = True

    langchain_tracing_v2: bool = False
    langchain_api_key: SecretStr | None = None
    langchain_project: str = "gp-artifact-rag"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    yaml_file: Path = Path("config/rag_config.yaml")


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
