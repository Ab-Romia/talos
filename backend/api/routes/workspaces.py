"""Workspace routes."""

from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user
from backend.api.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceListResponse,
)
from backend.model.identity import User
from backend.model.messaging import Workspace, Chatroom

router = APIRouter()


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceListResponse:
    """
    List all workspaces for the current user.

    Args:
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List of workspaces
    """
    # Get workspaces owned by user
    workspaces = db.execute(
        select(Workspace).where(
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalars().all()

    # Get chatroom counts for each workspace
    workspace_responses = []
    for workspace in workspaces:
        chatroom_count = db.execute(
            select(func.count(Chatroom.id)).where(
                Chatroom.workspace_id == workspace.id,
                Chatroom.deleted_at.is_(None),
            )
        ).scalar() or 0

        workspace_responses.append(
            WorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                owner_id=workspace.owner_id,
                created_at=workspace.created_at,
                chatroom_count=chatroom_count,
            )
        )

    return WorkspaceListResponse(
        workspaces=workspace_responses,
        total=len(workspace_responses),
    )


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Create a new workspace.

    Args:
        workspace_data: Workspace creation data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Created workspace
    """
    # Check if workspace name already exists for this user
    existing = db.execute(
        select(Workspace).where(
            Workspace.name == workspace_data.name,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace with this name already exists",
        )

    workspace = Workspace(
        name=workspace_data.name,
        owner_id=current_user.id,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        created_at=workspace.created_at,
        chatroom_count=0,
    )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Get a specific workspace.

    Args:
        workspace_id: Workspace ID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Workspace details
    """
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

    chatroom_count = db.execute(
        select(func.count(Chatroom.id)).where(
            Chatroom.workspace_id == workspace.id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar() or 0

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        created_at=workspace.created_at,
        chatroom_count=chatroom_count,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    workspace_data: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Update a workspace.

    Args:
        workspace_id: Workspace ID
        workspace_data: Workspace update data
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Updated workspace
    """
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

    if workspace_data.name is not None:
        # Check if name already exists
        existing = db.execute(
            select(Workspace).where(
                Workspace.name == workspace_data.name,
                Workspace.owner_id == current_user.id,
                Workspace.id != workspace_id,
                Workspace.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace with this name already exists",
            )

        workspace.name = workspace_data.name

    db.commit()
    db.refresh(workspace)

    chatroom_count = db.execute(
        select(func.count(Chatroom.id)).where(
            Chatroom.workspace_id == workspace.id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar() or 0

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        created_at=workspace.created_at,
        chatroom_count=chatroom_count,
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a workspace (soft delete).

    Args:
        workspace_id: Workspace ID
        current_user: Currently authenticated user
        db: Database session
    """
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

    workspace.deleted_at = datetime.now()
    db.commit()
