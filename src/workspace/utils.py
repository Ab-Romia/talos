import uuid
from typing import Annotated

from fastapi import Depends, Path

from auth import UserIdDep
from database import DatabaseDep
from permissions import require_perms as default_require_perms
from workspace.model import Workspace, Channel


def is_owner(user_id: UserIdDep,
             workspace_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
             channel_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
             db: DatabaseDep) -> bool:
    if workspace_id is not None:
        workspace = db.get(Workspace, workspace_id)
        return workspace is not None and workspace.owner_id == user_id
    if channel_id is not None:
        channel = db.get(Channel, channel_id)
        return channel is not None and channel.workspace.owner_id == user_id
    return False


def require_perms(*permission, is_owner=is_owner):
    return Depends(default_require_perms(*permission, is_owner=is_owner))


WorkspaceID = uuid.UUID
RoleID = uuid.UUID
