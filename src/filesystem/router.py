import uuid
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from auth import active_user
from model import DatabaseDep
from utils.logger import get_logger
from workspace import require_perms
from . import service
from .model import FileMetadata
from .storage.dependencies import FSDep

logger = get_logger(__name__)


class FileUploadResponse(BaseModel):
    file_id: uuid.UUID
    upload_url: str


class GetResponse(BaseModel):
    metadata: FileMetadata
    download_url: str | None = None


class FileListResponse(BaseModel):
    files: list[FileMetadata]
    next_cursor: str | None


class FileCreateRequest(BaseModel):
    create_type: Literal["file"] = "file"
    workspace_id: uuid.UUID
    channel_id: uuid.UUID | None
    user_id: uuid.UUID
    header: bytes
    sha256checksum: str
    size: int
    parent_uri: str
    filename: str | None = None


class DirectoryCreateRequest(BaseModel):
    create_type: Literal["directory"] = "directory"
    uri: str


class FileUpdateRequest(BaseModel):
    filename: str | None = None


CreateRequest = Annotated[FileCreateRequest | DirectoryCreateRequest, Field(discriminator="create_type")]

# Scope tuple: (workspace_id, channel_id | None)
FilesScope = tuple[uuid.UUID, uuid.UUID | None]


async def workspace_scope(
        workspace_id: uuid.UUID,
        _user: Annotated[object, Depends(active_user)],
) -> FilesScope:
    """Extracts workspace path param; auth enforced by require_perms on each route."""
    return workspace_id, None


async def channel_scope(
        workspace_id: uuid.UUID,
        channel_id: uuid.UUID,
        _user: Annotated[object, Depends(active_user)],
) -> FilesScope:
    """Extracts workspace + channel path params; auth enforced by require_perms on each route."""
    return workspace_id, channel_id


