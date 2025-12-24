"""
Configuration loader using Pydantic models for type-safe, validated configuration.

All RAG system parameters are defined here with sensible defaults.
Configuration can be loaded from YAML files or environment variables.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class MilvusConfig(BaseModel):
    """Milvus vector database configuration."""

    host: str = Field(default="localhost", description="Milvus server host")
    port: int = Field(default=19530, description="Milvus server port")
    user: Optional[str] = Field(default=None, description="Milvus username")
    password: Optional[str] = Field(default=None, description="Milvus password")
    database: str = Field(default="default", description="Database name")
    collection_name: str = Field(default="rag_collection", description="Collection name")
    dimension: int = Field(default=1536, description="Vector dimension")
    index_type: Literal["IVF_FLAT", "IVF_SQ8", "IVF_PQ", "HNSW", "DISKANN", "AUTOINDEX"] = Field(
        default="HNSW", description="Index type for vector search"
    )
    metric_type: Literal["L2", "IP", "COSINE"] = Field(
        default="COSINE", description="Distance metric type"
    )
    index_params: Dict[str, Any] = Field(
        default_factory=lambda: {"M": 16, "efConstruction": 256},
        description="Index-specific parameters",
    )
    search_params: Dict[str, Any] = Field(
        default_factory=lambda: {"ef": 64}, description="Search-specific parameters"
    )
    consistency_level: Literal["Strong", "Bounded", "Session", "Eventually"] = Field(
        default="Bounded", description="Consistency level for operations"
    )
    pool_size: int = Field(default=10, description="Connection pool size")
    timeout: float = Field(default=30.0, description="Operation timeout in seconds")

    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Dimension must be positive")
        return v


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""

    provider: Literal["openai", "huggingface", "cohere", "sentence_transformers", "local"] = Field(
        default="openai", description="Embedding provider"
    )
    model_name: str = Field(
        default="text-embedding-3-small", description="Embedding model name"
    )
    dimension: int = Field(default=1536, description="Embedding dimension")
    batch_size: int = Field(default=32, description="Batch size for embedding generation")
    max_retries: int = Field(default=3, description="Maximum retries on failure")
    normalize: bool = Field(default=True, description="Normalize embeddings to unit length")
    api_key_env: str = Field(
        default="OPENAI_API_KEY", description="Environment variable name for API key"
    )
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Batch size must be positive")
        if v > 2048:
            raise ValueError("Batch size too large, maximum is 2048")
        return v


class RetrieverConfig(BaseModel):
    """Retriever configuration for document retrieval."""

    top_k: int = Field(default=10, description="Number of documents to retrieve")
    retrieval_method: Literal["dense", "sparse", "hybrid"] = Field(
        default="hybrid", description="Retrieval method"
    )
    dense_weight: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Weight for dense retrieval in hybrid"
    )
    sparse_weight: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Weight for sparse retrieval in hybrid"
    )
    rrf_k: int = Field(default=60, description="RRF constant for rank fusion")
    similarity_threshold: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum similarity threshold"
    )
    use_metadata_filter: bool = Field(default=False, description="Enable metadata filtering")
    metadata_filter: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata filter expression"
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "RetrieverConfig":
        if self.retrieval_method == "hybrid":
            total = self.dense_weight + self.sparse_weight
            if abs(total - 1.0) > 0.01:
                # Normalize weights
                self.dense_weight = self.dense_weight / total
                self.sparse_weight = self.sparse_weight / total
        return self


class RerankerConfig(BaseModel):
    """Reranker configuration for post-retrieval reranking."""

    enabled: bool = Field(default=True, description="Enable reranking")
    model_name: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder model for reranking",
    )
    top_n: int = Field(default=5, description="Number of documents after reranking")
    batch_size: int = Field(default=32, description="Batch size for reranking")
    relevance_threshold: float = Field(
        default=-100.0, description="Minimum relevance score threshold (cross-encoder scores can be negative)"
    )
    use_gpu: bool = Field(default=False, description="Use GPU for reranking")


class CompressionConfig(BaseModel):
    """Context compression configuration (CLaRa-inspired)."""

    enabled: bool = Field(default=False, description="Enable context compression")
    method: Literal["llm_extractor", "embeddings_filter", "llm_chain_filter"] = Field(
        default="llm_extractor", description="Compression method"
    )
    compression_ratio: float = Field(
        default=0.5, ge=0.1, le=1.0, description="Target compression ratio"
    )
    similarity_threshold: float = Field(
        default=0.75, ge=0.0, le=1.0, description="Similarity threshold for filtering"
    )


class GeneratorConfig(BaseModel):
    """LLM generator configuration."""

    provider: Literal["openai", "anthropic", "local", "azure_openai"] = Field(
        default="openai", description="LLM provider"
    )
    model_name: str = Field(default="gpt-4o-mini", description="Model name")
    temperature: float = Field(
        default=0.1, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: int = Field(default=1000, description="Maximum tokens in response")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="Top-p sampling")
    frequency_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0, description="Frequency penalty"
    )
    presence_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0, description="Presence penalty"
    )
    api_key_env: str = Field(
        default="OPENAI_API_KEY", description="Environment variable for API key"
    )
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    timeout: float = Field(default=60.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retries on failure")
    stream: bool = Field(default=False, description="Enable streaming responses")


class QueryProcessorConfig(BaseModel):
    """Query processing configuration."""

    enabled: bool = Field(default=True, description="Enable query processing")
    rewriting: bool = Field(default=True, description="Enable query rewriting")
    expansion: bool = Field(default=True, description="Enable query expansion")
    hyde: bool = Field(default=False, description="Enable HyDE (Hypothetical Document Embedding)")
    step_back: bool = Field(default=False, description="Enable step-back prompting")
    decomposition: bool = Field(
        default=False, description="Enable query decomposition for complex queries"
    )
    multi_query: bool = Field(
        default=False, description="Enable multi-query generation"
    )
    num_generated_queries: int = Field(
        default=3, description="Number of queries to generate for multi-query"
    )


class OrchestrationConfig(BaseModel):
    """Pipeline orchestration configuration."""

    routing_enabled: bool = Field(default=True, description="Enable query routing")
    max_iterations: int = Field(
        default=3, ge=1, le=10, description="Maximum retrieval iterations"
    )
    answer_completeness_threshold: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Threshold for answer completeness"
    )
    enable_self_reflection: bool = Field(
        default=False, description="Enable self-reflective RAG with document grading"
    )
    workflow_type: Literal["simple", "adaptive", "self_reflective"] = Field(
        default="adaptive", description="RAG workflow type"
    )


class ChunkingConfig(BaseModel):
    """Document chunking configuration."""

    strategy: Literal["fixed", "semantic", "recursive", "sentence", "markdown"] = Field(
        default="semantic", description="Chunking strategy"
    )
    chunk_size: int = Field(default=1000, description="Target chunk size in characters")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks")
    min_chunk_size: int = Field(default=100, description="Minimum chunk size")
    max_chunk_size: int = Field(default=2000, description="Maximum chunk size")
    separators: List[str] = Field(
        default_factory=lambda: ["\n\n", "\n", ". ", " ", ""],
        description="Separators for recursive chunking",
    )
    breakpoint_threshold_type: Literal["percentile", "standard_deviation", "interquartile"] = Field(
        default="percentile", description="Threshold type for semantic chunking"
    )
    breakpoint_threshold_amount: float = Field(
        default=95.0, description="Threshold amount for semantic chunking"
    )

    @model_validator(mode="after")
    def validate_chunk_sizes(self) -> "ChunkingConfig":
        if self.min_chunk_size >= self.max_chunk_size:
            raise ValueError("min_chunk_size must be less than max_chunk_size")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class MemoryConfig(BaseModel):
    """Conversation memory configuration."""

    enabled: bool = Field(default=True, description="Enable conversation memory")
    max_history: int = Field(default=10, description="Maximum conversation turns to store")
    include_context_in_history: bool = Field(
        default=False, description="Include retrieved context in history"
    )
    summary_enabled: bool = Field(
        default=False, description="Enable conversation summarization"
    )
    summary_threshold: int = Field(
        default=5, description="Number of turns before summarizing"
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )
    file_path: Optional[str] = Field(default=None, description="Log file path")
    enable_rich: bool = Field(default=True, description="Enable rich console logging")
    enable_metrics: bool = Field(default=True, description="Enable metrics logging")


class KnowledgeBaseConfig(BaseModel):
    """Knowledge base metadata configuration."""

    description: str = Field(
        default="General knowledge base", description="Description of the knowledge base"
    )
    domain: str = Field(default="general", description="Domain of the knowledge base")
    source_paths: List[str] = Field(
        default_factory=list, description="Paths to knowledge base sources"
    )


class PromptConfig(BaseModel):
    """Prompt template configuration."""

    qa_template_path: str = Field(
        default="config/prompts/qa_prompt.yaml", description="Path to QA prompt template"
    )
    rewrite_template_path: str = Field(
        default="config/prompts/query_rewrite_prompt.yaml",
        description="Path to query rewrite prompt template",
    )
    hyde_template_path: str = Field(
        default="config/prompts/hyde_prompt.yaml",
        description="Path to HyDE prompt template",
    )
    system_prompt: Optional[str] = Field(
        default=None, description="Custom system prompt override"
    )


class RAGConfig(BaseModel):
    """
    Main RAG configuration model.

    Aggregates all component configurations into a single validated model.
    Can be loaded from YAML files or created programmatically.
    """

    # Component configurations
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    retriever: RetrieverConfig = Field(default_factory=RetrieverConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    generator: GeneratorConfig = Field(default_factory=GeneratorConfig)
    query_processor: QueryProcessorConfig = Field(default_factory=QueryProcessorConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)

    # Pipeline settings
    pipeline_type: Literal["simple", "modular"] = Field(
        default="modular", description="Pipeline type"
    )

    @classmethod
    def from_yaml(cls, config_path: Union[str, Path]) -> "RAGConfig":
        """Load configuration from a YAML file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_dict = yaml.safe_load(f)

        return cls.model_validate(config_dict or {})

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "RAGConfig":
        """Create configuration from a dictionary."""
        return cls.model_validate(config_dict)

    def to_yaml(self, config_path: Union[str, Path]) -> None:
        """Save configuration to a YAML file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)

    def update_from_env(self) -> "RAGConfig":
        """Update configuration from environment variables."""
        # Override with environment variables if present
        if milvus_host := os.getenv("MILVUS_HOST"):
            self.milvus.host = milvus_host
        if milvus_port := os.getenv("MILVUS_PORT"):
            self.milvus.port = int(milvus_port)
        if collection_name := os.getenv("MILVUS_COLLECTION"):
            self.milvus.collection_name = collection_name

        return self


def load_config(config_path: Optional[Union[str, Path]] = None) -> RAGConfig:
    """
    Load RAG configuration from file or create default.

    Args:
        config_path: Path to YAML configuration file. If None, looks for
                    config/rag_config.yaml or uses defaults.

    Returns:
        Validated RAGConfig instance.
    """
    if config_path is None:
        # Try default locations
        default_paths = [
            Path("config/rag_config.yaml"),
            Path("rag_config.yaml"),
            Path.home() / ".config" / "rag" / "config.yaml",
        ]
        for path in default_paths:
            if path.exists():
                config_path = path
                break

    if config_path and Path(config_path).exists():
        config = RAGConfig.from_yaml(config_path)
    else:
        config = RAGConfig()

    # Update from environment variables
    return config.update_from_env()
