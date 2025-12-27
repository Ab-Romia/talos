from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    embedding_model: str = "text-embedding-3-small"
    embedding_cache_dir: str = ".cache/embeddings"
    embedding_provider: str = "openai"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "documents_v2"

    retrieval_top_k: int = 5
    rerank_top_k: int = 3
    use_hybrid_retrieval: bool = True
    use_reranking: bool = True
    hybrid_dense_weight: float = 0.5
    hybrid_sparse_weight: float = 0.5

    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunking_strategy: str = "recursive"

    conversation_memory_k: int = 3

    llm_temperature: float = 0.0
    llm_streaming: bool = True

    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "gp-artifact-rag"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
