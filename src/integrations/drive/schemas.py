import uuid

from pydantic import BaseModel

from files.schemas import FileUploadResponse


class DriveFile(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int | None = None
    modified_time: str | None = None
    icon_link: str | None = None
    web_view_link: str | None = None


class DriveFileListResponse(BaseModel):
    files: list[DriveFile]
    next_page_token: str | None = None


class DriveImportRequest(BaseModel):
    drive_file_id: str
    workspace_id: uuid.UUID
    chatroom_id: uuid.UUID | None = None


class DriveImportResponse(FileUploadResponse):
    drive_file_id: str


class DriveStatusResponse(BaseModel):
    connected: bool
    scope: str | None = None
