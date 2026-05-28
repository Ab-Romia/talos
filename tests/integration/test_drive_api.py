"""Integration tests for Google Drive endpoints."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.auth.model import ProviderToken
from config import cfg
from integrations.drive.router import drive_status, list_drive_files, import_drive_file


@pytest.fixture
def drive_token(db_session, test_user):
    token = ProviderToken(
        user_id=test_user.id,
        provider="google",
        access_token="access-123",
        refresh_token="refresh-123",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="openid email profile https://www.googleapis.com/auth/drive.file",
    )
    db_session.add(token)
    db_session.flush()
    return token


@pytest.mark.integration
class TestDriveStatus:
    def test_status_disconnected(self, client, path):
        resp = client.get(path(drive_status))
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["scope"] is None

    def test_status_connected(self, client, drive_token, path):
        resp = client.get(path(drive_status))
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert "drive.file" in body["scope"]


@pytest.mark.integration
class TestDriveListFiles:
    def test_412_when_not_connected(self, client, path):
        resp = client.get(path(list_drive_files))
        assert resp.status_code == 412

    def test_returns_files_when_connected(self, client, drive_token, path):
        with patch("integrations.drive.router.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.list_files = AsyncMock(return_value={
                "files": [
                    {
                        "id": "f1",
                        "name": "doc.pdf",
                        "mimeType": "application/pdf",
                        "size": "1024",
                        "modifiedTime": "2026-01-01T00:00:00Z",
                    }
                ],
                "nextPageToken": "tok",
            })
            resp = client.get(path(list_drive_files))
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_page_token"] == "tok"
        assert body["files"][0]["id"] == "f1"
        assert body["files"][0]["size"] == 1024

    def test_502_on_drive_api_error(self, client, drive_token, path):
        from integrations.drive.exceptions import DriveAPIError

        with patch("integrations.drive.router.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.list_files = AsyncMock(side_effect=DriveAPIError(500, "boom"))
            resp = client.get(path(list_drive_files))
        assert resp.status_code == 502

    def test_401_on_refresh_failure(self, client, drive_token, path):
        from integrations.drive.exceptions import DriveTokenRefreshFailed

        with patch("integrations.drive.router.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.list_files = AsyncMock(side_effect=DriveTokenRefreshFailed("nope"))
            resp = client.get(path(list_drive_files))
        assert resp.status_code == 401

    def test_page_size_clamped(self, client, drive_token, path):
        resp = client.get(path(list_drive_files) + "?page_size=999")
        # Pydantic validation -> 422 before the Drive call
        assert resp.status_code == 422


@pytest.mark.integration
class TestDriveImport:
    def test_412_when_not_connected(self, client, test_workspace, path):
        resp = client.post(path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc")
        assert resp.status_code == 412

    def test_happy_path_runs_through_upload(
            self, client, test_workspace, drive_token, db_session, mock_arq_pool, path
    ):
        from files.model import FileAttachment

        with patch("integrations.drive.service.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.get_metadata = AsyncMock(return_value={
                "id": "abc",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "size": "12",
            })
            instance.download = AsyncMock(
                return_value=("application/pdf", "", b"%PDF-1.4 fake")
            )
            resp = client.post(
                path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc"
            )

        assert resp.status_code == 202, resp.content
        body = resp.json()
        assert body["filename"] == "report.pdf"
        assert body["drive_file_id"] == "abc"
        # Persisted to the DB
        record = db_session.get(FileAttachment, uuid.UUID(body["file_id"]))
        assert record is not None
        # Same enqueue path as direct upload
        mock_arq_pool.enqueue_job.assert_called_once()

    def test_413_on_oversized_file(self, client, test_workspace, drive_token, path):
        with patch("integrations.drive.service.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.get_metadata = AsyncMock(return_value={
                "id": "abc",
                "name": "huge.pdf",
                "mimeType": "application/pdf",
                "size": str(cfg().files.max_size + 1),
            })
            resp = client.post(
                path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc"
            )
        assert resp.status_code == 413

    def test_415_on_unsupported_google_native_type(
            self, client, test_workspace, drive_token, path
    ):
        with patch("integrations.drive.service.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.get_metadata = AsyncMock(return_value={
                "id": "abc",
                "name": "drawing",
                "mimeType": "application/vnd.google-apps.drawing",
            })
            resp = client.post(
                path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc"
            )
        assert resp.status_code == 415

    def test_503_when_arq_pool_unavailable(
            self, client, test_workspace, drive_token, path
    ):
        from app import app
        app.state.arq_pool = None
        try:
            with patch("integrations.drive.service.DriveClient") as MockClient:
                instance = MockClient.return_value
                instance.get_metadata = AsyncMock(return_value={
                    "id": "abc",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                })
                instance.download = AsyncMock(
                    return_value=("application/pdf", "", b"%PDF-1.4 ok")
                )
                resp = client.post(
                    path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc"
                )
            assert resp.status_code == 503
        finally:
            # restore for other tests
            app.state.arq_pool = None  # client fixture re-installs on next test

    def test_channel_validated_against_workspace(
            self, client, test_workspace, drive_token, path
    ):
        # channel_id that doesn't exist in this workspace
        resp = client.post(
            path(import_drive_file, workspace_id=test_workspace.id) + f"?drive_file_id=abc&channel_id={uuid.uuid4()}"
        )
        assert resp.status_code == 404

    def test_502_on_drive_api_error(self, client, test_workspace, drive_token, path):
        from integrations.drive.exceptions import DriveAPIError

        with patch("integrations.drive.service.DriveClient") as MockClient:
            instance = MockClient.return_value
            instance.get_metadata = AsyncMock(side_effect=DriveAPIError(500, "boom"))
            resp = client.post(
                path(import_drive_file, workspace_id=test_workspace.id) + "?drive_file_id=abc"
            )
        assert resp.status_code == 502
