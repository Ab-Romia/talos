"""
Channels management endpoints at the workspace level.
Handles channel creation, listing, and deletion from workspace perspective.
"""
import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Form, Path
from pydantic import BaseModel
from starlette.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from database import DatabaseDep
from workspace import require_perms, WorkspaceID
from workspace.service import WorkspaceService, ChannelService


class ChannelListResponse(BaseModel):
    """Response model for channel list."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    is_public: bool
    is_muted: bool
    is_archived: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChannelCreateResponse(BaseModel):
    """Response model for created channel."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    workspace_id: uuid.UUID
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


channels = APIRouter(
    prefix="/channels",
    tags=["workspace-channels"]
)


@channels.get(
    "",
    response_model=list[ChannelListResponse],
    dependencies=[require_perms("channel:view")]
)
def list_workspace_channels(
        workspace_id: WorkspaceID,
        skip: int = 0,
        limit: int = 50,
        db: DatabaseDep = None
):
    """
    List all channels in a workspace.

    Query Parameters:
    - skip: Number of channels to skip (default: 0)
    - limit: Maximum number of channels to return (default: 50, max: 100)
    """
    if limit > 100:
        limit = 100
    if skip < 0:
        skip = 0

    try:
        channels_list = ChannelService.get_workspace_channels(db, workspace_id)
        return channels_list[skip:skip + limit]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channels.post(
    "",
    response_model=ChannelCreateResponse,
    dependencies=[require_perms("channel:create")],
    status_code=HTTP_201_CREATED
)
def create_workspace_channel(
        workspace_id: WorkspaceID,
        name: Annotated[str, Form()],
        description: Annotated[Optional[str], Form()] = None,
        is_public: Annotated[bool, Form()] = True,
        db: DatabaseDep = None
):
    """
    Create a new channel in the workspace.

    Form Parameters:
    - name: Channel name (required)
    - description: Channel description (optional)
    - is_public: Whether the channel is public (default: true)
    """
    try:
        channel = WorkspaceService.create_channel(
            db,
            workspace_id,
            name,
            description=description,
            is_public=is_public
        )
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channels.delete(
    "/{channel_id}",
    dependencies=[require_perms("channel:delete")],
    status_code=HTTP_204_NO_CONTENT
)
def delete_workspace_channel(
        workspace_id: WorkspaceID,
        channel_id: Annotated[uuid.UUID, Path()],
        db: DatabaseDep
):
    """
    Delete a channel from the workspace.

    Note: This will permanently delete all messages in the channel.
    """
    try:
        channel = ChannelService.get_channel(db, channel_id)
        if channel is None:
            raise ValueError("Channel not found")

        # Verify channel belongs to workspace
        if channel.workspace_id != workspace_id:
            raise ValueError("Channel does not belong to this workspace")

        name = channel.name
        ChannelService.delete_channel(db, channel_id)

        from chat.sync import notify_workspace
        notify_workspace(db, workspace_id, "channels", action="deleted", name=name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
