"""Unit tests for the Google Drive client (token refresh, listing, downloads)."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.auth.model import ProviderToken
from integrations.drive.client import DriveClient, REFRESH_LEEWAY
from integrations.drive.exceptions import (
    DriveAPIError,
    DriveNotConnected,
    DriveTokenRefreshFailed,
)


def _make_token(
        access_token: str = "good-access",
        refresh_token: str | None = "good-refresh",
        expires_at: datetime | None = None,
        scope: str | None = "drive.file",
) -> ProviderToken:
    """Build a ProviderToken without committing to the DB."""
    t = ProviderToken(
        user_id=uuid.uuid4(),
        provider="google",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scope=scope,
    )
    return t


def _db_with_token(token: ProviderToken | None) -> MagicMock:
    db = MagicMock()
    db.scalar.return_value = token
    return db


def _httpx_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body,
        text=text if json_body is None else None,
        request=httpx.Request("GET", "https://example/"),
    )


@pytest.mark.unit
class TestLoadToken:
    def test_raises_when_no_row(self):
        client = DriveClient(_db_with_token(None), uuid.uuid4())
        with pytest.raises(DriveNotConnected):
            client._load_token()

    def test_raises_when_access_token_blank(self):
        client = DriveClient(_db_with_token(_make_token(access_token="")), uuid.uuid4())
        with pytest.raises(DriveNotConnected):
            client._load_token()

    def test_returns_and_caches(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        assert client._load_token() is token
        assert client._token is token


@pytest.mark.unit
class TestExpiry:
    def test_no_expiry_means_not_expired(self):
        token = _make_token(expires_at=None)
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        assert client._is_expired(token) is False

    def test_future_expiry_outside_leeway(self):
        token = _make_token(
            expires_at=datetime.now(timezone.utc) + REFRESH_LEEWAY + timedelta(seconds=30)
        )
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        assert client._is_expired(token) is False

    def test_past_expiry_is_expired(self):
        token = _make_token(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        assert client._is_expired(token) is True

    def test_inside_leeway_treated_as_expired(self):
        token = _make_token(
            expires_at=datetime.now(timezone.utc) + REFRESH_LEEWAY - timedelta(seconds=5)
        )
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        assert client._is_expired(token) is True


@pytest.mark.unit
class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_without_refresh_token_fails(self):
        token = _make_token(refresh_token=None)
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        with pytest.raises(DriveTokenRefreshFailed):
            await client._refresh(token)

    @pytest.mark.asyncio
    @patch("integrations.drive.client.cfg")
    async def test_refresh_missing_oauth_client_fails(self, mock_cfg):
        mock_cfg.return_value.auth.oauth_clients = {}
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        with pytest.raises(DriveTokenRefreshFailed):
            await client._refresh(token)

    @pytest.mark.asyncio
    @patch("integrations.drive.client.cfg")
    async def test_refresh_non_200_fails(self, mock_cfg):
        mock_cfg.return_value.auth.oauth_clients = {
            "google": MagicMock(client_id="cid", client_secret="cs")
        }
        token = _make_token()
        db = _db_with_token(token)
        client = DriveClient(db, uuid.uuid4())

        async def _post(*_a, **_kw):
            return _httpx_response(400, text="invalid_grant")

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=_post)
            with pytest.raises(DriveTokenRefreshFailed):
                await client._refresh(token)

    @pytest.mark.asyncio
    @patch("integrations.drive.client.cfg")
    async def test_refresh_success_persists_new_access_token(self, mock_cfg):
        mock_cfg.return_value.auth.oauth_clients = {
            "google": MagicMock(client_id="cid", client_secret="cs")
        }
        token = _make_token(access_token="old", refresh_token="rt")
        db = _db_with_token(token)
        client = DriveClient(db, uuid.uuid4())

        async def _post(*_a, **_kw):
            return _httpx_response(
                200,
                json_body={"access_token": "new-access", "expires_in": 3600, "scope": "drive.file"},
            )

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=_post)
            refreshed = await client._refresh(token)

        assert refreshed.access_token == "new-access"
        assert refreshed.refresh_token == "rt"  # preserved
        assert refreshed.expires_at is not None
        assert refreshed.expires_at > datetime.now(timezone.utc) + timedelta(minutes=50)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("integrations.drive.client.cfg")
    async def test_refresh_uses_rotated_refresh_token_if_provided(self, mock_cfg):
        mock_cfg.return_value.auth.oauth_clients = {
            "google": MagicMock(client_id="cid", client_secret="cs")
        }
        token = _make_token(refresh_token="rt-old")
        db = _db_with_token(token)
        client = DriveClient(db, uuid.uuid4())

        async def _post(*_a, **_kw):
            return _httpx_response(
                200,
                json_body={
                    "access_token": "new",
                    "refresh_token": "rt-new",
                    "expires_in": 3600,
                },
            )

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=_post)
            refreshed = await client._refresh(token)

        assert refreshed.refresh_token == "rt-new"


@pytest.mark.unit
class TestAuthHeader:
    @pytest.mark.asyncio
    async def test_skips_refresh_when_token_fresh(self):
        token = _make_token(expires_at=None)
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        client._refresh = AsyncMock()  # type: ignore[method-assign]
        headers = await client._auth_header()
        assert headers == {"Authorization": "Bearer good-access"}
        client._refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_refreshes_when_token_expired(self):
        token = _make_token(
            access_token="old",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        client = DriveClient(_db_with_token(token), uuid.uuid4())
        refreshed = _make_token(access_token="new")
        client._refresh = AsyncMock(return_value=refreshed)  # type: ignore[method-assign]
        headers = await client._auth_header()
        assert headers == {"Authorization": "Bearer new"}
        client._refresh.assert_awaited_once()


@pytest.mark.unit
class TestListFiles:
    @pytest.mark.asyncio
    async def test_appends_trash_filter(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        captured = {}

        async def _get(url, params=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            return _httpx_response(200, json_body={"files": []})

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            await client.list_files(query="name contains 'foo'")

        assert "trashed = false and (name contains 'foo')" == captured["params"]["q"]

    @pytest.mark.asyncio
    async def test_default_query_excludes_trash(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        captured = {}

        async def _get(url, params=None, headers=None):
            captured["params"] = params
            return _httpx_response(200, json_body={"files": []})

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            await client.list_files()

        assert captured["params"]["q"] == "trashed = false"

    @pytest.mark.asyncio
    async def test_non_200_raises_drive_api_error(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        async def _get(*_a, **_kw):
            return _httpx_response(403, text="forbidden")

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            with pytest.raises(DriveAPIError) as exc:
                await client.list_files()
            assert exc.value.status_code == 403


@pytest.mark.unit
class TestGetMetadata:
    @pytest.mark.asyncio
    async def test_404_translated(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        async def _get(*_a, **_kw):
            return _httpx_response(404, text="not found")

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            with pytest.raises(DriveAPIError) as exc:
                await client.get_metadata("xyz")
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_json_body(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        async def _get(*_a, **_kw):
            return _httpx_response(200, json_body={"id": "x", "name": "n", "mimeType": "text/plain"})

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            meta = await client.get_metadata("xyz")
        assert meta["name"] == "n"


@pytest.mark.unit
class TestPersistProviderToken:
    """B2: re-auth without expiry must not clobber existing expires_at."""

    def test_reauth_without_expiry_preserves_existing_expires_at(self):
        from datetime import datetime, timezone, timedelta
        from backend.auth.oauth import _persist_provider_token
        from backend.auth.model import ProviderToken
        import uuid

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        existing = ProviderToken(
            user_id=uuid.uuid4(),
            provider="google",
            access_token="old",
            refresh_token="rt",
            expires_at=future,
            scope="drive.file",
        )
        db = MagicMock()
        db.scalar.return_value = existing

        # Google re-auth returns a new access token but no expiry fields
        new_token = {
            "access_token": "new-access",
            "scope": "drive.file",
        }
        _persist_provider_token(db, existing.user_id, "google", new_token)

        assert existing.expires_at == future  # NOT clobbered
        assert existing.access_token == "new-access"


@pytest.mark.unit
class TestDriveApi401Handling:
    """B3: Drive API 401 must surface as DriveTokenRefreshFailed, not DriveAPIError."""

    @pytest.mark.asyncio
    async def test_list_files_401_raises_token_refresh_failed(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        async def _get(*_a, **_kw):
            return _httpx_response(401, text="invalid credentials")

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            with pytest.raises(DriveTokenRefreshFailed):
                await client.list_files()

    @pytest.mark.asyncio
    async def test_get_metadata_401_raises_token_refresh_failed(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        async def _get(*_a, **_kw):
            return _httpx_response(401, text="invalid credentials")

        with patch("httpx.AsyncClient") as mock_async_client:
            instance = mock_async_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_get)
            with pytest.raises(DriveTokenRefreshFailed):
                await client.get_metadata("file-id")


@pytest.mark.unit
class TestDownloadUnknownGoogleMime:
    """G1: Unknown vnd.google-apps.* types must raise DriveAPIError(415)."""

    @pytest.mark.asyncio
    async def test_unknown_google_native_mime_raises_415(self):
        token = _make_token()
        client = DriveClient(_db_with_token(token), uuid.uuid4())

        with pytest.raises(DriveAPIError) as exc:
            await client.download("file-id", "application/vnd.google-apps.form", max_bytes=10 * 1024 * 1024)
        assert exc.value.status_code == 415
