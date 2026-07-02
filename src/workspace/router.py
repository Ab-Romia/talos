from fastapi import APIRouter

from chat.router import channel as channel_chat_router
from filesystem.router import workspace as workspace_files_router, channel as channel_files_router
from permissions.router import (
    workspace as workspace_permission_router,
    channel as channel_permission_router)
from workspace import require_perms
from workspace.settings import workspace_settings, channel_settings
from workspace.channels import channels as channels_router
from workspace.workspace_members import workspace_members

workspace = APIRouter(
    prefix="/workspaces/{workspace_id}",
    dependencies=[require_perms("workspace:view")],
)
channel = APIRouter(
    prefix="/channels/{channel_id}",
    dependencies=[require_perms("channel:view")],
)

workspace.include_router(workspace_permission_router)
workspace.include_router(workspace_files_router)
workspace.include_router(workspace_settings)
workspace.include_router(channels_router)
workspace.include_router(workspace_members)
channel.include_router(channel_permission_router)
channel.include_router(channel_chat_router)
channel.include_router(channel_files_router)
channel.include_router(channel_settings)
