import uuid
from datetime import datetime
from typing import Literal, Annotated

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, computed_field, ConfigDict
from sqlalchemy import update, select
from starlette import status
from starlette.requests import Request
from starlette.responses import StreamingResponse

from auth.model import ProviderToken
from auth.utils.jwt import BaseJWTClaims
from model import DatabaseDep
from .fs import GDriveFileSystem
from ...model import File, FileStatus


class UserCreds(BaseModel):
    id: uuid.UUID
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: str = ""
    token_type: str = "Bearer"

    @computed_field
    def timestamp(self) -> int | None:
        return int(self.expires_at.timestamp()) if self.expires_at else None

    model_config = ConfigDict(from_attributes=True)


class DriveClaims(BaseJWTClaims):
    user_creds_id: uuid.UUID
    file_path: str
    op: Literal["get_object", "put_object"]


router = APIRouter()


def _claims(token: str) -> DriveClaims:
    try:
        return DriveClaims.decode(token)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid token") from e


async def _fs(claims: Annotated[DriveClaims, Depends(_claims)], db: DatabaseDep) -> GDriveFileSystem:
    creds = db.get(ProviderToken, claims.user_creds_id)
    if creds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Owner not found")

    filesystem = GDriveFileSystem(user_creds=UserCreds(
        id=creds.id,
        access_token=creds.access_token,
        refresh_token=creds.refresh_token,
        expires_at=creds.expires_at.isoformat() if creds.expires_at else None,
        scopes=creds.scopes.split() if creds.scopes else [],
    ))

    updated = await filesystem.updated_creds()
    if updated.access_token != creds.access_token:
        db.execute(
            update(ProviderToken)
            .where(ProviderToken.id == creds.id)
            .values(
                access_token=updated.access_token,
                refresh_token=updated.refresh_token,
                expires_at=updated.expires_at,
            )
        )
        db.commit()

    return filesystem


@router.get("/gdrive/download")
async def stream_gdrive_download(
        fs: Annotated[GDriveFileSystem, Depends(_fs)],
        claims: Annotated[DriveClaims, Depends(_claims)],
):
    if claims.op != "get_object":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid operation for this endpoint")
    f = await fs.open_async(claims.file_path, mode="rb")
    meta = await fs._info(claims.file_path)
    return StreamingResponse(
        f.stream(),
        media_type=meta.get("content_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{meta.get("name", "file")}"',
            "Content-Length": str(meta.get("size", "")),
        },
    )


@router.put("/gdrive/upload")
async def create_gdrive_upload(
        claims: Annotated[DriveClaims, Depends(_claims)],
        fs: Annotated[GDriveFileSystem, Depends(_fs)],
        db: DatabaseDep,
        request: Request,
):
    # TODO: same interface as S3 signed URLs
    # TODO: Resumable uploads (client-side)
    if claims.op != "put_object":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid operation for this endpoint")

    async with await fs.open_async(claims.file_path, mode="wb") as f:
        async for chunk in request.stream():
            await f.write(chunk)

    file_id = f._gdrive_id  # set by _upload_chunk on final chunk

    db_file = db.execute(
        select(File).where(File.uri == fs.unstrip_protocol(claims.file_path))
    ).scalar_one_or_none()

    if db_file:
        db_file.uri = fs.unstrip_protocol(claims.file_path)
        db_file.status = FileStatus.UPLOADED
        db.commit()

    # TODO: return file meta
    return {"message": "Upload complete", "file_id": file_id}
