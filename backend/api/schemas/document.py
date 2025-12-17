"""Document schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentCreate(BaseModel):
    """Schema for creating a document record."""

    name: str = Field(..., min_length=1, max_length=255, description="Document name")
    workspace_id: UUID = Field(..., description="ID of the workspace")
    description: Optional[str] = Field(None, max_length=1000, description="Document description")
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(BaseModel):
    """Schema for document response."""

    id: UUID
    name: str
    workspace_id: UUID
    owner_id: UUID
    description: Optional[str]
    file_type: Optional[str]
    file_size: Optional[int]
    status: DocumentStatus
    chunk_count: int = 0
    created_at: datetime
    processed_at: Optional[datetime]
    metadata: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """Schema for document upload response."""

    document: DocumentResponse
    message: str = "Document uploaded successfully"


class IngestionStatus(BaseModel):
    """Schema for document ingestion status."""

    document_id: UUID
    status: DocumentStatus
    progress: float = Field(ge=0.0, le=100.0, description="Processing progress percentage")
    chunks_processed: int = 0
    total_chunks: int = 0
    error_message: Optional[str] = None


class DocumentListResponse(BaseModel):
    """Schema for document list response."""

    documents: List[DocumentResponse]
    total: int


class DocumentSearchRequest(BaseModel):
    """Schema for document search request."""

    query: str = Field(..., min_length=1, max_length=1000)
    workspace_id: Optional[UUID] = None
    top_k: int = Field(default=10, ge=1, le=100)
    filters: Optional[Dict[str, Any]] = None
