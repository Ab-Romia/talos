"""Thin Google Drive v3 client built on httpx, using a stored ProviderToken.

We deliberately do not depend on google-api-python-client to keep the install
small; the surface we need (list, get, download, export) is three endpoints.
"""

from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.model import ProviderToken
from config import cfg
from utils.logger import get_logger
from .constants import (
    DRIVE_FILES_ENDPOINT,
    GOOGLE_DOC_EXPORTS,
    GOOGLE_TOKEN_ENDPOINT,
)
from .exceptions import DriveAPIError, DriveNotConnected, DriveTokenRefreshFailed

logger = get_logger(__name__)

REFRESH_LEEWAY = timedelta(seconds=60)


class DriveClient:
    """Per-user Google Drive client.

    Resolves and refreshes the user's stored OAuth token on demand. Callers
    must hand in a sync DB session — the same one bound to the request — so
    refreshed tokens get persisted in the same unit of work.
    """

    def __init__(self, db: Session, user_id):
        self.db = db
        self.user_id = user_id
        self._token: ProviderToken | None = None

    def _load_token(self) -> ProviderToken:
        token = self.db.scalar(
            select(ProviderToken).where(
                ProviderToken.user_id == self.user_id,
                ProviderToken.provider == "google",
            )
        )
        if token is None or not token.access_token:
            raise DriveNotConnected("No Google account connected for this user")
        self._token = token
        return token

    def _is_expired(self, token: ProviderToken) -> bool:
        if token.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= token.expires_at - REFRESH_LEEWAY

    async def _refresh(self, token: ProviderToken) -> ProviderToken:
        if not token.refresh_token:
            raise DriveTokenRefreshFailed(
                "No refresh token stored — user must reconnect Google"
            )

        client_cfg = cfg().auth.oauth_clients.get("google")
        if client_cfg is None:
            raise DriveTokenRefreshFailed("Google OAuth client not configured")

        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": client_cfg.client_id,
                    "client_secret": client_cfg.client_secret,
                    "refresh_token": token.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code != 200:
            raise DriveTokenRefreshFailed(
                f"Refresh failed ({resp.status_code}): {resp.text[:200]}"
            )

        body = resp.json()
        token.access_token = body["access_token"]
        if body.get("expires_in"):
            token.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(body["expires_in"])
            )
        if body.get("refresh_token"):
            token.refresh_token = body["refresh_token"]
        if body.get("scope"):
            token.scope = body["scope"]
        self.db.commit()
        return token

    async def _auth_header(self) -> dict[str, str]:
        token = self._token or self._load_token()
        if self._is_expired(token):
            token = await self._refresh(token)
        return {"Authorization": f"Bearer {token.access_token}"}

    async def list_files(
            self,
            query: str | None = None,
            page_size: int = 25,
            page_token: str | None = None,
    ) -> dict:
        """List files visible to the app under the drive.file scope."""
        params = {
            "pageSize": page_size,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, iconLink, webViewLink)",
        }
        if query:
            # Caller-provided query is appended to the trash filter
            params["q"] = f"trashed = false and ({query})"
        else:
            params["q"] = "trashed = false"
        if page_token:
            params["pageToken"] = page_token

        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                DRIVE_FILES_ENDPOINT,
                params=params,
                headers=await self._auth_header(),
            )
        if resp.status_code == 401:
            raise DriveTokenRefreshFailed("Google token revoked or invalid; user must reconnect")
        if resp.status_code != 200:
            raise DriveAPIError(resp.status_code, resp.text[:500])
        return resp.json()

    async def get_metadata(self, drive_file_id: str) -> dict:
        params = {
            "fields": "id, name, mimeType, size, modifiedTime, iconLink, webViewLink",
        }
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                f"{DRIVE_FILES_ENDPOINT}/{quote(drive_file_id)}",
                params=params,
                headers=await self._auth_header(),
            )
        if resp.status_code == 401:
            raise DriveTokenRefreshFailed("Google token revoked or invalid; user must reconnect")
        if resp.status_code == 404:
            raise DriveAPIError(404, "File not found or not granted to this app")
        if resp.status_code != 200:
            raise DriveAPIError(resp.status_code, resp.text[:500])
        return resp.json()

    async def download(
            self, drive_file_id: str, mime_type: str, max_bytes: int
    ) -> tuple[str, str, bytes]:
        """Return (effective_mime, suggested_ext, content_bytes).

        Google-native docs (Docs/Sheets/Slides) are exported to a downloadable
        format per GOOGLE_DOC_EXPORTS; everything else uses alt=media. Aborts
        if the response body exceeds max_bytes so a malicious or oversized
        Drive file can't blow the worker's memory.
        """
        export = GOOGLE_DOC_EXPORTS.get(mime_type)
        if export is None and mime_type.startswith("application/vnd.google-apps."):
            raise DriveAPIError(
                415,
                f"Google-native file type '{mime_type}' is not supported for import",
            )
        if export is not None:
            export_mime, ext = export
            url = f"{DRIVE_FILES_ENDPOINT}/{quote(drive_file_id)}/export"
            params = {"mimeType": export_mime}
            effective_mime = export_mime
        else:
            url = f"{DRIVE_FILES_ENDPOINT}/{quote(drive_file_id)}"
            params = {"alt": "media"}
            effective_mime = mime_type
            ext = ""

        headers = await self._auth_header()

        buf = bytearray()
        async with httpx.AsyncClient(timeout=60) as http:
            async with http.stream("GET", url, params=params, headers=headers) as resp:
                if resp.status_code == 401:
                    raise DriveTokenRefreshFailed("Google token revoked or invalid; user must reconnect")
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise DriveAPIError(
                        resp.status_code, body.decode("utf-8", "replace")[:500]
                    )
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise DriveAPIError(
                            413, f"Drive file exceeds {max_bytes} bytes"
                        )
        return effective_mime, ext, bytes(buf)
