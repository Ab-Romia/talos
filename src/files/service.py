"""Business logic for file operations."""

import hashlib
import os
import uuid
from datetime import datetime

import magic
from utils.datetime import utcnow
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from files.constants import ALLOWED_MIME_TYPES, MAX_FILE_SIZE, STORAGE_KEY_TEMPLATE
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.models import FileAttachment, ProcessingStatus, message_files
from files.storage import MinIOStorage
from model.messaging import Message
from utils.logger import get_logger

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
        chatroom_id: uuid.UUID | None = None,
    ) -> FileAttachment:
        """Validate, upload to MinIO, persist metadata, return FileAttachment."""
        # 1. MIME detection via magic bytes
        header = await file.read(2048)
        await file.seek(0)
        detected_mime = magic.from_buffer(header, mime=True)

        if detected_mime not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileType(detected_mime)

        # 1b. Validate chatroom belongs to workspace
        if chatroom_id is not None:
            from model.messaging import Chatroom
            chatroom = self.db.scalar(
                select(Chatroom).where(
                    Chatroom.id == chatroom_id,
                    Chatroom.workspace_id == workspace_id,
                    Chatroom.deleted_at.is_(None),
                )
            )
            if chatroom is None:
                raise ValueError(f"Chatroom {chatroom_id} not found in workspace {workspace_id}")

        # 2. Get actual file size
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0)

        if file_size > MAX_FILE_SIZE:
            raise FileTooLarge(file_size, MAX_FILE_SIZE)

        # 3. Generate storage key
        file_id = uuid.uuid4()
        ext = os.path.splitext(file.filename or "")[1].lower()
        chatroom_part = str(chatroom_id) if chatroom_id else "general"
        storage_key = STORAGE_KEY_TEMPLATE.format(
            workspace_id=workspace_id,
            chatroom_id=chatroom_part,
            file_id=file_id,
            ext=ext,
        )

        # 4. Compute checksum
        checksum = hashlib.file_digest(file.file, "sha256").hexdigest()
        file.file.seek(0)

        # 5. Upload to MinIO
        await self.storage.upload_file(
            storage_key=storage_key,
            data=file.file,
            size=file_size,
            content_type=detected_mime,
        )

        # 6. Persist metadata
        db_file = FileAttachment(
            id=file_id,
            workspace_id=workspace_id,
            chatroom_id=chatroom_id,
            uploader_id=uploader_id,
            original_filename=file.filename or "unnamed",
            content_type=detected_mime,
            size_bytes=file_size,
            storage_key=storage_key,
            checksum=checksum,
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
        chatroom_id: uuid.UUID | None = None,
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

        if chatroom_id is not None:
            query = query.where(FileAttachment.chatroom_id == chatroom_id)

        if content_type is not None:
            query = query.where(FileAttachment.content_type == content_type)

        if cursor is not None:
            # cursor format: "{created_at_iso}|{uuid}"
            try:
                ts_str, id_str = cursor.split("|", 1)
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
        """Soft-delete a file. Returns the file or None if not found."""
        file = self.get_file(file_id, workspace_id)
        if file is None:
            return None

        file.deleted_at = utcnow()
        self.db.commit()
        self.db.refresh(file)

        # Remove vector chunks from Milvus
        try:
            from rag.vector_store import delete_file_chunks
            delete_file_chunks(str(file_id))
        except Exception:
            logger.warning("Failed to delete file chunks from vector store", file_id=str(file_id))

        logger.info("File soft-deleted", file_id=str(file_id))
        return file

    def attach_to_message(
        self,
        file_id: uuid.UUID,
        message_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        """Attach an existing file to a message. Returns True on success."""
        file = self.get_file(file_id, workspace_id)
        if file is None:
            return False

        msg = self.db.scalar(
            select(Message).where(
                Message.id == message_id,
                Message.workspace_id == workspace_id,
            )
        )
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
