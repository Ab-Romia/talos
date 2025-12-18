"""Indexing module for vector storage and management."""

from src.indexing.milvus_manager import MilvusVectorStore, InMemoryVectorStore
from src.indexing.milvus_vector_store import (
    OptimizedMilvusVectorStore,
    IndexConfig,
    IndexType,
    MetricType,
    create_milvus_store,
)
from src.indexing.sparse_encoder import (
    SparseEncoder,
    SparseVector,
    BM25Encoder,
    TFIDFEncoder,
    SPLADEEncoder,
    create_sparse_encoder,
)
from src.indexing.embedding_service import (
    EmbeddingService,
    OpenAIEmbedding,
    HuggingFaceEmbedding,
    create_embedding_service,
)
from src.indexing.index_builder import IndexBuilder

__all__ = [
    # Vector stores
    "MilvusVectorStore",
    "InMemoryVectorStore",
    "OptimizedMilvusVectorStore",
    "create_milvus_store",
    # Index configuration
    "IndexConfig",
    "IndexType",
    "MetricType",
    # Sparse encoding
    "SparseEncoder",
    "SparseVector",
    "BM25Encoder",
    "TFIDFEncoder",
    "SPLADEEncoder",
    "create_sparse_encoder",
    # Embeddings
    "EmbeddingService",
    "OpenAIEmbedding",
    "HuggingFaceEmbedding",
    "create_embedding_service",
    # Index building
    "IndexBuilder",
]
