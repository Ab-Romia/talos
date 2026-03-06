import uuid
from io import BytesIO
from unittest.mock import AsyncMock

import pytest

from files.constants import MAX_FILE_SIZE


@pytest.mark.integration
class TestUploadAPI:
    def test_upload_returns_202(self, client, test_workspace):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 202

    def test_upload_response_shape(self, client, test_workspace):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("doc.txt", b"content", "text/plain")},
        )
        data = resp.json()
        assert "file_id" in data
        assert "status" in data
        assert "filename" in data
        assert "content_type" in data
        assert "size_bytes" in data

    def test_upload_too_large_returns_413(self, client, test_workspace):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("big.txt", b"x", "text/plain")},
            headers={"content-length": str(MAX_FILE_SIZE + 1)},
        )
        assert resp.status_code == 413

    def test_upload_without_arq_still_succeeds(self, client, test_workspace):
        from app import app
        app.state.arq_pool = None

        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("test.txt", b"data", "text/plain")},
        )
        assert resp.status_code == 202

    def test_upload_persists_to_db(self, client, test_workspace, db_session):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("persist.txt", b"persist data", "text/plain")},
        )
        assert resp.status_code == 202
        file_id = resp.json()["file_id"]

        from files.models import FileAttachment
        record = db_session.get(FileAttachment, uuid.UUID(file_id))
        assert record is not None
        assert record.original_filename == "persist.txt"
