import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator, Any, Literal, TYPE_CHECKING

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cachetools import LRUCache
from fsspec.asyn import AbstractAsyncStreamedFile, AsyncFileSystem

from auth.utils import jwt
from config import cfg

if TYPE_CHECKING:
    from router import UserCreds

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = f"https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
ID_PREFIX = "id:"

_name_cache = LRUCache(maxsize=1024)  # global LRU cache for name resolution


def _file_info(f: dict) -> dict[str, int | str | Any]:
    is_folder = f.get("mimeType") == FOLDER_MIME
    return {
        "name": f["name"],
        "id": f["id"],
        "size": int(f.get("size", 0)),
        "type": "directory" if is_folder else "file",
        "content_type": f.get("mimeType", "application/octet-stream"),
        "modified": f.get("modifiedTime"),
        "created": f.get("createdTime"),
        "checksum": f.get("sha256Checksum"),
    }


class GDriveFileSystem(AsyncFileSystem):
    protocol = "gdrive"

    _INFO_FIELDS = "id,name,mimeType,size,modifiedTime,createdTime,sha256Checksum"
    _LS_FIELDS = f"files({_INFO_FIELDS}),nextPageToken"

    def __init__(self, user_creds: UserCreds, root_folder_id: str = "root", **kwargs):
        super().__init__(**kwargs)
        self.user_creds = user_creds
        self.client_creds = cfg().auth.oauth_clients.get("google")
        assert self.client_creds, "Google OAuth client config is required"
        self.root_folder_id = root_folder_id

    @asynccontextmanager
    async def client(self):
        """Yields an AsyncOAuth2Client that auto-refreshes the token."""

        async def _update(token, **_):
            self.user_creds.access_token = token["access_token"]
            self.user_creds.refresh_token = token.get("refresh_token", self.user_creds.refresh_token)
            self.user_creds.expires_at = datetime.fromtimestamp(
                token.get("expires_at", self.user_creds.expires_at), tz=timezone.utc
            )

        async with AsyncOAuth2Client(
                client_id=self.client_creds.client_id,
                client_secret=self.client_creds.client_secret.get_secret_value(),
                token={
                    "access_token": self.user_creds.access_token,
                    "refresh_token": self.user_creds.refresh_token,
                    "expires_at": int(self.user_creds.expires_at.timestamp()) if self.user_creds.expires_at else None,
                },
                token_endpoint=GOOGLE_TOKEN_URL,
                update_token=_update,
        ) as c:
            yield c

    @property
    async def access_token(self) -> str:
        async with self.client() as c:
            await c.ensure_active_token(self.user_creds.model_dump())
        return self.user_creds.access_token

    async def updated_creds(self) -> "UserCreds":
        async with self.client() as c:
            await c.ensure_active_token(self.user_creds.model_dump())
        return self.user_creds

    async def _resolve_name(self, name: str, parent_id: str, is_file: bool = False) -> str:
        """Resolve one path segment to its Drive ID under parent_id."""
        # key = (str(self.user_creds.id), name, parent_id)
        # if key in _name_cache:
        #     return _name_cache[key]

        mime_filter = " and mimeType != 'application/vnd.google-apps.folder'" if is_file else ""
        async with self.client() as c:
            resp = await c.get(
                DRIVE_FILES_URL,
                params={
                    "q": f"'{parent_id}' in parents and name = '{name}' and trashed = false{mime_filter}",
                    "fields": "files(id,mimeType)",
                    "pageSize": 2,
                },
            )
            resp.raise_for_status()
            files = resp.json().get("files", [])

        if not files:
            raise FileNotFoundError(f"{name!r} not found under {parent_id!r}")
        if len(files) > 1:
            raise ValueError(f"Ambiguous: multiple entries named {name!r} under {parent_id!r}")

        # _name_cache[key] = files[0]["id"]

        return files[0]["id"]

    async def resolve_path(self, path: str, *, is_folder: bool = False) -> str:
        """
        Resolve a mixed ID/name path to a leaf Drive ID.

        Examples:
            "id:1BxMoo" -> "1BxMoo"
            "id:ROOT/Reports/report.pdf" -> resolved file ID
            "Reports/Q1/id:FolderID/report.pdf" -> resolved file ID
            "Reports/Q1" -> resolved folder ID
        """
        segments = [s for s in path.split("/") if s]
        if not segments:
            return self.root_folder_id

        parent_id = self.root_folder_id
        n = len(segments)
        for i, seg in enumerate(segments):
            if seg.startswith(ID_PREFIX):
                parent_id = seg[len(ID_PREFIX):]
            else:
                is_last = i == n - 1
                # For the terminal segment: is_file=True unless caller says it's a folder.
                parent_id = await self._resolve_name(seg, parent_id, is_file=is_last and not is_folder)

        return parent_id

    async def _ls(self, path: str, detail: bool = True, **kwargs) -> list:
        # TODO: handle shortcuts / duplicate names
        parent_id = await self.resolve_path(path, is_folder=True) if path else self.root_folder_id
        q = f"'{parent_id}' in parents and trashed = false"

        items: list[dict] = []
        page_token: str | None = None
        async with self.client() as c:
            while True:
                params: dict = {"q": q, "fields": self._LS_FIELDS, "pageSize": 100}
                if page_token:
                    params["pageToken"] = page_token
                resp = await c.get(DRIVE_FILES_URL, params=params)
                resp.raise_for_status()
                res = resp.json()
                items.extend(_file_info(f) for f in res.get("files", []))
                page_token = res.get("nextPageToken")
                if not page_token:
                    break

        return items if detail else [i["name"] for i in items]

    async def _info(self, path: str, **kwargs) -> dict:
        file_id = await self.resolve_path(path)
        async with self.client() as c:
            resp = await c.get(f"{DRIVE_FILES_URL}/{file_id}", params={"fields": self._INFO_FIELDS})
            resp.raise_for_status()
        return _file_info(resp.json())

    async def _rm_file(self, path: str, **kwargs) -> None:
        file_id = await self.resolve_path(path)
        async with self.client() as c:
            (await c.delete(f"{DRIVE_FILES_URL}/{file_id}")).raise_for_status()

    async def _cp_file(self, path1: str, path2: str, **kwargs) -> str:
        """Copy file at path1 into folder path2. Returns new file ID."""
        file_id = await self.resolve_path(path1)
        dest_id = await self.resolve_path(path2, is_folder=True)
        async with self.client() as c:
            resp = await c.post(
                f"{DRIVE_FILES_URL}/{file_id}/copy",
                json={"parents": [dest_id]},
                params={"fields": "id"},
            )
            resp.raise_for_status()
        return resp.json()["id"]

    async def open_async(self, path: str, mode: str = "rb", name: str | None = None, **kwargs) -> GDriveFile:
        if "w" in mode:
            segments = [s for s in path.split("/") if s]
            leaf_name = segments[-1] if segments else "untitled"
            parent_id = (
                await self.resolve_path("/".join(segments[:-1]), is_folder=True)
                if len(segments) > 1 else self.root_folder_id
            )
            return GDriveFile(
                fs=self, path=path, mode=mode,
                block_size=self.blocksize, cache_type="none",
                name=name or leaf_name, parent_id=parent_id,
                **kwargs,
            )

        # read path
        file_id = await self.resolve_path(path)
        meta = await self._info(path)
        f = GDriveFile(
            fs=self, path=f"{ID_PREFIX}{file_id}", mode=mode,
            block_size=self.blocksize, cache_type="none",
            name=name, parent_id=self.root_folder_id,
            **kwargs,
        )
        f.size = int(meta.get("size", 0))
        return f

    async def _mkdir(self, path: str, create_parents: bool = True, **kwargs) -> str:
        """Create a folder at a path. Returns new folder ID."""
        segments = [s for s in path.split("/") if s]
        name = kwargs.pop("name", segments[-1] if segments else "untitled")
        parent_id = (
            await self.resolve_path("/".join(segments[:-1]), is_folder=True)
            if len(segments) > 1 else self.root_folder_id
        )
        async with self.client() as c:
            resp = await c.post(
                DRIVE_FILES_URL,
                json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
                params={"fields": "id"},
            )
            resp.raise_for_status()
        return resp.json()["id"]

    def sign(self, path: str, expiration: int = 100,
             operation: Literal["get_object", "put_object"] = "get_object") -> str:
        from app import app
        from router import stream_gdrive_download, create_gdrive_upload, DriveClaims

        fn = {
            "get_object": stream_gdrive_download.__name__,
            "put_object": create_gdrive_upload.__name__,
        }.get(operation)

        if fn is None:
            raise ValueError(f"Unsupported operation: {operation!r}")
        claims = DriveClaims(
            user_creds_id=self.user_creds.id,
            file_path=path,
            op=operation,
            exp=jwt.now() + timedelta(minutes=expiration),
        )
        return f"{app.url_path_for(fn)}?token={claims.encode()}"


