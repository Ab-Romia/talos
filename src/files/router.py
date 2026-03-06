"""File upload and management endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from backend.auth.dependencies import active_user
from files.constants import MAX_FILE_SIZE
from files.dependencies import get_storage, get_workspace_member
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.schemas import FileDownloadResponse, FileListResponse, FileMetadata, FileUploadResponse
from files.service import FileService
from files.storage import MinIOStorage
from model.base import DatabaseDep
from model.identity import User
from model.messaging import Workspace

router = APIRouter()


# --- Upload ---

@router.post(
    "/workspaces/{workspace_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file(
    request: Request,
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    chatroom_id: uuid.UUID | None = Query(None),
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
    storage: MinIOStorage = Depends(get_storage),
):
    """Upload a file to a workspace. MIME type is validated via magic bytes."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds maximum size")

    svc = FileService(db, storage)
    try:
        db_file = await svc.upload(file, workspace_id, user.id, chatroom_id)
    except FileTooLarge:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds maximum size")
    except UnsupportedFileType as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))

    # Enqueue background processing
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        await arq_pool.enqueue_job("process_file", str(db_file.id), _job_id=f"process_{db_file.id}")

    return FileUploadResponse(
        file_id=db_file.id,
        status=db_file.processing_status,
        filename=db_file.original_filename,
        content_type=db_file.content_type,
        size_bytes=db_file.size_bytes,
    )


# --- Get metadata ---

@router.get(
    "/workspaces/{workspace_id}/files/{file_id}",
    response_model=FileMetadata,
)
def get_file_metadata(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    """Get metadata for a single file."""
    svc = FileService(db, storage=None)
    file = svc.get_file(file_id, workspace_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileMetadata.model_validate(file)


# --- Download (pre-signed URL) ---

@router.get(
    "/workspaces/{workspace_id}/files/{file_id}/download",
    response_model=FileDownloadResponse,
)
async def download_file(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
    storage: MinIOStorage = Depends(get_storage),
):
    """Generate a pre-signed download URL for a file."""
    svc = FileService(db, storage)
    result = await svc.get_download_url(file_id, workspace_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    url, filename = result
    return FileDownloadResponse(file_id=file_id, filename=filename, download_url=url)


# --- Processing status ---

@router.get(
    "/workspaces/{workspace_id}/files/{file_id}/status",
)
def get_file_status(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    """Get the processing status of a file."""
    svc = FileService(db, storage=None)
    file = svc.get_file(file_id, workspace_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return {
        "file_id": str(file.id),
        "processing_status": file.processing_status.value,
        "processing_error": file.processing_error,
        "chunk_count": file.chunk_count,
    }


# --- List files ---

@router.get(
    "/workspaces/{workspace_id}/files",
    response_model=FileListResponse,
)
def list_files(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID | None = Query(None),
    content_type: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    """List files in a workspace with cursor-based pagination."""
    svc = FileService(db, storage=None)
    files, next_cursor = svc.list_files(
        workspace_id=workspace_id,
        chatroom_id=chatroom_id,
        content_type=content_type,
        cursor=cursor,
        limit=limit,
    )
    return FileListResponse(
        files=[FileMetadata.model_validate(f) for f in files],
        next_cursor=next_cursor,
    )


# --- Soft delete ---

@router.delete(
    "/workspaces/{workspace_id}/files/{file_id}",
    response_model=FileMetadata,
)
def delete_file(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    """Soft-delete a file (sets deleted_at)."""
    svc = FileService(db, storage=None)
    file = svc.soft_delete(file_id, workspace_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileMetadata.model_validate(file)


# --- Attach file to message ---

@router.post(
    "/workspaces/{workspace_id}/chatrooms/{chatroom_id}/messages/{message_id}/files",
    status_code=status.HTTP_200_OK,
)
def attach_file_to_message(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID,
    message_id: uuid.UUID,
    file_id: uuid.UUID = Query(...),
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    """Attach an existing file to a message."""
    svc = FileService(db, storage=None)
    success = svc.attach_to_message(file_id, message_id, workspace_id)
    if not success:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File or message not found")
    return {"status": "attached", "file_id": str(file_id), "message_id": str(message_id)}
