from uuid import UUID

from authlib.integrations.base_client.errors import OAuthError
from sqlalchemy import select, update

from auth.model import ProviderToken
from filesystem.storage.gdrive.fs import GDriveFileSystem
from filesystem.storage.gdrive.router import UserCreds

GOOGLE = "google"


class DriveAuthError(Exception):
    """Drive is not usable — either never connected, or the stored token is
    expired and can't be refreshed (no refresh token). The caller should ask
    the user to (re)connect Google Drive."""


def google_token_for(db, user_id: UUID) -> ProviderToken | None:
    return db.scalar(
        select(ProviderToken).where(
            ProviderToken.user_id == user_id,
            ProviderToken.provider == GOOGLE,
        )
    )


async def get_drive_fs(db, user_id: UUID) -> GDriveFileSystem:
    """Build a ready Drive filesystem for the user, or raise DriveAuthError when
    the connection is missing or unrecoverably expired."""
    token = google_token_for(db, user_id)
    if token is None:
        raise DriveAuthError("not_connected")
    try:
        return await make_gdrive_fs(db, token)
    except (OAuthError, ValueError) as e:
        # InvalidTokenError (an OAuthError subclass) is raised when the access
        # token is expired and there's no usable refresh token.
        raise DriveAuthError("reconnect") from e


async def make_gdrive_fs(db, token: ProviderToken) -> GDriveFileSystem:
    fs = GDriveFileSystem(
        user_creds=UserCreds(
            id=token.id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=token.expires_at.isoformat() if token.expires_at else None,
            scopes=token.scopes or "",
        )
    )

    updated = await fs.updated_creds()
    if updated.access_token != token.access_token:
        db.execute(
            update(ProviderToken)
            .where(ProviderToken.id == token.id)
            .values(
                access_token=updated.access_token,
                refresh_token=updated.refresh_token,
                expires_at=updated.expires_at,
            )
        )
        db.commit()

    return fs


_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".mpeg", ".mpg")


def is_video_file(name: str, mime_type: str) -> bool:
    """Video files carry no text layer and can't be OCR'd — never indexable."""
    if (mime_type or "").startswith("video/"):
        return True
    return (name or "").lower().endswith(_VIDEO_EXTS)


async def list_drive_entries(fs: GDriveFileSystem, folder_id: str | None = None) -> list[dict]:
    path = f"id:{folder_id}" if folder_id else ""
    entries = await fs._ls(path, detail=True)
    items = [
        {
            "id": e["id"],
            "name": e["name"],
            "mime_type": e.get("content_type", "application/octet-stream"),
            "size": e.get("size", 0),
            "is_folder": e.get("type") == "directory",
            "modified": e.get("modified"),
            "created": e.get("created"),
        }
        for e in entries
    ]
    # Videos can't be indexed for RAG — hide them from the picker (keep folders).
    items = [it for it in items if it["is_folder"] or not is_video_file(it["name"], it["mime_type"])]
    # Two stable sorts → folders first, newest-modified first within each group.
    # Drive timestamps are ISO-8601, so string ordering matches chronological.
    items.sort(key=lambda x: x.get("modified") or "", reverse=True)
    items.sort(key=lambda x: not x["is_folder"])
    return items


async def download_drive_bytes(fs: GDriveFileSystem, drive_id: str) -> bytes:
    handle = await fs.open_async(f"id:{drive_id}", mode="rb")
    chunks: list[bytes] = []
    async for chunk in handle.stream():
        chunks.append(chunk)
    return b"".join(chunks)
