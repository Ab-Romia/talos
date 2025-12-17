"""RAG system schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


class SourceDocument(BaseModel):
    """Schema for source document in RAG response."""

    content: str = Field(..., description="Document content")
    document_id: Optional[str] = Field(None, description="Document ID")
    document_name: Optional[str] = Field(None, description="Document name")
    page: Optional[int] = Field(None, description="Page number")
    chunk_index: Optional[int] = Field(None, description="Chunk index")
    score: Optional[float] = Field(None, description="Relevance score")
    metadata: Optional[Dict[str, Any]] = None


class RAGQueryRequest(BaseModel):
    """Schema for RAG query request."""

    query: str = Field(..., min_length=1, max_length=5000, description="User query")
    workspace_id: Optional[UUID] = Field(None, description="Limit search to workspace")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of documents to retrieve")
    include_sources: bool = Field(default=True, description="Include source documents")
    filters: Optional[Dict[str, Any]] = Field(None, description="Metadata filters")
    conversation_id: Optional[UUID] = Field(None, description="Conversation ID for context")


class RAGQueryResponse(BaseModel):
    """Schema for RAG query response."""

    answer: str = Field(..., description="Generated answer")
    query: str = Field(..., description="Original query")
    sources: List[SourceDocument] = Field(default_factory=list)
    query_type: Optional[str] = Field(None, description="Detected query type")
    processed_query: Optional[str] = Field(None, description="Processed/rewritten query")
    retrieval_latency_ms: Optional[float] = None
    generation_latency_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class RAGConfigResponse(BaseModel):
    """Schema for RAG configuration response."""

    pipeline_type: str
    embedding_model: str
    llm_model: str
    retrieval_method: str
    reranker_enabled: bool
    reranker_model: Optional[str]
    query_processing_enabled: bool
    routing_enabled: bool
    compression_enabled: bool
    memory_enabled: bool
    collection_name: str


class RAGHealthResponse(BaseModel):
    """Schema for RAG system health check."""

    status: str = Field(..., description="Health status")
    vector_store_connected: bool
    llm_available: bool
    embedding_service_available: bool
    indexed_documents: int
    last_ingestion: Optional[datetime] = None


class ConversationContext(BaseModel):
    """Schema for conversation context."""

    conversation_id: UUID
    messages: List[Dict[str, str]] = Field(default_factory=list)
    summary: Optional[str] = None
