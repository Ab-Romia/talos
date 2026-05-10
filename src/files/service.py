"""Business logic for file operations."""

import os
import uuid
from datetime import datetime

import magic
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import cfg
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.models import FileAttachment, ProcessingStatus, message_files
from files.storage import MinIOStorage
from files.streaming import HashingReader
from model.messaging import Message
from utils.datetime import utcnow
from utils.logger import get_logger

MAX_FILE_SIZE = cfg().files.max_size
ALLOWED_MIME_TYPES = cfg().files.allowed_mime_types
DOCUMENT_MIME_TYPES = cfg().files.document_mime_types
IMAGE_MIME_TYPES = cfg().files.image_mime_types
THUMBNAIL_SIZE = cfg().files.thumbnail_size
STORAGE_KEY_TEMPLATE = cfg().files.storage_key_template

logger = get_logger(__name__)


class FileService:
    def __init__(self, db: Session, storage: MinIOStorage | None = None):
        self.db = db
        self.storage = storage

    async def upload(
            self,
            file: UploadFile,
            workspace_id: uuid.UUID,
            uploader_id: uuid.UUID,
            channel_id: uuid.UUID | None = None,
    ) -> FileAttachment:
        """Validate, upload to MinIO, persist metadata, return FileAttachment."""
        # 1. MIME detection via magic bytes
        header = await file.read(2048)
        await file.seek(0)
        detected_mime = magic.from_buffer(header, mime=True)

        if detected_mime not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileType(detected_mime)

        # 1b. Validate channel belongs to workspace
        if channel_id is not None:
            from model.messaging import Channel
            channel = self.db.scalar(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.workspace_id == workspace_id,
                    Channel.deleted_at.is_(None),
                )
            )
            if channel is None:
                raise ValueError(f"Channel {channel_id} not found in workspace {workspace_id}")

        # 2. Size from the spooled body. Starlette has fully received the
        # multipart body into UploadFile.file before this handler runs,
        # so seek/tell is authoritative.
        underlying = file.file
        underlying.seek(0, os.SEEK_END)
        file_size = underlying.tell()
        underlying.seek(0)
        if file_size > MAX_FILE_SIZE:
            raise FileTooLarge(file_size, MAX_FILE_SIZE)

        # 3. Generate storage key
        file_id = uuid.uuid4()
        ext = os.path.splitext(file.filename or "")[1].lower()
        channel_part = str(channel_id) if channel_id else "general"
        storage_key = STORAGE_KEY_TEMPLATE.format(
            workspace_id=workspace_id,
            channel_id=channel_part,
            file_id=file_id,
            ext=ext,
        )

        # 4. Stream to MinIO. minio-py reads part_size chunks at a time and
        # the wrapper hashes each chunk inline, so peak RAM is bounded by
        # part_size and we avoid a second pass over the body for SHA-256.
        reader = HashingReader(underlying)
        await self.storage.upload_file(
            storage_key=storage_key,
            data=reader,
            size=file_size,
            content_type=detected_mime,
        )

        # 5. Persist metadata
        db_file = FileAttachment(
            id=file_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            uploader_id=uploader_id,
            original_filename=file.filename or "unnamed",
            content_type=detected_mime,
            size_bytes=file_size,
            storage_key=storage_key,
            checksum=reader.checksum,
            processing_status=ProcessingStatus.UPLOADED,
        )
        self.db.add(db_file)
        self.db.commit()
        self.db.refresh(db_file)

        logger.info(
            "File uploaded",
            file_id=str(file_id),
            workspace_id=str(workspace_id),
            size=file_size,
            mime=detected_mime,
        )

        return db_file

    def get_file(
            self,
            file_id: uuid.UUID,
            workspace_id: uuid.UUID,
    ) -> FileAttachment | None:
        """Retrieve file metadata, scoped to workspace. Returns None if not found or deleted."""
        return self.db.scalar(
            select(FileAttachment).where(
                FileAttachment.id == file_id,
                FileAttachment.workspace_id == workspace_id,
                FileAttachment.deleted_at.is_(None),
            )
        )

    async def get_download_url(
            self,
            file_id: uuid.UUID,
            workspace_id: uuid.UUID,
    ) -> tuple[str, str] | None:
        """Return (download_url, filename) or None if file not found."""
        file = self.get_file(file_id, workspace_id)
        if file is None:
            return None

        url = await self.storage.generate_presigned_download_url(
            storage_key=file.storage_key,
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

    def soft_delete(
            self,
            file_id: uuid.UUID,
            workspace_id: uuid.UUID,
    ) -> FileAttachment | None:
        """Soft-delete a file. Returns the file or None if not found.

        Vector chunks are removed before the row is marked deleted so a
        failure to clean Milvus does not leave orphaned, queryable chunks
        behind a tombstoned file. Only INDEXED files have chunks to delete;
        other states are skipped.
        """
        file = self.get_file(file_id, workspace_id)
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

    def reset_for_retry(
            self,
            file_id: uuid.UUID,
            workspace_id: uuid.UUID,
    ) -> FileAttachment | None:
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

        file = self.get_file(file_id, workspace_id)
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

    async def get_thumbnail_url(
            self,
            file_id: uuid.UUID,
            workspace_id: uuid.UUID,
    ) -> str | None:
        """Return a presigned URL to the thumbnail, or None if there isn't one."""
        file = self.get_file(file_id, workspace_id)
        if file is None or not file.thumbnail_storage_key:
            return None

        return await self.storage.generate_presigned_download_url(
            storage_key=file.thumbnail_storage_key,
            original_filename=f"thumb_{file.original_filename}.jpg",
        )

    def attach_to_message(
            self,
            file_id: uuid.UUID,
            message_id: uuid.UUID,
            workspace_id: uuid.UUID,
            channel_id: uuid.UUID | None = None,
    ) -> bool:
        """Attach an existing file to a message. Returns True on success.

        When channel_id is provided, the message must belong to that
        channel — otherwise a caller could pass any channel in the URL
        and have it accepted.
        """
        file = self.get_file(file_id, workspace_id)
        if file is None:
            return False

        msg_query = select(Message).where(
            Message.id == message_id,
            Message.workspace_id == workspace_id,
        )
        if channel_id is not None:
            msg_query = msg_query.where(Message.channel_id == channel_id)

        msg = self.db.scalar(msg_query)
        if msg is None:
            return False

        # Check if already attached
        existing = self.db.execute(
            select(message_files).where(
                message_files.c.message_id == message_id,
                message_files.c.file_id == file_id,
            )
        ).first()
        if existing is not None:
            return True  # already attached, idempotent

        self.db.execute(
            message_files.insert().values(message_id=message_id, file_id=file_id)
        )
        self.db.commit()

        logger.info("File attached to message", file_id=str(file_id), message_id=str(message_id))
        return True
