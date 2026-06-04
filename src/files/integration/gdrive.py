from contextlib import asynccontextmanager
from datetime import timedelta
from typing import BinaryIO, Literal

from aiogoogle import Aiogoogle

from files.schemas import FileMetadata
from files.storage import StorageBackend

REFRESH_LEEWAY = timedelta(seconds=60)
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_FILES_ENDPOINT = f"{DRIVE_API_BASE}/files"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_DOC_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "text/csv",
        ".csv",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}


class GDriveStorage(StorageBackend):
    """Google Drive storage backend."""

    def __init__(self, user_creds, client_creds):
        self.user_creds = user_creds
        self.client_creds = client_creds

    @asynccontextmanager
    async def client(self):
        async with Aiogoogle(user_creds=self.user_creds, client_creds=self.client_creds) as aiogoogle:
            drive_v3 = await aiogoogle.discover('drive', 'v3')
            yield aiogoogle, drive_v3

    async def list_files(self):
        async with self.client() as (aiogoogle, drive_v3):
            json_res = await aiogoogle.as_user(drive_v3.files.list(), full_res=True)

        async for page in json_res:
            for file in page["files"]:
                # TODO: yield a richer FileMetadata object here instead of raw API dicts
                yield file

    async def put(self, key: str, stream: BinaryIO, metadata: FileMetadata) -> str:
        async with self.client() as (aiogoogle, drive_v3):
            media = aiogoogle.MediaIoBaseUpload(stream, mimetype=metadata.content_type)
            req = drive_v3.files.create(
                upload_file=metadata.path,
                json={"name": metadata.original_filename},
                media_body=media,
                fields="id",
            )
            # TODO: detect mimetype

            res = await aiogoogle.as_user(req)
            return res["id"]

    async def get(self, key: str) -> BinaryIO:
        return await super().get(key)

    async def delete(self, key: str) -> None:
        return await super().delete(key)

    async def presigned_url(self, key: str, expiry: timedelta,
                            operation: Literal["get_object", "put_object"]) -> str | None:
        return await super().presigned_url(key, expiry, operation)
