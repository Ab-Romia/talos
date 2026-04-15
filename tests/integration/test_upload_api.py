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

    def test_upload_without_arq_returns_503(self, client, test_workspace):
        """If the ARQ pool is unavailable, uploads fail fast so the client
        knows the file will not be processed, rather than silently accepting
        it and leaving the file stuck in UPLOADED forever."""
        from app import app
        app.state.arq_pool = None

        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("test.txt", b"data", "text/plain")},
        )
        assert resp.status_code == 503

    def test_upload_enqueues_processing_job(self, client, test_workspace, mock_arq_pool):
        """A successful upload schedules the file for background processing."""
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("enqueued.txt", b"queue me", "text/plain")},
        )
        assert resp.status_code == 202
        mock_arq_pool.enqueue_job.assert_called_once()
        args, kwargs = mock_arq_pool.enqueue_job.call_args
        assert args[0] == "process_file"
        assert args[1] == resp.json()["file_id"]

    def test_upload_unsupported_mime_returns_415(self, client, test_workspace):
        # ZIP magic bytes -> detected as application/zip (not in ALLOWED_MIME_TYPES)
        zip_header = b'PK\x03\x04' + b'\x00' * 100
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("archive.zip", zip_header, "application/zip")},
        )
        assert resp.status_code == 415

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
