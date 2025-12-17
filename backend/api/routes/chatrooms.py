"""Chatroom routes."""

from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user
from backend.api.schemas.chatroom import (
    ChatroomCreate,
    ChatroomUpdate,
    ChatroomResponse,
    ChatroomListResponse,
)
from backend.model.identity import User
from backend.model.messaging import Workspace, Chatroom, Message

router = APIRouter()


@router.get("", response_model=ChatroomListResponse)
async def list_chatrooms(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatroomListResponse:
    """
    List all chatrooms in a workspace.

    Args:
        workspace_id: Workspace ID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List of chatrooms
    """
    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    chatrooms = db.execute(
        select(Chatroom).where(
            Chatroom.workspace_id == workspace_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalars().all()

    # Get message counts
    chatroom_responses = []
    for chatroom in chatrooms:
        message_count = db.execute(
            select(func.count(Message.id)).where(
                Message.chatroom_id == chatroom.id,
            )
        ).scalar() or 0

        chatroom_responses.append(
            ChatroomResponse(
                id=chatroom.id,
                name=chatroom.name,
                workspace_id=chatroom.workspace_id,
                created_at=chatroom.created_at,
                message_count=message_count,
            )
        )

    return ChatroomListResponse(
        chatrooms=chatroom_responses,
        total=len(chatroom_responses),
    )


@router.post("", response_model=ChatroomResponse, status_code=status.HTTP_201_CREATED)
async def create_chatroom(
    chatroom_data: ChatroomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatroomResponse:
    """
    Create a new chatroom.

    Args:
        chatroom_data: Chatroom creation data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Created chatroom
    """
    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom_data.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    chatroom = Chatroom(
        name=chatroom_data.name,
        workspace_id=chatroom_data.workspace_id,
    )
    db.add(chatroom)
    db.commit()
    db.refresh(chatroom)

    return ChatroomResponse(
        id=chatroom.id,
        name=chatroom.name,
        workspace_id=chatroom.workspace_id,
        created_at=chatroom.created_at,
        message_count=0,
    )


@router.get("/{chatroom_id}", response_model=ChatroomResponse)
async def get_chatroom(
    chatroom_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatroomResponse:
    """
    Get a specific chatroom.

    Args:
        chatroom_id: Chatroom ID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Chatroom details
    """
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    message_count = db.execute(
        select(func.count(Message.id)).where(
            Message.chatroom_id == chatroom.id,
        )
    ).scalar() or 0

    return ChatroomResponse(
        id=chatroom.id,
        name=chatroom.name,
        workspace_id=chatroom.workspace_id,
        created_at=chatroom.created_at,
        message_count=message_count,
    )


@router.patch("/{chatroom_id}", response_model=ChatroomResponse)
async def update_chatroom(
    chatroom_id: UUID,
    chatroom_data: ChatroomUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatroomResponse:
    """
    Update a chatroom.

    Args:
        chatroom_id: Chatroom ID
        chatroom_data: Chatroom update data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Updated chatroom
    """
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    if chatroom_data.name is not None:
        chatroom.name = chatroom_data.name

    db.commit()
    db.refresh(chatroom)

    message_count = db.execute(
        select(func.count(Message.id)).where(
            Message.chatroom_id == chatroom.id,
        )
    ).scalar() or 0

    return ChatroomResponse(
        id=chatroom.id,
        name=chatroom.name,
        workspace_id=chatroom.workspace_id,
        created_at=chatroom.created_at,
        message_count=message_count,
    )


@router.delete("/{chatroom_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chatroom(
    chatroom_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a chatroom (soft delete).

    Args:
        chatroom_id: Chatroom ID
        current_user: Currently authenticated user
        db: Database session
    """
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    chatroom.deleted_at = datetime.now()
    db.commit()
