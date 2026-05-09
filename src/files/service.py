"""Business logic for file operations."""

import hashlib
import io
import os
import uuid
from datetime import datetime

import magic
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import cfg
from files.exceptions import FileTooLarge, StorageError, UnsupportedFileType
from files.model import FileAttachment, ProcessingStatus, MessageFile
from files.storage import MinIOStorage
from files.streaming import HashingReader
from model.messaging import Message
from utils.datetime import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_FILE_SIZE = cfg().files.max_size
ALLOWED_MIME_TYPES = cfg().files.allowed_mime_types
DOCUMENT_MIME_TYPES = cfg().files.document_mime_types
IMAGE_MIME_TYPES = cfg().files.image_mime_types
THUMBNAIL_SIZE = cfg().files.thumbnail_size


class FileService:
    def __init__(self, db: Session, storage: MinIOStorage | None = None):
        self.db = db
        self.storage = storage

    async def upload(self,
                     file: UploadFile,
                     uploader_id: uuid.UUID,
                     workspace_id: uuid.UUID | None = None,
                     channel_id: uuid.UUID | None = None
                     ) -> FileAttachment:
        """
            Upload a file and persist metadata.
            Channel-scoped if channel_id is provided (ignores workspace_id).
            Otherwise, workspace-scoped and channel_id is ignored (but workspace_id is required).
        """
        if workspace_id is None and channel_id is None:
            raise ValueError("Either workspace_id or channel_id must be provided")

        detected_mime = await self._validate_mime_type(file)

        db_file = FileAttachment(
            channel_id=channel_id,
            workspace_id=workspace_id,
            uploader_id=uploader_id,
            original_filename=file.filename or "unnamed",
            content_type=detected_mime,
            size_bytes=0,
            checksum="",
            processing_status=ProcessingStatus.UPLOADED,
        )
        self.db.add(db_file)
        self.db.flush()

        try:
            file_size, checksum = await self._upload(file, db_file.id.hex, detected_mime)
        except FileTooLarge, StorageError:
            self.db.rollback()
            raise

        db_file.size_bytes = file_size
        db_file.checksum = checksum

        self.db.commit()

        logger.info("File uploaded",
                    file_id=str(db_file.id),
                    filename=db_file.original_filename,
                    content_type=db_file.content_type,
                    size_bytes=db_file.size_bytes)
        return db_file

    @staticmethod
    async def _validate_mime_type(file: UploadFile) -> str | None:
        """
        Detect MIME type from the file header and validate against allowed types.
        """
        detected_mime = magic.from_descriptor(file.file.fileno(), mime=True)

        if detected_mime not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileType(detected_mime)

        return detected_mime

    async def _upload(self, file: UploadFile, key: str, mime: str) -> tuple[int, str]:
        """Upload file bytes to object storage under a precomputed key."""
        # TODO: Verify this:
        # Size from the spooled body. Starlette has fully received the
        # multipart body into UploadFile.file before this handler runs,
        # so seek/tell is authoritative.
        underlying = file.file
        underlying.seek(0, os.SEEK_END)
        file_size = underlying.tell()
        underlying.seek(0)
        if file_size > MAX_FILE_SIZE:
            raise FileTooLarge(file_size, MAX_FILE_SIZE)

        reader = HashingReader(underlying)
        await self.storage.upload_file(
            storage_key=key,
            data=reader,
            size=file_size,
            content_type=mime,
        )

        return file_size, reader.checksum

    def get_file(self, file_id: uuid.UUID) -> FileAttachment | None:
        """Retrieve file metadata, scoped to workspace. Returns None if not found or deleted."""
        return self.db.scalar(
            select(FileAttachment)
            .where(FileAttachment.id == file_id,
                   FileAttachment.deleted_at.is_(None))
        )

    async def get_download_url(self, file_id: uuid.UUID) -> tuple[str, str] | None:
        """Return (download_url, filename) or None if a file not found."""
        file = self.get_file(file_id)
        if file is None:
            return None

        url = await self.storage.generate_presigned_download_url(
            storage_key=file.id.hex,
            original_filename=file.original_filename,
        )
        return url, file.original_filename

    def list_files(
            self,
            workspace_id: uuid.UUID,
            channel_id: uuid.UUID | None = None,
            content_type: str | None = None,
            cursor: str | None = None,
            limit: int = 20,
    ) -> tuple[list[FileAttachment], str | None]:
        """List files with cursor-based pagination. Returns (files, next_cursor)."""
        query = (
            select(FileAttachment)
            .where(
                FileAttachment.workspace_id == workspace_id,
                FileAttachment.deleted_at.is_(None),
            )
            .order_by(FileAttachment.created_at.desc(), FileAttachment.id.desc())
            .limit(limit + 1)
        )

        if channel_id is not None:
            query = query.where(FileAttachment.channel_id == channel_id)

        if content_type is not None:
            query = query.where(FileAttachment.content_type == content_type)

        if cursor is not None:
            # cursor format: "{created_at_iso}|{uuid}"
            try:
                ts_str, id_str = cursor.split("|", 1)
                # URL decoding converts "+" in the tz offset (e.g. "+00:00") to a space,
                # so put it back before parsing the ISO timestamp.
                ts_str = ts_str.replace(" ", "+")
                cursor_ts = datetime.fromisoformat(ts_str)
                cursor_id = uuid.UUID(id_str)
                query = query.where(
                    (FileAttachment.created_at < cursor_ts)
                    | (
                            (FileAttachment.created_at == cursor_ts)
                            & (FileAttachment.id < cursor_id)
                    )
                )
            except (ValueError, TypeError):
                pass  # invalid cursor, ignore

        results = list(self.db.scalars(query).all())

        next_cursor = None
        if len(results) > limit:
            results = results[:limit]
            last = results[-1]
            next_cursor = f"{last.created_at.isoformat()}|{last.id}"

        return results, next_cursor

    def soft_delete(self, file_id: uuid.UUID, workspace_id: uuid.UUID) -> FileAttachment | None:
        """Soft-delete a file. Returns the file or None if not found.

        Vector chunks are removed before the row is marked deleted so a
        failure to clean Milvus does not leave orphaned, queryable chunks
        behind a tombstoned file. Only INDEXED files have chunks to delete;
        other states are skipped.
        """
        file = self.get_file(file_id)
        if file is None:
            return None

        if file.processing_status == ProcessingStatus.INDEXED:
            from rag.vector_store import delete_file_chunks
            try:
                delete_file_chunks(str(file_id), workspace_id=str(workspace_id))
            except Exception as e:
                logger.error(
                    "Failed to delete file chunks from vector store; aborting soft-delete",
                    file_id=str(file_id),
                    error=str(e),
                )
                raise

        file.deleted_at = utcnow()
        self.db.commit()
        self.db.refresh(file)

        logger.info("File soft-deleted", file_id=str(file_id))
        return file

    @staticmethod
    async def enqueue_processing(arq_pool, file_id: uuid.UUID) -> None:
        """Enqueue the background processing job for a file.

        Raises RuntimeError if the ARQ pool is unavailable so the caller
        can translate that to an HTTP error. Using the file id as the ARQ
        job id keeps enqueues idempotent per file.
        """
        if arq_pool is None:
            raise RuntimeError("ARQ pool not available")
        await arq_pool.enqueue_job(
            "process_file",
            str(file_id),
            _job_id=f"process_{file_id}",
        )

    def reset_for_retry(self, file_id: uuid.UUID) -> FileAttachment | None:
        """Reset a file so it can be reprocessed.

        Returns the file flipped back to UPLOADED, or None if missing.
        Raises ValueError when the file is INDEXED (nothing to retry) or
        when it is genuinely still being processed by a live worker
        (PROCESSING with a recent updated_at). PROCESSING rows whose
        updated_at is older than the stuck threshold are treated as
        crashed-worker leftovers and reclaimed by this call so the user
        does not have to wait for the periodic sweep.
        """
        from processing.worker import STUCK_AGE
        from utils.datetime import utcnow

        file = self.get_file(file_id)
        if file is None:
            return None
        if file.processing_status == ProcessingStatus.INDEXED:
            raise ValueError("Cannot retry file in indexed state")
        if file.processing_status == ProcessingStatus.PROCESSING:
            age = utcnow() - file.updated_at
            if age < STUCK_AGE:
                raise ValueError("Cannot retry file in processing state")

        file.processing_status = ProcessingStatus.UPLOADED
        file.processing_error = None
        file.chunk_count = None
        self.db.commit()
        self.db.refresh(file)
        return file

    async def get_thumbnail_url(self, file_id: uuid.UUID) -> str | None:
        """Return a presigned URL to the thumbnail, or None if there isn't one."""
        file = self.get_file(file_id)
        if file is None:
            return None

        return await self.storage.generate_presigned_download_url(
            storage_key=file.id.hex,
            original_filename=f"thumb_{file.original_filename}.jpg",
        )

    def attach_to_message(self, file_id: uuid.UUID, message_id: uuid.UUID, ) -> bool:
        """Attach an existing file to a message. Returns True on success.

        When channel_id is provided, the message must belong to that
        channel — otherwise a caller could pass any channel in the URL
        and have it accepted.
        """
        file = self.get_file(file_id)
        if file is None:
            return False

        msg = self.db.get(Message, message_id)

        if msg is None:
            return False

        # Check if already attached (idempotent)
        if self.db.get(MessageFile, (message_id, file_id)) is not None:
            return True

        mf = MessageFile(message_id=message_id, file_id=file_id, )
        self.db.add(mf)
        self.db.commit()

        logger.info("File attached to message", file_id=str(file_id), message_id=str(message_id))

        return True
