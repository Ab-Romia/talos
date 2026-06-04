"""File upload and management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from auth import UserDep
from auth.utils.session import verified_session
from config import cfg
from files.dependencies import get_storage, StorageDep
from files.errors import FileTooLarge, UnsupportedFileType
from files.schemas import (
    FileDownloadResponse,
    FileListResponse,
    FileMetadata,
    FileThumbnailResponse,
    FileUploadResponse,
)
from files.service import FileService
from files.storage import S3Storage
from model import DatabaseDep
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/workspaces/{workspace_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_file(
        request: Request,
        db: DatabaseDep,
        workspace_id: uuid.UUID,
        file: Annotated[UploadFile, File(...)],
        user: UserDep,
        storage: Annotated[S3Storage, Depends(get_storage)],
        channel_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Upload a file to a workspace. MIME type is validated via magic bytes."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > cfg().files.max_size:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds maximum size")

    svc = FileService(db, storage)
    try:
        db_file = await svc.upload(file, workspace_id, user.id, channel_id)
    except FileTooLarge:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds maximum size")
    except UnsupportedFileType as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    # Enqueue background processing
    arq_pool = getattr(request.app.state, "arq_pool", None)
    try:
        await FileService.enqueue_processing(arq_pool, db_file.id)
    except RuntimeError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File processing queue unavailable; try again later",
        )

    return FileUploadResponse(
        file_id=db_file.id,
        status=db_file.processing_status,
        filename=db_file.original_filename,
        content_type=db_file.content_type,
        size_bytes=db_file.size_bytes,
    )


@router.get(
    "/workspaces/{workspace_id}/files/{file_id}/metadata",
    response_model=FileMetadata,
    dependencies=[Depends(verified_session)],
)
def get_file_metadata(file_id: uuid.UUID, db: DatabaseDep):
    """Get metadata for a single file."""
    svc = FileService(db, storage=None)
    file = svc.get_file(file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileMetadata.model_validate(file)


@router.get(
    "/workspaces/{workspace_id}/files/{file_id}",
    response_model=FileDownloadResponse,
    dependencies=[Depends(verified_session)],
)
async def download_file(
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        storage: Annotated[S3Storage, Depends(get_storage)],
        db: DatabaseDep,
):
    """Generate a pre-signed download URL for a file."""
    svc = FileService(db, storage)
    result = await svc.get_download_url(file_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    url, filename = result
    return FileDownloadResponse(file_id=file_id, filename=filename, download_url=url)


# --- Thumbnail (pre-signed URL) ---

@router.get(
    "/workspaces/{workspace_id}/files/{file_id}/thumbnail",
    response_model=FileThumbnailResponse,
    dependencies=[Depends(verified_session)]
)
async def get_file_thumbnail(file_id: uuid.UUID, storage: StorageDep, db: DatabaseDep):
    """Return a pre-signed URL to the file's generated thumbnail, if any."""
    svc = FileService(db, storage)
    url = await svc.get_thumbnail_url(file_id)
    if url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thumbnail not found")
    return FileThumbnailResponse(file_id=file_id, thumbnail_url=url)


# --- Retry processing ---

@router.post(
    "/workspaces/{workspace_id}/files/{file_id}/retry",
    response_model=FileMetadata,
    dependencies=[Depends(verified_session)],
)
async def retry_file_processing(request: Request, file_id: uuid.UUID, db: DatabaseDep):
    """Re-enqueue a file for processing. Valid for UPLOADED and FAILED states."""
    svc = FileService(db, storage=None)
    try:
        file = svc.reset_for_retry(file_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))

    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    arq_pool = getattr(request.app.state, "arq_pool", None)
    try:
        await FileService.enqueue_processing(arq_pool, file.id)
    except RuntimeError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File processing queue unavailable; try again later",
        )

    return FileMetadata.model_validate(file)


# --- Processing status ---

@router.get(
    "/workspaces/{workspace_id}/files/{file_id}/status",
    dependencies=[Depends(verified_session)],
)
def get_file_status(file_id: uuid.UUID, db: DatabaseDep):
    """Get the processing status of a file."""
    svc = FileService(db, storage=None)
    file = svc.get_file(file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return {
        "file_id": str(file.id),
        "processing_status": file.processing_status.value,
        "processing_error": file.processing_error,
        "chunk_count": file.chunk_count,
    }


@router.get(
    "/workspaces/{workspace_id}/files",
    response_model=FileListResponse,
    dependencies=[Depends(verified_session)],
)
def list_files(
        workspace_id: uuid.UUID,
        db: DatabaseDep,
        channel_id: Annotated[uuid.UUID | None, Query()] = None,
        content_type: Annotated[str | None, Query()] = None,
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List files in a workspace with cursor-based pagination."""
    svc = FileService(db, storage=None)
    files, next_cursor = svc.list_files(
        workspace_id=workspace_id,
        channel_id=channel_id,
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
    dependencies=[Depends(verified_session)],
)
def delete_file(
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        db: DatabaseDep,
):
    """Soft-delete a file (sets deleted_at)."""
    svc = FileService(db, storage=None)
    try:
        file = svc.soft_delete(file_id, workspace_id)
    except Exception:
        logger.exception("soft_delete failed", file_id=str(file_id))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Vector store unavailable; file not deleted",
        )
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileMetadata.model_validate(file)


# --- Attach file to message ---

@router.post(
    "/workspaces/{workspace_id}/channels/{channel_id}/messages/{message_id}/files",
    dependencies=[Depends(verified_session)]
)
def attach_file_to_message(
        message_id: uuid.UUID,
        file_id: Annotated[uuid.UUID, Query(...)],
        db: DatabaseDep,
):
    """Attach an existing file to a message."""
    svc = FileService(db, storage=None)
    success = svc.attach_to_message(file_id, message_id)
    if not success:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File or message not found")
    return {"status": "attached", "file_id": str(file_id), "message_id": str(message_id)}
