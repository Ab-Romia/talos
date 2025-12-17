"""Workspace schemas."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    """Schema for creating a workspace."""

    name: str = Field(..., min_length=1, max_length=100, description="Workspace name")


class WorkspaceUpdate(BaseModel):
    """Schema for updating a workspace."""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Workspace name")


class WorkspaceResponse(BaseModel):
    """Schema for workspace response."""

    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime
    chatroom_count: int = 0

    class Config:
        from_attributes = True


class WorkspaceListResponse(BaseModel):
    """Schema for workspace list response."""

    workspaces: List[WorkspaceResponse]
    total: int
