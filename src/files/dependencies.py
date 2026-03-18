import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from backend.auth.helpers import active_user
from files.storage import MinIOStorage
from model import DatabaseDep
from model.identity import User
from model.messaging import Workspace


def get_workspace_member(
    workspace_id: uuid.UUID,
    user: User = Depends(active_user),
    db: DatabaseDep = None,
) -> Workspace:
    """Verify the user has access to the workspace. Currently checks ownership only."""
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.deleted_at.is_(None),
        )
    )
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")

    if workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a workspace member")

    return workspace


def get_storage(request: Request) -> MinIOStorage:
    """Retrieve the MinIOStorage instance from app state."""
    storage: MinIOStorage | None = getattr(request.app.state, "minio_storage", None)
    if storage is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Storage service not available",
        )
    return storage
