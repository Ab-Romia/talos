"""Chatroom schemas."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class ChatroomCreate(BaseModel):
    """Schema for creating a chatroom."""

    name: str = Field(..., min_length=1, max_length=100, description="Chatroom name")
    workspace_id: UUID = Field(..., description="ID of the workspace this chatroom belongs to")


class ChatroomUpdate(BaseModel):
    """Schema for updating a chatroom."""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Chatroom name")


class ChatroomResponse(BaseModel):
    """Schema for chatroom response."""

    id: UUID
    name: str
    workspace_id: UUID
    created_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatroomListResponse(BaseModel):
    """Schema for chatroom list response."""

    chatrooms: List[ChatroomResponse]
    total: int
