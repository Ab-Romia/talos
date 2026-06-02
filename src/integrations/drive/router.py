"""Google Drive integration endpoints.

Mounted under /api/integrations/drive. Requires the user to have signed in
via Google with the drive.file scope; otherwise endpoints return 412.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from auth.model import ProviderToken, User
from auth.utils.helpers import active_user
from files.dependencies import get_storage, get_workspace_member
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.service import FileService
from files.storage import MinIOStorage
from model import DatabaseDep
from workspace.model import Workspace, Channel
from .client import DriveClient
from .constants import DEFAULT_LIST_PAGE_SIZE, MAX_LIST_PAGE_SIZE
from .exceptions import DriveAPIError, DriveNotConnected, DriveTokenRefreshFailed
from .schemas import (
    DriveFile,
    DriveFileListResponse,
    DriveImportResponse,
    DriveStatusResponse,
)
from .service import DriveImportService

router = APIRouter(prefix="/integrations/drive", tags=["drive"])


@router.get("/status", response_model=DriveStatusResponse)
def drive_status(user: User = Depends(active_user), db: DatabaseDep = None):
    """Whether this user has a usable Google token stored, and its scope."""
    token = db.scalar(
        select(ProviderToken).where(
            ProviderToken.user_id == user.id,
            ProviderToken.provider == "google",
        )
    )
    if token is None or not token.access_token:
        return DriveStatusResponse(connected=False)
    return DriveStatusResponse(connected=True, scope=token.scope)


@router.get("/files", response_model=DriveFileListResponse)
async def list_drive_files(
        q: str | None = Query(None, description="Drive query, e.g. \"name contains 'report'\""),
        page_size: int = Query(DEFAULT_LIST_PAGE_SIZE, ge=1, le=MAX_LIST_PAGE_SIZE),
        page_token: str | None = Query(None),
        user: User = Depends(active_user),
        db: DatabaseDep = None,
):
    client = DriveClient(db, user.id)
    try:
        body = await client.list_files(query=q, page_size=page_size, page_token=page_token)
    except DriveNotConnected as e:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, str(e))
    except DriveTokenRefreshFailed as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    except DriveAPIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.detail)

    return DriveFileListResponse(
        files=[
            DriveFile(
                id=f["id"],
                name=f.get("name", ""),
                mime_type=f.get("mimeType", "application/octet-stream"),
                size=int(f["size"]) if f.get("size") else None,
                modified_time=f.get("modifiedTime"),
                icon_link=f.get("iconLink"),
                web_view_link=f.get("webViewLink"),
            )
            for f in body.get("files", [])
        ],
        next_page_token=body.get("nextPageToken"),
    )


@router.post(
    "/workspaces/{workspace_id}/import",
    response_model=DriveImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_drive_file(
        request: Request,
        workspace_id: uuid.UUID,
        drive_file_id: str = Query(..., description="Google Drive file id to import"),
        channel_id: uuid.UUID | None = Query(None),
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
        storage: MinIOStorage = Depends(get_storage),
):
    """Import a Drive file into the workspace and enqueue background processing.

    Reuses FileService.upload so MIME sniffing, size cap, checksum, MinIO
    upload, and DB persistence behave exactly as a direct upload.
    """
    if channel_id is not None:
        channel = db.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.workspace_id == workspace_id,
                Channel.deleted_at.is_(None),
            )
        )
        if channel is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found in workspace")

    svc = DriveImportService(db, storage, user.id)
    try:
        db_file = await svc.import_file(
            drive_file_id=drive_file_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
        )
    except DriveNotConnected as e:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, str(e))
    except DriveTokenRefreshFailed as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    except FileTooLarge:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Drive file exceeds maximum size")
    except UnsupportedFileType as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))
    except DriveAPIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.detail)

    arq_pool = getattr(request.app.state, "arq_pool", None)
    try:
        await FileService.enqueue_processing(arq_pool, db_file.id)
    except RuntimeError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File processing queue unavailable; try again later",
        )

    return DriveImportResponse(
        file_id=db_file.id,
        status=db_file.processing_status,
        filename=db_file.original_filename,
        content_type=db_file.content_type,
        size_bytes=db_file.size_bytes,
        drive_file_id=drive_file_id,
    )
