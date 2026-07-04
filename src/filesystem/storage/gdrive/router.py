import uuid
from datetime import datetime, timezone, timedelta
from typing import Literal, Annotated

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import delete, select, update
from starlette import status
from starlette.responses import RedirectResponse, StreamingResponse

from auth.model import GDriveConnection, GDriveOwnerType
from auth.oauth import oauth
from auth.utils.jwt import BaseJWTClaims
from auth.utils.session import NewSessionDep, UnverifiedSessionDep
from database import DatabaseDep
from .fs import GDriveFileSystem
from ...model import File, FileStatus


class UserCreds(BaseModel):
    id: uuid.UUID
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    token_type: str = "Bearer"

    @computed_field
    def timestamp(self) -> int | None:
        return int(self.expires_at.timestamp()) if self.expires_at else None

    model_config = ConfigDict(from_attributes=True)


class DriveClaims(BaseJWTClaims):
    owner_type: GDriveOwnerType
    owner_id: uuid.UUID
    file_path: str
    op: Literal["get_object", "put_object"]


class GDriveConnectState(BaseJWTClaims):
    owner_type: GDriveOwnerType
    owner_id: uuid.UUID
    user_id: uuid.UUID


class RootFolderIn(BaseModel):
    folder_id: str
    folder_name: str


class PickerItem(BaseModel):
    file_id: str
    is_folder: bool = False


class ShareItemsIn(BaseModel):
    items: list[PickerItem]


router = APIRouter()
gdrive_oauth_router = APIRouter(prefix="/gdrive", tags=["gdrive"])


def _expires_at(token: dict) -> datetime | None:
    if token.get("expires_at"):
        return datetime.fromtimestamp(token["expires_at"], tz=timezone.utc)
    if token.get("expires_in"):
        return datetime.now(timezone.utc) + timedelta(seconds=int(token["expires_in"]))
    return None


def _file_owner_kwargs(owner_type: GDriveOwnerType, owner_id: uuid.UUID) -> dict:
    return {"channel_id": owner_id} if owner_type == GDriveOwnerType.channel else {"workspace_id": owner_id}


def _filesystem_from_connection(conn: GDriveConnection) -> GDriveFileSystem:
    return GDriveFileSystem(
        user_creds=UserCreds(
            id=conn.id,
            access_token=conn.access_token,
            refresh_token=conn.refresh_token,
            expires_at=conn.expires_at,
            scopes=conn.scope.split() if conn.scope else [],
        ),
        owner_type=conn.owner_type,
        owner_id=conn.owner_id,
    )


def _claims(token: str) -> DriveClaims:
    try:
        return DriveClaims.decode(token)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid token") from e


async def _fs(claims: Annotated[DriveClaims, Depends(_claims)], db: DatabaseDep) -> GDriveFileSystem:
    conn = db.scalar(
        select(GDriveConnection)
        .where(GDriveConnection.owner_type == claims.owner_type)
        .where(GDriveConnection.owner_id == claims.owner_id)
    )
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drive not connected")

    filesystem = _filesystem_from_connection(conn)

    updated = await filesystem.updated_creds()
    if updated.access_token != conn.access_token:
        db.execute(
            update(GDriveConnection)
            .where(GDriveConnection.id == conn.id)
            .values(
                access_token=updated.access_token,
                refresh_token=updated.refresh_token,
                expires_at=updated.expires_at,
            )
        )
        db.commit()

    return filesystem


