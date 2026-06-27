import uuid

import pytest

from config import cfg


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
            headers={"content-length": str(cfg().files.max_size + 1)},
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

        from files.model import File
        record = db_session.get(File, uuid.UUID(file_id))
        assert record is not None
        assert record.filename == "persist.txt"

    def test_channel_upload_derives_workspace_id(self, client, test_workspace, test_channel, db_session):
        resp = client.post(
            f"/api/channels/{test_channel.id}/files",
            files={"file": ("channel.txt", b"channel data", "text/plain")},
        )
        assert resp.status_code == 202

        from files.model import File
        file_id = uuid.UUID(resp.json()["file_id"])
        record = db_session.get(File, file_id)
        assert record is not None
        assert record.channel_id == test_channel.id
        assert record.workspace_id == test_workspace.id


@pytest.mark.integration
class TestRetryAPI:
    def test_retry_resets_failed_file_and_enqueues(
            self, client, test_workspace, make_file, db_session, mock_arq_pool
    ):
        from files.model import File, FileStatus

        f = make_file(
            test_workspace.id,
            processing_status=FileStatus.PROCESSING_FAILED,
            processing_error="something went wrong",
            chunk_count=None,
        )
        resp = client.post(f"/api/workspaces/{test_workspace.id}/files/{f.id}/retry")
        assert resp.status_code == 200

        db_session.expire_all()
        record = db_session.get(File, f.id)
        assert record.status == FileStatus.UPLOADED
        assert record.processing_error is None
        mock_arq_pool.enqueue_job.assert_called_once()

    def test_retry_rejects_indexed_file(self, client, test_workspace, make_file):
        from files.model import FileStatus

        f = make_file(test_workspace.id, processing_status=FileStatus.INDEXED)
        resp = client.post(f"/api/workspaces/{test_workspace.id}/files/{f.id}/retry")
        assert resp.status_code == 409

    def test_retry_404_when_missing(self, client, test_workspace):
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files/{uuid.uuid4()}/retry"
        )
        assert resp.status_code == 404
