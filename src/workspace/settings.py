"""
Workspace and Channel settings endpoints.
Handles all workspace and channel configuration, member management, etc.
"""
import uuid
from typing import Annotated, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Form, Body, Path, Query
from pydantic import BaseModel, Field
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT

from auth.dependencies import UserIdDep
from database import DatabaseDep
from workspace import require_perms, is_owner, WorkspaceID
from workspace.model import Workspace, Channel
from workspace.service import WorkspaceService, ChannelService

# ==================== Response Models ====================

class WorkspaceSettingsResponse(BaseModel):
    """Response model for workspace settings."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    icon_id: Optional[uuid.UUID] = None
    owner_id: uuid.UUID
    created_at: str

    model_config = {"from_attributes": True}


class ChannelSettingsResponse(BaseModel):
    """Response model for channel settings."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    workspace_id: uuid.UUID
    is_public: bool
    is_muted: bool
    is_archived: bool
    created_at: str

    model_config = {"from_attributes": True}


class WorkspaceMemberResponse(BaseModel):
    """Response model for workspace member."""
    id: uuid.UUID
    username: str
    email: str

    model_config = {"from_attributes": True}


class ChannelListResponse(BaseModel):
    """Response model for channel list."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    is_public: bool
    is_muted: bool
    is_archived: bool

    model_config = {"from_attributes": True}


# ==================== Workspace Settings Router ====================

workspace_settings = APIRouter(prefix="/workspaces/{workspace_id}/settings", tags=["workspace-settings"])


@workspace_settings.get(
    "",
    response_model=WorkspaceSettingsResponse,
    dependencies=[require_perms("workspace:view")]
)
def get_workspace_settings(workspace_id: WorkspaceID, db: DatabaseDep):
    """Get workspace settings."""
    workspace = WorkspaceService.get_workspace(db, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@workspace_settings.put(
    "/name",
    response_model=WorkspaceSettingsResponse,
    dependencies=[require_perms("workspace:edit")]
)
def update_workspace_name(
    workspace_id: WorkspaceID,
    name: Annotated[str, Form()],
    db: DatabaseDep
):
    """Edit workspace name."""
    try:
        workspace = WorkspaceService.update_workspace_name(db, workspace_id, name)
        return workspace
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.put(
    "/description",
    response_model=WorkspaceSettingsResponse,
    dependencies=[require_perms("workspace:edit")]
)
def update_workspace_description(
    workspace_id: WorkspaceID,
    description: Annotated[Optional[str], Form()] = None,
    db: DatabaseDep = None
):
    """Edit workspace description."""
    try:
        workspace = WorkspaceService.update_workspace_description(db, workspace_id, description)
        return workspace
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.put(
    "/icon",
    response_model=WorkspaceSettingsResponse,
    dependencies=[require_perms("workspace:edit")]
)
def update_workspace_icon(
    workspace_id: WorkspaceID,
    icon_id: Annotated[Optional[uuid.UUID], Form()] = None,
    db: DatabaseDep = None
):
    """Edit workspace icon."""
    try:
        workspace = WorkspaceService.update_workspace_icon(db, workspace_id, icon_id)
        return workspace
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.get(
    "/members",
    response_model=list[WorkspaceMemberResponse],
    dependencies=[require_perms("workspace.member:view")]
)
def get_workspace_members(workspace_id: WorkspaceID, db: DatabaseDep):
    """Get all members of the workspace."""
    try:
        members = WorkspaceService.get_workspace_members(db, workspace_id)
        return members
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.post(
    "/members/{user_id}",
    response_model=WorkspaceMemberResponse,
    dependencies=[require_perms("workspace.member:manage")],
    status_code=HTTP_201_CREATED
)
def add_workspace_member(
    workspace_id: WorkspaceID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep
):
    """Add a member to the workspace."""
    try:
        workspace = WorkspaceService.add_workspace_member(db, workspace_id, user_id)
        # Return the added user
        for member in workspace.members:
            if member.id == user_id:
                return member
        raise HTTPException(status_code=404, detail="Member not found after adding")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.delete(
    "/members/{user_id}",
    dependencies=[require_perms("workspace.member:manage")],
    status_code=HTTP_204_NO_CONTENT
)
def remove_workspace_member(
    workspace_id: WorkspaceID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep
):
    """Remove a member from the workspace."""
    try:
        WorkspaceService.remove_workspace_member(db, workspace_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_settings.post(
    "/leave",
    status_code=HTTP_204_NO_CONTENT
)
def leave_workspace(
    workspace_id: WorkspaceID,
    user_id: UserIdDep,
    db: DatabaseDep
):
    """Leave the workspace."""
    try:
        WorkspaceService.leave_workspace(db, workspace_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@workspace_settings.delete(
    "",
    dependencies=[require_perms("workspace:delete")],
    status_code=HTTP_204_NO_CONTENT
)
def delete_workspace(
    workspace_id: WorkspaceID,
    db: DatabaseDep
):
    """Delete workspace (Owner only)."""
    try:
        WorkspaceService.delete_workspace(db, workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Channel Management Router ====================

channel_settings = APIRouter(prefix="/channels/{channel_id}/settings", tags=["channel-settings"])


@channel_settings.get(
    "",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:view")]
)
def get_channel_settings(channel_id: uuid.UUID, db: DatabaseDep):
    """Get channel settings."""
    channel = ChannelService.get_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@channel_settings.put(
    "/name",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:edit")]
)
def rename_channel(
    channel_id: uuid.UUID,
    name: Annotated[str, Form()],
    db: DatabaseDep
):
    """Rename channel."""
    try:
        channel = ChannelService.rename_channel(db, channel_id, name)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.put(
    "/description",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:edit")]
)
def update_channel_description(
    channel_id: uuid.UUID,
    description: Annotated[Optional[str], Form()] = None,
    db: DatabaseDep = None
):
    """Edit channel description."""
    try:
        channel = ChannelService.update_channel_description(db, channel_id, description)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.put(
    "/visibility",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:edit")]
)
def toggle_channel_visibility(
    channel_id: uuid.UUID,
    is_public: Annotated[bool, Form()],
    db: DatabaseDep
):
    """Toggle channel between public/private."""
    try:
        channel = ChannelService.toggle_channel_public(db, channel_id, is_public)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.post(
    "/mute",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:manage")]
)
def mute_channel(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """Mute channel."""
    try:
        channel = ChannelService.mute_channel(db, channel_id)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.post(
    "/unmute",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:manage")]
)
def unmute_channel(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """Unmute channel."""
    try:
        channel = ChannelService.unmute_channel(db, channel_id)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.post(
    "/archive",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:manage")]
)
def archive_channel(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """Archive channel."""
    try:
        channel = ChannelService.archive_channel(db, channel_id)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.post(
    "/unarchive",
    response_model=ChannelSettingsResponse,
    dependencies=[require_perms("channel:manage")]
)
def unarchive_channel(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """Unarchive channel."""
    try:
        channel = ChannelService.unarchive_channel(db, channel_id)
        return channel
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_settings.delete(
    "",
    dependencies=[require_perms("channel:delete")],
    status_code=HTTP_204_NO_CONTENT
)
def delete_channel(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """Delete channel."""
    try:
        ChannelService.delete_channel(db, channel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))




