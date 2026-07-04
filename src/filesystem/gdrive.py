from uuid import UUID

from sqlalchemy import select, update

from auth.model import ProviderToken
from filesystem.storage.gdrive.fs import GDriveFileSystem
from filesystem.storage.gdrive.router import UserCreds

GOOGLE = "google"


def google_token_for(db, user_id: UUID) -> ProviderToken | None:
    return db.scalar(
        select(ProviderToken).where(
            ProviderToken.user_id == user_id,
            ProviderToken.provider == GOOGLE,
        )
    )


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


async def list_drive_entries(fs: GDriveFileSystem, folder_id: str | None = None) -> list[dict]:
    path = f"id:{folder_id}" if folder_id else ""
    entries = await fs._ls(path, detail=True)
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "mime_type": e.get("content_type", "application/octet-stream"),
            "size": e.get("size", 0),
            "is_folder": e.get("type") == "directory",
        }
        for e in entries
    ]


async def download_drive_bytes(fs: GDriveFileSystem, drive_id: str) -> bytes:
    handle = await fs.open_async(f"id:{drive_id}", mode="rb")
    chunks: list[bytes] = []
    async for chunk in handle.stream():
        chunks.append(chunk)
    return b"".join(chunks)
