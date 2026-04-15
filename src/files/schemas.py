import uuid
from datetime import datetime

from pydantic import BaseModel

from files.models import ProcessingStatus


class FileUploadResponse(BaseModel):
    file_id: uuid.UUID
    status: ProcessingStatus
    filename: str
    content_type: str
    size_bytes: int

    model_config = {"from_attributes": True}


class FileMetadata(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    chatroom_id: uuid.UUID | None
    uploader_id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    checksum: str
    processing_status: ProcessingStatus
    processing_error: str | None
    thumbnail_storage_key: str | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FileDownloadResponse(BaseModel):
    file_id: uuid.UUID
    filename: str
    download_url: str


class FileThumbnailResponse(BaseModel):
    file_id: uuid.UUID
    thumbnail_url: str


class FileListResponse(BaseModel):
    files: list[FileMetadata]
    next_cursor: str | None
