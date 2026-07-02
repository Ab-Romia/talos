"""
Workspace members management endpoints.
Handles adding/removing members from workspaces.
Members are controlled at the workspace level.
Channel access is managed through the permission system.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from starlette.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from auth.model import User
from database import DatabaseDep
from workspace import require_perms, WorkspaceID
from workspace.model import Workspace
from workspace.service import WorkspaceService

# ==================== Response Models ====================

class WorkspaceMemberResponse(BaseModel):
    """Response model for workspace member."""
    id: uuid.UUID
    username: str
    email: str

    model_config = {"from_attributes": True}


class WorkspaceMembersListResponse(BaseModel):
    """Response model for workspace members list."""
    members: list[WorkspaceMemberResponse]
    total: int


# ==================== Workspace Members Router ====================

workspace_members = APIRouter(
    prefix="/members",
    tags=["workspace-members"],
    dependencies=[require_perms("workspace:view")]
)


@workspace_members.get(
    "",
    response_model=WorkspaceMembersListResponse
)
def list_workspace_members(
    workspace_id: WorkspaceID,
    skip: int = 0,
    limit: int = 50,
    db: DatabaseDep = None
):
    """
    List all members of a workspace.

    Query Parameters:
    - skip: Number of members to skip (default: 0)
    - limit: Maximum number of members to return (default: 50, max: 100)
    """
    if limit > 100:
        limit = 100
    if skip < 0:
        skip = 0

    try:
        members = WorkspaceService.get_workspace_members(db, workspace_id)
        paginated_members = members[skip:skip + limit]
        return {
            "members": paginated_members,
            "total": len(members)
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_members.post(
    "/{user_id}",
    response_model=WorkspaceMemberResponse,
    dependencies=[require_perms("workspace.member:manage")],
    status_code=HTTP_201_CREATED
)
def add_member_to_workspace(
    workspace_id: WorkspaceID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep = None
):
    """
    Add a member to the workspace.

    Path Parameters:
    - user_id: The ID of the user to add

    Note: Once a user is a workspace member, they can access channels
    based on their permissions. Channel-level access is controlled
    through the permission system, not member lists.
    """
    try:
        workspace = WorkspaceService.add_workspace_member(db, workspace_id, user_id)
        # Return the added member
        added_user = db.get(User, user_id)
        return added_user
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@workspace_members.delete(
    "/{user_id}",
    dependencies=[require_perms("workspace.member:manage")],
    status_code=HTTP_204_NO_CONTENT
)
def remove_member_from_workspace(
    workspace_id: WorkspaceID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep = None
):
    """
    Remove a member from the workspace.

    Path Parameters:
    - user_id: The ID of the user to remove

    Note: Removing a workspace member will restrict their access to all channels.
    """
    try:
        WorkspaceService.remove_workspace_member(db, workspace_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

