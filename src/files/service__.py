import uuid
from typing import TYPE_CHECKING

import magic
from fastapi import HTTPException
from fsspec.asyn import AsyncFileSystem
from sqlalchemy import orm, select
from starlette import status

from config import cfg
from files import errors
from files.model import File, FileStatus, FileMetadata
from files.storage.minio import MinIOFileSystem
from utils.logger import get_logger

if TYPE_CHECKING:
    from files.router import FileCreateRequest

logger = get_logger(__name__)


async def get_download_url(db: orm.Session, filesystem: AsyncFileSystem, file_uri: str) -> str | None:
    """Return a signed GET URL and the original filename, or None if the file is not found."""
    file = db.execute(
        select(File)
        .where(File.uri == file_uri)
    ).scalar_one()

    if file.processing_status == FileStatus.PENDING:
        raise HTTPException(status.HTTP_204_NO_CONTENT)

    try:
        # TODO: abac - only allow if uploader or has workspace read perms
        url = filesystem.sign(file.uri, client_method="get_object")
    except Exception as e:
        logger.exception("Failed to generate signed download URL", file_uri=file.uri)
        raise errors.StorageError("get_url", "Failed to generate download URL") from e

    return url


# TODO: update support
async def get_upload_url(
        db: orm.Session,
        filesystem: AsyncFileSystem,
        payload: FileCreateRequest,
) -> str | None:
    """Return a signed PUT URL for the given file upload request, or None if the file record cannot be created."""
    if (isinstance(filesystem, MinIOFileSystem)
            and payload.size > cfg().minio.max_file_size):
        raise errors.FileTooLarge(payload.size, cfg().minio.max_file_size)

    if filesystem is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

    detected_mime = magic.from_buffer(payload.header, mime=True)

    db_file = File(
        channel_id=payload.channel_id,
        workspace_id=payload.workspace_id,
        uploader_id=payload.user_id,
        filename=payload.filename or "unnamed",
        content_type=detected_mime,
        size_bytes=payload.size,
        sha256checksum=payload.sha256checksum,
        processing_status=FileStatus.PENDING,
    )

    db.add(db_file)
    db.flush()

    # TODO: abac
    uri = f"{payload.parent_uri}/{db_file.filename}"

    isdir = filesystem.isdir(payload.parent_uri)
    exists = filesystem.exists(payload.parent_uri)
    duplicate = filesystem.exists(uri)

    if not exists and not isdir:
        db.rollback()
        raise errors.InvalidPath("Parent path does not exist or is not a directory")

    if duplicate:
        db.rollback()
        raise errors.AlreadyExists("A file with the same name already exists at the target location")

    signed_url = filesystem.sign(
        uri,
        operation="put_object",
        filename=db_file.filename,
        content_type=db_file.content_type,
    )

    db_file.uri = filesystem.unstrip_protocol(uri)
    try:
        db.commit()
    except Exception as e:
        # TODO:
        pass

    logger.info("Generated signed upload URL", file_id=str(db_file.id), filename=db_file.filename)
    return signed_url


async def file_info(
        db: orm.Session,
        filesystem: AsyncFileSystem,

        workspace_id: uuid.UUID,
        channel_id: uuid.UUID | None = None,
        uploader_id: uuid.UUID | None = None,

        file_uri: str | None = None,
        file_id: uuid.UUID | None = None,
        index_if_missing: bool = False,
) -> FileMetadata:
    """
    Return file metadata
    :raises FileNotFoundError: If the file doesn't exist in either DB or storage
    """
    file = None

    if file_id is not None:
        file = db.execute(
            select(File)
            .where(File.id == file_id)
        ).scalar_one()
    elif file_uri is not None:
        file = db.execute(
            select(File)
            .where(File.workspace_id == workspace_id)
            .where(File.uri == file_uri)
        ).scalar_one()

    if file is not None:
        return FileMetadata.model_validate(file)

    if file_uri is None:
        raise errors.FileNotFound("File not found in database and no URI provided for storage lookup")

    file_meta = filesystem.info(file_uri)

    # index the file if it exists in storage but not in DB (uploaded to external storage)
    file = File(
        workspace_id=workspace_id,
        channel_id=channel_id,
        uploader_id=uploader_id,
        filename=file_meta["name"],
        content_type=file_meta.get("type", "application/octet-stream"),
        size_bytes=file_meta.get("size", 0),
        sha256checksum=file_meta.get("sha256checksum"),
        processing_status=FileStatus.UPLOADED,
        uri=filesystem.unstrip_protocol(file_uri),
        created_at=file_meta.get("created_at"),
        updated_at=file_meta.get("updated_at"),
    )
    if index_if_missing:
        db.add(file)
        db.commit()

    return FileMetadata.model_validate(file)


def attach_to_message(db, file_id, message_id, uploader_id, workspace_id, channel_id):
    return NotImplementedError("attach_to_message won't be implemented")


def soft_delete(db, file_id, workspace_id):
    return None


def list_files(db, workspace_id, channel_id, content_type, cursor, limit, parent_uri=None):
    return None