def make_files_router(
        prefix: str,
        scope_dep: Callable,
        name_prefix: str,
) -> APIRouter:
    """
    Produce a files APIRouter for either workspace-scoped or channel-scoped paths.
    Every handler is: unpack scope → call service → return.
    Auth lives in scope_dep + require_perms. Logic lives in service.
    """
    router = APIRouter(prefix=prefix, tags=["files"])

    @router.post(
        "/{protocol_abbr}",
        operation_id=f"{name_prefix}_create",
        dependencies=[require_perms("files:write", "files:create")],
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            status.HTTP_201_CREATED: {"description": "Directory created"},
            status.HTTP_208_ALREADY_REPORTED: {
                "description": "File already exists with same checksum; existing metadata returned"
            },
            status.HTTP_202_ACCEPTED: {"description": "File record created; upload URL returned"},
            status.HTTP_400_BAD_REQUEST: {"description": "Invalid request"},
            status.HTTP_404_NOT_FOUND: {"description": "Invalid protocol or path"},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Storage backend unavailable"},
        },
    )
    async def create_file_or_directory(
            protocol_abbr: Literal["g", "m"],
            payload: CreateRequest,
            scope: Annotated[FilesScope, Depends(scope_dep)],
            filesystem: FSDep,
            db: DatabaseDep,
    ):
        """Create a file or directory. Files → signed upload URL. Directories → 201."""
        ws_id, ch_id = scope
        match payload:
            case FileCreateRequest():
                # Inject scope into payload if not already set (channel-scoped upload)
                if payload.workspace_id != ws_id:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "workspace_id mismatch")
                if ch_id is not None and payload.channel_id is None:
                    payload = payload.model_copy(update={"channel_id": ch_id})
                return await service.get_upload_url(db, filesystem, payload)
            case DirectoryCreateRequest():
                filesystem.mkdirs(payload.uri, exist_ok=True)
                return JSONResponse(
                    status_code=status.HTTP_201_CREATED,
                    content={"status": "directory created", "path": payload.uri},
                )

    @router.get(
        "/{protocol_abbr}",
        operation_id=f"{name_prefix}_list",
        response_model=FileListResponse,
        dependencies=[require_perms("files:read")],
    )
    async def list_files(
            protocol_abbr: Literal["g", "m"],
            scope: Annotated[FilesScope, Depends(scope_dep)],
            db: DatabaseDep,
            content_type: Annotated[str | None, Query()] = None,
            cursor: Annotated[str | None, Query()] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        """List files with cursor-based pagination. Channel scope auto-filters by channel_id."""
        ws_id, ch_id = scope
        files, next_cursor = service.list_files(
            db=db,
            workspace_id=ws_id,
            channel_id=ch_id,
            content_type=content_type,
            cursor=cursor,
            limit=limit,
        )
        return FileListResponse(
            files=[FileMetadata.model_validate(f) for f in files],
            next_cursor=next_cursor,
        )

    @router.get(
        "/{protocol_abbr}/{file_or_dir_id}",
        operation_id=f"{name_prefix}_get",
        response_model=GetResponse,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "File not found"},
            status.HTTP_204_NO_CONTENT: {"description": "File exists but not yet available"},
        },
        dependencies=[require_perms("files:read")],
    )
    async def get_file(
            protocol_abbr: Literal["g", "m"],
            file_or_dir_id: uuid.UUID,
            scope: Annotated[FilesScope, Depends(scope_dep)],
            filesystem: FSDep,
            db: DatabaseDep,
            download: bool = False,
    ):
        """Get metadata and optionally a signed download URL. Directories return a file listing."""
        ws_id, ch_id = scope

        if filesystem.isdir(str(file_or_dir_id)):
            files, next_cursor = service.list_files(
                db=db,
                workspace_id=ws_id,
                channel_id=ch_id,
                content_type=None,
                cursor=None,
                parent_uri=str(file_or_dir_id),
                limit=1000,
            )
            return FileListResponse(files=[FileMetadata.model_validate(f) for f in files], next_cursor=next_cursor)

        file = await service.file_info(
            db=db,
            filesystem=filesystem,
            file_id=file_or_dir_id,
            workspace_id=ws_id,
            channel_id=ch_id,
        )

        if not download:
            return GetResponse(metadata=file)

        url = await service.get_download_url(db, filesystem, file.file_path)
        return GetResponse(metadata=file, download_url=url)

    @router.patch(
        "/{protocol_abbr}/{file_id}",
        operation_id=f"{name_prefix}_update_meta",
        dependencies=[require_perms("files:write")],
        status_code=status.HTTP_200_OK,
        response_model=FileMetadata,
    )
    async def update_file_meta(
            protocol_abbr: Literal["g", "m"],
            file_id: uuid.UUID,
            payload: FileUpdateRequest,
            scope: Annotated[FilesScope, Depends(scope_dep)],
            db: DatabaseDep,
    ):
        """Partial update of file metadata (e.g. rename)."""
        ws_id, ch_id = scope
        return await service.update_file_meta(db, file_id, ws_id, payload)

    @router.put(
        "/{protocol_abbr}/{file_id}",
        operation_id=f"{name_prefix}_replace",
        dependencies=[require_perms("files:write")],
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def replace_file(
            protocol_abbr: Literal["g", "m"],
            file_id: uuid.UUID,
            payload: FileCreateRequest,
            scope: Annotated[FilesScope, Depends(scope_dep)],
            filesystem: FSDep,
            db: DatabaseDep,
    ):
        """Replace file content entirely; returns new signed upload URL."""
        ws_id, ch_id = scope
        return await service.replace_file(db, filesystem, file_id, ws_id, payload)

    @router.delete(
        "/{file_id}",
        operation_id=f"{name_prefix}_delete",
        response_model=FileMetadata,
        dependencies=[require_perms("files:write")],
    )
    async def delete_file(
            file_id: uuid.UUID,
            scope: Annotated[FilesScope, Depends(scope_dep)],
            db: DatabaseDep,
    ):
        """Soft-delete a file (sets deleted_at)."""
        ws_id, _ch_id = scope
        file = service.soft_delete(db, file_id, ws_id)
        if file is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
        return FileMetadata.model_validate(file)

    return router


workspace = make_files_router(
    prefix="/files",
    scope_dep=workspace_scope,
    name_prefix="ws_files",
)

channel = make_files_router(
    prefix="/files",
    scope_dep=channel_scope,
    name_prefix="ch_files",
)
