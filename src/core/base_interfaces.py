"""
Abstract base classes for RAG system components.

These interfaces define contracts that all implementations must follow,
enabling easy component swapping and testing.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from datetime import datetime


@dataclass
class Document:
    """Represents a document or chunk with content and metadata."""

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    embedding: Optional[List[float]] = None
    score: Optional[float] = None

    def __post_init__(self):
        if self.id is None:
            import uuid
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert document to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "embedding": self.embedding,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """Create document from dictionary."""
        return cls(
            id=data.get("id"),
            content=data["content"],
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
            score=data.get("score"),
        )


@dataclass
class RetrievalResult:
    """Result from a retrieval operation."""

    documents: List[Document]
    query: str
    method: str
    total_found: int
    latency_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """Result from a generation operation."""

    answer: str
    sources: List[Document]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Complete result from a RAG query."""

    answer: str
    sources: List[Document]
    query: str
    processed_query: Optional[str] = None
    query_type: Optional[str] = None
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class BaseEmbedding(ABC):
    """Abstract base class for embedding models."""

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text."""
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the embedding dimension."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name."""
        pass


class BaseVectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    def create_collection(
        self,
        collection_name: str,
        dimension: int,
        metadata_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a new collection."""
        pass

    @abstractmethod
    def insert(
        self,
        collection_name: str,
        documents: List[Document],
    ) -> List[str]:
        """Insert documents into collection."""
        pass

    @abstractmethod
    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Search for similar documents."""
        pass

    @abstractmethod
    def delete(
        self,
        collection_name: str,
        ids: List[str],
    ) -> None:
        """Delete documents by ID."""
        pass

    @abstractmethod
    def collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists."""
        pass

    @abstractmethod
    def drop_collection(self, collection_name: str) -> None:
        """Drop a collection."""
        pass

    @abstractmethod
    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Get collection statistics."""
        pass


class BaseRetriever(ABC):
    """Abstract base class for document retrievers."""

    @abstractmethod
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """Retrieve relevant documents for a query."""
        pass

    @abstractmethod
    def retrieve_with_scores(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Retrieve documents with relevance scores."""
        pass


class BaseReranker(ABC):
    """Abstract base class for document rerankers."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        """Rerank documents based on query relevance."""
        pass

    @abstractmethod
    def score(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Tuple[Document, float]]:
        """Score documents without reordering."""
        pass


class BaseGenerator(ABC):
    """Abstract base class for response generators."""

    @abstractmethod
    def generate(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> GenerationResult:
        """Generate a response based on query and context."""
        pass

    @abstractmethod
    def generate_stream(
        self,
        query: str,
        context: List[Document],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ):
        """Generate a streaming response."""
        pass


class BaseChunker(ABC):
    """Abstract base class for document chunkers."""

    @abstractmethod
    def chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Split text into chunks."""
        pass

    @abstractmethod
    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Chunk multiple documents."""
        pass


class BaseDocumentLoader(ABC):
    """Abstract base class for document loaders."""

    @abstractmethod
    def load(self, source: str) -> List[Document]:
        """Load documents from a source."""
        pass

    @abstractmethod
    def load_and_chunk(
        self,
        source: str,
        chunker: Optional[BaseChunker] = None,
    ) -> List[Document]:
        """Load and chunk documents in one operation."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        pass


class BaseQueryProcessor(ABC):
    """Abstract base class for query processors."""

    @abstractmethod
    def process(
        self,
        query: str,
        conversation_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a query and return transformation results."""
        pass

    @abstractmethod
    def rewrite(self, query: str) -> str:
        """Rewrite a query for better retrieval."""
        pass

    @abstractmethod
    def expand(self, query: str) -> List[str]:
        """Expand query into multiple variations."""
        pass


class BaseContextCompressor(ABC):
    """Abstract base class for context compressors (CLaRa-inspired)."""

    @abstractmethod
    def compress(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Document]:
        """Compress context while preserving relevant information."""
        pass


class BaseMemory(ABC):
    """Abstract base class for conversation memory."""

    @abstractmethod
    def add_turn(
        self,
        question: str,
        answer: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a conversation turn."""
        pass

    @abstractmethod
    def get_history(self, max_turns: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get conversation history."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear conversation history."""
        pass

    @abstractmethod
    def get_context_string(self, max_turns: Optional[int] = None) -> str:
        """Get conversation history as a formatted string."""
        pass


class BaseQueryRouter(ABC):
    """Abstract base class for query routers."""

    @abstractmethod
    def classify(self, query: str) -> str:
        """Classify query type."""
        pass

    @abstractmethod
    def get_pipeline_config(self, query_type: str) -> Dict[str, Any]:
        """Get pipeline configuration for query type."""
        pass


class BaseRAGPipeline(ABC):
    """Abstract base class for RAG pipelines."""

    @abstractmethod
    def query(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> QueryResult:
        """Execute a RAG query."""
        pass

    @abstractmethod
    def ingest(
        self,
        documents: Union[List[Document], List[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Ingest documents into the system."""
        pass

    @abstractmethod
    def get_pipeline_info(self) -> Dict[str, Any]:
        """Get information about the pipeline configuration."""
        pass
