"""Import Drive files through the existing FileService pipeline.

We deliberately reuse FileService.upload by wrapping the Drive download in
a Starlette UploadFile so MIME sniffing, size cap, checksum, MinIO upload,
DB persistence, and ARQ enqueue all behave identically to a direct upload.
"""

import io
import os
import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from config import cfg
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.models import FileAttachment
from files.service import FileService
from files.storage import MinIOStorage
from utils.logger import get_logger
from .client import DriveClient
from .constants import GOOGLE_DOC_EXPORTS

logger = get_logger(__name__)

MAX_FILE_SIZE = cfg().files.max_size
ALLOWED_MIME_TYPES = cfg().files.allowed_mime_types


class DriveImportService:
    def __init__(self, db: Session, storage: MinIOStorage, user_id: uuid.UUID):
        self.db = db
        self.storage = storage
        self.user_id = user_id
        self.client = DriveClient(db, user_id)

    async def import_file(
            self,
            drive_file_id: str,
            workspace_id: uuid.UUID,
            channel_id: uuid.UUID | None = None,
    ) -> FileAttachment:
        meta = await self.client.get_metadata(drive_file_id)

        drive_mime = meta.get("mimeType", "application/octet-stream")
        drive_name = meta.get("name") or "drive-file"
        declared_size = int(meta.get("size") or 0)

        # Reject non-exportable Google-native types and oversize files before download
        if drive_mime.startswith("application/vnd.google-apps.") and drive_mime not in GOOGLE_DOC_EXPORTS:
            raise UnsupportedFileType(drive_mime)
        if declared_size and declared_size > MAX_FILE_SIZE:
            raise FileTooLarge(declared_size, MAX_FILE_SIZE)

        effective_mime, ext_hint, content = await self.client.download(
            drive_file_id, drive_mime, max_bytes=MAX_FILE_SIZE
        )

        # Pre-flight: bail before MinIO + DB if the resulting MIME is unsupported.
        # FileService.upload would also catch this via magic-byte sniff, but
        # checking here lets us return a precise 415 without uploading bytes.
        if effective_mime not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileType(effective_mime)

        filename = self._derive_filename(drive_name, ext_hint)

        upload = self._wrap_as_upload_file(
            content=content, filename=filename, content_type=effective_mime
        )

        svc = FileService(self.db, self.storage)
        return await svc.upload(
            upload,
            workspace_id=workspace_id,
            uploader_id=self.user_id,
            channel_id=channel_id,
        )

    @staticmethod
    def _derive_filename(drive_name: str, ext_hint: str) -> str:
        """Apply the export extension if Drive gave us a name without one.

        Example: 'My Doc' (Google Docs) → 'My Doc.docx'. Names with an existing
        extension are kept as-is so a 'report.pdf' Drive upload stays 'report.pdf'.
        """
        if not ext_hint:
            return drive_name
        _, current_ext = os.path.splitext(drive_name)
        if current_ext:
            return drive_name
        return drive_name + ext_hint

    @staticmethod
    def _wrap_as_upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
        headers = Headers({"content-type": content_type})
        return UploadFile(
            file=io.BytesIO(content),
            filename=filename,
            headers=headers,
            size=len(content),
        )