class GDriveFile(AbstractAsyncStreamedFile):
    # TODO: self.details from info
    """fsspec file-like object for Google Drive."""

    def __init__(self, *args, **kwargs):
        self._upload_name: str = kwargs.pop("name", None) or "untitled"
        self._parent_id: str = kwargs.pop("parent_id", None) or "root"
        super().__init__(*args, **kwargs)

        self._upload_url: str | None = None
        self._uploaded_bytes: int = 0
        if not self.path.startswith("id:"):
            raise ValueError(f"Invalid Drive ID path: {self.path !r}")
        self._gdrive_id: str | None = self.path.removeprefix(ID_PREFIX)

    async def _fetch_range(self, start: int, end: int) -> bytes:
        """Random-access byte range read (used by fsspec base read())."""
        token = await self.fs.access_token
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{DRIVE_FILES_URL}/{self._gdrive_id}",
                params={"alt": "media"},
                headers={"Authorization": f"Bearer {token}", "Range": f"bytes={start}-{end - 1}"},
            )
            resp.raise_for_status()
            return resp.content

    async def stream(self, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        """Sequential streaming read for StreamingResponse (avoids full buffer)."""
        token = await self.fs.access_token
        headers = {"Authorization": f"Bearer {token}"}
        if start or end is not None:
            headers["Range"] = f"bytes={start}-{end - 1 if end is not None else ''}"
        async with httpx.AsyncClient() as c:
            async with c.stream(
                    "GET",
                    f"{DRIVE_FILES_URL}/{self._gdrive_id}",
                    params={"alt": "media"},
                    headers=headers,
                    timeout=None,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=self.fs.blocksize):
                    yield chunk

    # TODO: support PATCH for existing file (overwrite) instead of always creating new
    async def _initiate_upload(self) -> None:
        """Start a resumable upload session; stores the session URI."""
        token = await self.fs.access_token
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                DRIVE_UPLOAD_URL,
                params={"uploadType": "resumable"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"name": self._upload_name, "parents": [self._parent_id]},
            )
            resp.raise_for_status()
            self._upload_url = resp.headers["Location"]
            self._uploaded_bytes = 0

    async def _upload_chunk(self, final: bool = False) -> bool:
        """Send buffered bytes as the next resumable-upload chunk."""
        data = self.buffer.getvalue()
        if not data and not final:
            return False

        if self._upload_url is None:
            await self._initiate_upload()

        start = self._uploaded_bytes
        end = start + len(data) - 1
        range_total = end + 1 if final else "*"

        async with httpx.AsyncClient() as c:
            resp = await c.put(
                self._upload_url,
                content=data,
                headers={"Content-Range": f"bytes {start}-{end}/{range_total}"},
            )
            if final:
                resp.raise_for_status()
                self._gdrive_id = resp.json()["id"]
            elif resp.status_code not in (200, 201, 308):
                # 308 Resume Incomplete = chunk accepted, more expected
                resp.raise_for_status()

        self._uploaded_bytes += len(data)
        self.buffer = io.BytesIO()
        return True
