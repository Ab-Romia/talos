import asyncio
import functools
import hashlib
import os
import uuid

from fastapi import APIRouter, UploadFile, HTTPException, status
from sqlalchemy import select
from starlette.responses import Response

from auth.dependencies import UserDep
from config import cfg
from database import DatabaseDep
from workspace import require_perms
from .model import File, FileStatus, FileMetadata

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["documents"])


@functools.cache
def _fs():
    import s3fs

    c = cfg().minio
    endpoint = str(c.internal_endpoint)
    if not endpoint.startswith("http"):
        endpoint = f"{'https' if c.secure else 'http'}://{endpoint}"

    return s3fs.S3FileSystem(
        key=c.access_key,
        secret=c.secret_key.get_secret_value(),
        client_kwargs={"endpoint_url": endpoint},
    )


def _object_key(workspace_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{cfg().minio.bucket}/{workspace_id}/files/{file_id}/{filename}"


@router.post(
    "/documents",
    dependencies=[require_perms("files:write", "files:create")],
    status_code=status.HTTP_201_CREATED,
    response_model=FileMetadata,
)
async def upload_document(workspace_id: uuid.UUID, file: UploadFile, user: UserDep, db: DatabaseDep):
    """Upload a document to a workspace."""
    data = await file.read()

    if len(data) > cfg().minio.max_file_size:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large.")

    file_id = uuid.uuid7()
    filename = os.path.basename(file.filename or "unnamed")
    key = _object_key(workspace_id, file_id, filename)

    await asyncio.to_thread(_fs().pipe_file, key, data)

    db_file = File(
        id=file_id,
        workspace_id=workspace_id,
        uploader_id=user.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256checksum=hashlib.sha256(data).hexdigest(),
        processing_status=FileStatus.UPLOADED,
        uri=f"minio://{key}",
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    return FileMetadata.model_validate(db_file)


@router.get(
    "/documents/{file_id}",
    dependencies=[require_perms("files:read")],
)
async def download_document(workspace_id: uuid.UUID, file_id: uuid.UUID, db: DatabaseDep):
    """Download a document's contents."""
    file = db.scalar(
        select(File).where(
            File.id == file_id,
            File.workspace_id == workspace_id,
            File.deleted_at.is_(None),
        )
    )
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    key = file.uri.removeprefix("minio://")
    try:
        data = await asyncio.to_thread(_fs().cat_file, key)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File contents not found")

    return Response(
        content=data,
        media_type=file.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )
