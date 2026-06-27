from fastapi import APIRouter

from chat.router import channel as channel_chat_router
from files.router import workspace as workspace_files_router, channel as channel_files_router
from permissions.router import (
    workspace as workspace_permission_router,
    channel as channel_permission_router)
from workspace import require_perms

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
channel.include_router(channel_permission_router)
channel.include_router(channel_chat_router)
channel.include_router(channel_files_router)
