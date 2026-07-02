"""
Channel members management endpoints.
Handles adding/removing members from channels.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from starlette.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from auth.model import User
from database import DatabaseDep
from workspace import require_perms
from workspace.model import Channel
from sqlalchemy import select
from sqlalchemy.orm import Session

# ==================== Response Models ====================

class ChannelMemberResponse(BaseModel):
    """Response model for channel member."""
    id: uuid.UUID
    username: str
    email: str

    model_config = {"from_attributes": True}


# ==================== Channel Members Router ====================

channel_members = APIRouter(
    prefix="/channels/{channel_id}/members",
    tags=["channel-members"],
    dependencies=[require_perms("channel:view")]
)


def get_channel_members(db: Session, channel_id: uuid.UUID) -> list[User]:
    """Get all members of a channel."""
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise ValueError("Channel not found")

    # Get unique members from workspace who have access to this channel
    # For now, channel members are workspace members (can be extended later)
    return channel.workspace.members


def add_channel_member(db: Session, channel_id: uuid.UUID, user_id: uuid.UUID) -> User:
    """Add a member to a channel (must be workspace member)."""
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise ValueError("Channel not found")

    user = db.get(User, user_id)
    if user is None:
        raise ValueError("User not found")

    # Verify user is a workspace member
    if user not in channel.workspace.members:
        raise ValueError("User is not a member of the workspace")

    # Note: Current implementation treats all workspace members as channel members
    # To add per-channel member tracking, a new relationship table would be needed
    return user


def remove_channel_member(db: Session, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Remove a member from a channel."""
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise ValueError("Channel not found")

    user = db.get(User, user_id)
    if user is None:
        raise ValueError("User not found")

    # Note: Current implementation treats all workspace members as channel members
    # To add per-channel member tracking, a new relationship table would be needed
    # For now, this operation would require a channel_members table
    raise NotImplementedError("Per-channel member tracking requires additional database schema")


@channel_members.get(
    "",
    response_model=list[ChannelMemberResponse]
)
def list_channel_members(
    channel_id: uuid.UUID,
    db: DatabaseDep
):
    """
    List all members of a channel.
    Currently returns all workspace members who have access to the channel.
    """
    try:
        members = get_channel_members(db, channel_id)
        return members
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_members.post(
    "/{user_id}",
    response_model=ChannelMemberResponse,
    dependencies=[require_perms("channel.member:manage")],
    status_code=HTTP_201_CREATED
)
def add_member_to_channel(
    channel_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep
):
    """
    Add a member to a channel.
    The user must already be a member of the workspace.
    """
    try:
        member = add_channel_member(db, channel_id, user_id)
        return member
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@channel_members.delete(
    "/{user_id}",
    dependencies=[require_perms("channel.member:manage")],
    status_code=HTTP_204_NO_CONTENT
)
def remove_member_from_channel(
    channel_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Path()],
    db: DatabaseDep
):
    """
    Remove a member from a channel.
    Note: This requires implementation of per-channel member tracking.
    """
    try:
        remove_channel_member(db, channel_id, user_id)
    except NotImplementedError as e:
        raise HTTPException(
            status_code=501,
            detail="Per-channel member management requires additional database schema. "
                   "For now, use workspace member management to control channel access."
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

