import uuid
from datetime import datetime, timezone
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
    from files.router import FileCreateRequest, FileUpdateRequest

logger = get_logger(__name__)


async def get_download_url(db: orm.Session, filesystem: AsyncFileSystem, file_uri: str) -> str:
    """Return a signed GET URL for the given file URI."""
    file = db.execute(
        select(File).where(File.uri == file_uri)
    ).scalar_one_or_none()

    if file is None:
        raise errors.FileNotFound(f"No DB record for URI: {file_uri}")

    if file.processing_status == FileStatus.PENDING:
        raise HTTPException(status.HTTP_204_NO_CONTENT)

    try:
        url = filesystem.sign(file.uri, client_method="get_object")
    except Exception as e:
        logger.exception("Failed to generate signed download URL", file_uri=file.uri)
        raise errors.StorageError("get_url", "Failed to generate download URL") from e

    return url


async def get_upload_url(
        db: orm.Session,
        filesystem: AsyncFileSystem,
        payload: "FileCreateRequest",
) -> str:
    """
    Create a DB record and return a signed PUT URL.
    Raises FileTooLarge, InvalidPath, AlreadyExists, StorageError.
    """
    if isinstance(filesystem, MinIOFileSystem) and payload.size > cfg().minio.max_file_size:
        raise errors.FileTooLarge(payload.size, cfg().minio.max_file_size)

    if filesystem is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No filesystem available")

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
    db.flush()  # populate db_file.id without committing

    # TODO: abac
    uri = f"{payload.parent_uri}/{db_file.filename}"

    parent_exists = filesystem.exists(payload.parent_uri)
    parent_is_dir = filesystem.isdir(payload.parent_uri)
    duplicate = filesystem.exists(uri)

    if not parent_exists or not parent_is_dir:
        db.rollback()
        raise errors.InvalidPath("Parent path does not exist or is not a directory")

    if duplicate:
        db.rollback()
        raise errors.AlreadyExists("File with same name already exists at target location")

    try:
        signed_url = filesystem.sign(
            uri,
            operation="put_object",
            filename=db_file.filename,
            content_type=db_file.content_type,
        )
    except Exception as e:
        db.rollback()
        logger.exception("Failed to generate signed upload URL", file_id=str(db_file.id))
        raise errors.StorageError("put_url", "Failed to generate upload URL") from e

    db_file.uri = filesystem.unstrip_protocol(uri)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("DB commit failed after generating upload URL", file_id=str(db_file.id))
        raise errors.StorageError("db_commit", "Failed to persist file record") from e

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
    Return file metadata, optionally indexing files found in storage but not in DB.

    Lookup order: file_id → file_uri → storage.
    Raises FileNotFound if not found in DB or storage.
    """
    file = None

    if file_id is not None:
        file = db.execute(
            select(File)
            .where(File.id == file_id)
            .where(File.workspace_id == workspace_id)
            .where(File.deleted_at.is_(None))
        ).scalar_one_or_none()
    elif file_uri is not None:
        file = db.execute(
            select(File)
            .where(File.workspace_id == workspace_id)
            .where(File.uri == file_uri)
            .where(File.deleted_at.is_(None))
        ).scalar_one_or_none()

    if file is not None:
        return FileMetadata.model_validate(file)

    if file_uri is None:
        raise errors.FileNotFound("File not found in database and no URI provided for storage lookup")

    # File exists in storage but not DB — happens for externally-uploaded objects.
    try:
        file_meta = filesystem.info(file_uri)
    except FileNotFoundError as e:
        raise errors.FileNotFound(f"File not found in DB or storage: {file_uri}") from e

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
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception("Failed to index externally-uploaded file", file_uri=file_uri)
            raise errors.StorageError("index", "Failed to index file") from e

    return FileMetadata.model_validate(file)


def list_files(
        db: orm.Session,
        workspace_id: uuid.UUID,
        channel_id: uuid.UUID | None,
        content_type: str | None,
        cursor: str | None,
        limit: int,
        parent_uri: str | None = None,
) -> tuple[list[File], str | None]:
    """
    Return (files, next_cursor). Cursor is the stringified UUID of the last seen file.
    Soft-deleted files are excluded. Filters: workspace, optional channel, optional
    content_type prefix, optional parent_uri (directory listing).
    """
    q = (
        select(File)
        .where(File.workspace_id == workspace_id)
        .where(File.deleted_at.is_(None))
        .order_by(File.id)
    )

    if channel_id is not None:
        q = q.where(File.channel_id == channel_id)

    if content_type is not None:
        # Support prefix match: "image/" matches "image/png", "image/jpeg", etc.
        if content_type.endswith("/"):
            q = q.where(File.content_type.like(f"{content_type}%"))
        else:
            q = q.where(File.content_type == content_type)

    if parent_uri is not None:
        q = q.where(File.uri.like(f"{parent_uri}/%"))

    if cursor is not None:
        try:
            cursor_id = uuid.UUID(cursor)
            q = q.where(File.id > cursor_id)
        except ValueError:
            logger.warning("Invalid cursor value ignored", cursor=cursor)

    q = q.limit(limit + 1)
    rows = db.execute(q).scalars().all()

    has_next = len(rows) > limit
    page = rows[:limit]
    next_cursor = str(page[-1].id) if has_next and page else None

    return list(page), next_cursor


async def update_file_meta(
        db: orm.Session,
        file_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: "FileUpdateRequest",
) -> FileMetadata:
    """Partial update of mutable metadata fields (currently: filename)."""
    file = db.execute(
        select(File)
        .where(File.id == file_id)
        .where(File.workspace_id == workspace_id)
        .where(File.deleted_at.is_(None))
    ).scalar_one_or_none()

    if file is None:
        raise errors.FileNotFound(f"File {file_id} not found in workspace {workspace_id}")

    if payload.filename is not None:
        file.filename = payload.filename

    file.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("update_file_meta commit failed", file_id=str(file_id))
        raise errors.StorageError("db_commit", "Failed to persist metadata update") from e

    return FileMetadata.model_validate(file)


async def replace_file(
        db: orm.Session,
        filesystem: AsyncFileSystem,
        file_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: "FileCreateRequest",
) -> str:
    """
    Soft-delete the existing record and create a new one, returning a signed upload URL.
    Preserves file_id lineage via soft-delete rather than in-place mutation.
    """
    existing = db.execute(
        select(File)
        .where(File.id == file_id)
        .where(File.workspace_id == workspace_id)
        .where(File.deleted_at.is_(None))
    ).scalar_one_or_none()

    if existing is None:
        raise errors.FileNotFound(f"File {file_id} not found in workspace {workspace_id}")

    existing.deleted_at = datetime.now(timezone.utc)
    db.flush()

    return await get_upload_url(db, filesystem, payload)


def soft_delete(
        db: orm.Session,
        file_id: uuid.UUID,
        workspace_id: uuid.UUID,
) -> File | None:
    """
    Set deleted_at on the file record. Returns the updated record or None if not found.
    Does not remove storage objects — physical deletion is handled async by a background job.
    """
    file = db.execute(
        select(File)
        .where(File.id == file_id)
        .where(File.workspace_id == workspace_id)
        .where(File.deleted_at.is_(None))
    ).scalar_one_or_none()

    if file is None:
        return None

    file.deleted_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("soft_delete commit failed", file_id=str(file_id))
        raise

    logger.info("File soft-deleted", file_id=str(file_id))
    return file
