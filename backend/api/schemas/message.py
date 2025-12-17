"""Message and chat schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Message role enum."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageCreate(BaseModel):
    """Schema for creating a message."""

    content: str = Field(..., min_length=1, max_length=10000, description="Message content")
    chatroom_id: UUID = Field(..., description="ID of the chatroom")


class MessageResponse(BaseModel):
    """Schema for message response."""

    id: UUID
    content: str
    sender_id: Optional[UUID]
    sender_name: Optional[str] = None
    chatroom_id: UUID
    workspace_id: UUID
    role: MessageRole = MessageRole.USER
    created_at: datetime
    sources: Optional[List[Dict[str, Any]]] = None  # For RAG responses
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """Schema for chat request (RAG-powered)."""

    message: str = Field(..., min_length=1, max_length=10000, description="User message")
    chatroom_id: UUID = Field(..., description="ID of the chatroom")
    include_sources: bool = Field(default=True, description="Include source documents in response")
    stream: bool = Field(default=False, description="Enable streaming response")


class SourceInfo(BaseModel):
    """Schema for source document information."""

    content: str = Field(..., description="Source content excerpt")
    document_name: Optional[str] = Field(None, description="Source document name")
    page: Optional[int] = Field(None, description="Page number if applicable")
    score: Optional[float] = Field(None, description="Relevance score")
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Schema for chat response."""

    message: MessageResponse
    sources: List[SourceInfo] = Field(default_factory=list)
    query_type: Optional[str] = None
    processing_time_ms: Optional[float] = None


class ChatStreamResponse(BaseModel):
    """Schema for streaming chat response chunk."""

    content: str = Field(..., description="Response content chunk")
    done: bool = Field(default=False, description="Whether this is the final chunk")
    sources: Optional[List[SourceInfo]] = None  # Only in final chunk
    message_id: Optional[UUID] = None  # Only in final chunk


class MessageListResponse(BaseModel):
    """Schema for message list response."""

    messages: List[MessageResponse]
    total: int
    has_more: bool