@gdrive_oauth_router.get("/oauth/callback", name="gdrive_oauth_callback")
async def gdrive_oauth_callback(request: Request, session: NewSessionDep, db: DatabaseDep):
    state = request.query_params.get("state")
    try:
        claims = GDriveConnectState.decode(state)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired state") from e

    client = oauth.create_client("google")
    request.scope["session"] = session.model_extra
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google authentication failed") from e

    session.model_extra.clear()
    session.model_extra.update(request.session)

    existing = db.scalar(
        select(GDriveConnection)
        .where(GDriveConnection.owner_type == claims.owner_type)
        .where(GDriveConnection.owner_id == claims.owner_id)
    )
    refresh_token = token.get("refresh_token") or (existing.refresh_token if existing else None)
    expires_at = _expires_at(token)

    if existing is None:
        db.add(GDriveConnection(
            owner_type=claims.owner_type,
            owner_id=claims.owner_id,
            access_token=token["access_token"],
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=token.get("scope"),
            connected_by_user_id=claims.user_id,
        ))
    else:
        existing.access_token = token["access_token"]
        existing.refresh_token = refresh_token
        existing.expires_at = expires_at
        existing.scope = token.get("scope") or existing.scope
    db.commit()

    return RedirectResponse(
        url=f"/settings/{claims.owner_type.value}/{claims.owner_id}/gdrive/select-folder",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def gdrive_settings_router(owner_type: GDriveOwnerType, id_param: str) -> APIRouter:
    r = APIRouter(prefix="/gdrive", tags=["gdrive"])

    def _owner_id(request: Request) -> uuid.UUID:
        return uuid.UUID(request.path_params[id_param])

    OwnerId = Annotated[uuid.UUID, Depends(_owner_id)]

    def _connection(db: DatabaseDep, owner_id: OwnerId) -> GDriveConnection:
        conn = db.scalar(
            select(GDriveConnection)
            .where(GDriveConnection.owner_type == owner_type)
            .where(GDriveConnection.owner_id == owner_id)
        )
        if conn is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Drive not connected")
        return conn

    Connection = Annotated[GDriveConnection, Depends(_connection)]

    @r.get("/connect")
    async def connect(owner_id: OwnerId, request: Request, session: UnverifiedSessionDep):  # + admin-permission dep
        if session.sub is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
        state = GDriveConnectState(
            owner_type=owner_type,
            owner_id=owner_id,
            user_id=session.sub,
        ).encode()
        client = oauth.create_client("google")
        request.scope["session"] = {}
        res = await client.authorize_redirect(
            request,
            request.url_for("gdrive_oauth_callback"),
            scope="openid email https://www.googleapis.com/auth/drive.file",
            access_type="offline",
            prompt="consent",
            state=state,
        )
        session.model_extra.update(request.session or {})
        return res

    @r.post("/root-folder")
    async def set_root_folder(body: RootFolderIn, conn: Connection, db: DatabaseDep):  # + admin dep
        conn.root_folder_id = body.folder_id
        conn.root_folder_name = body.folder_name
        db.commit()
        return {"message": "Root folder set"}

    @r.post("/share")
    async def share_items(body: ShareItemsIn, owner_id: OwnerId, conn: Connection, db: DatabaseDep):  # + admin dep
        fs = _filesystem_from_connection(conn)
        registered = []
        for item in body.items:
            path = f"id:{item.file_id}"
            meta = await fs._info(path)
            db.add(File(
                uri=fs.unstrip_protocol(path),
                filename=meta.get("name", item.file_id),
                content_type=meta.get("content_type", "application/octet-stream"),
                size_bytes=meta.get("size", 0),
                sha256checksum=meta.get("checksum") or "",
                processing_status=FileStatus.UPLOADED,
                uploader_id=conn.connected_by_user_id,
                **_file_owner_kwargs(owner_type, owner_id),
            ))
            registered.append(item.file_id)
        db.commit()
        return {"registered": registered}

    @r.delete("")
    async def disconnect(conn: Connection, db: DatabaseDep):  # + admin dep
        db.execute(delete(GDriveConnection).where(GDriveConnection.id == conn.id))
        db.commit()
        return {"message": "Disconnected"}

    return r


workspace_gdrive_router = gdrive_settings_router(GDriveOwnerType.workspace, "workspace_id")
channel_gdrive_router = gdrive_settings_router(GDriveOwnerType.channel, "channel_id")


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
        db_file.processing_status = FileStatus.UPLOADED
        db.commit()

    # TODO: return file meta
    return {"message": "Upload complete", "file_id": file_id}
