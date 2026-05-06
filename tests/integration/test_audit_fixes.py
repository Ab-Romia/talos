"""Regression tests for audit findings against the file system module."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from config import cfg
from utils.datetime import utcnow


@pytest.mark.integration
class TestAttachChannelMismatch:
    """Audit bug #2: attach must reject channel_id that doesn't match the message."""

    def test_attach_rejects_mismatched_channel(
            self, client, test_workspace, test_channel, test_message, make_file, db_session
    ):
        from model.messaging import Channel

        other_channel = Channel(
            id=uuid.uuid4(),
            name="other",
            workspace_id=test_workspace.id,
        )
        db_session.add(other_channel)
        db_session.flush()

        f = make_file(test_workspace.id)
        # Use other_channel in the URL but the message belongs to test_channel
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/channels/{other_channel.id}"
            f"/messages/{test_message.id}/files?file_id={f.id}"
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestRetryStuckProcessing:
    """Audit bug #1: retry should reclaim stuck PROCESSING files past STUCK_AGE."""

    def test_retry_reclaims_stuck_processing(
            self, client, test_workspace, make_file, db_session, mock_arq_pool
    ):
        from files.model import FileAttachment, ProcessingStatus
        from processing.worker import STUCK_AGE

        f = make_file(test_workspace.id, processing_status=ProcessingStatus.PROCESSING)
        # Backdate updated_at past the stuck threshold
        f.updated_at = utcnow() - STUCK_AGE - timedelta(seconds=60)
        db_session.flush()

        resp = client.post(f"/api/workspaces/{test_workspace.id}/files/{f.id}/retry")
        assert resp.status_code == 200

        db_session.expire_all()
        record = db_session.get(FileAttachment, f.id)
        assert record.processing_status == ProcessingStatus.UPLOADED
        mock_arq_pool.enqueue_job.assert_called_once()

    def test_retry_rejects_active_processing(
            self, client, test_workspace, make_file, db_session
    ):
        from files.model import ProcessingStatus

        f = make_file(test_workspace.id, processing_status=ProcessingStatus.PROCESSING)
        # updated_at is recent (just made), so it's still considered active
        resp = client.post(f"/api/workspaces/{test_workspace.id}/files/{f.id}/retry")
        assert resp.status_code == 409


@pytest.mark.integration
class TestSoftDeleteVectorFailure:
    """Audit risk #7: a Milvus failure must abort soft-delete, not orphan chunks."""

    def test_soft_delete_aborts_when_vector_cleanup_fails(
            self, client, test_workspace, make_file, db_session
    ):
        from files.model import FileAttachment, ProcessingStatus

        f = make_file(test_workspace.id, processing_status=ProcessingStatus.INDEXED)

        with patch(
                "rag.vector_store.delete_file_chunks",
                side_effect=RuntimeError("milvus down"),
        ):
            resp = client.delete(f"/api/workspaces/{test_workspace.id}/files/{f.id}")

        assert resp.status_code == 503
        db_session.expire_all()
        record = db_session.get(FileAttachment, f.id)
        assert record.deleted_at is None  # not tombstoned

    def test_soft_delete_skips_vector_call_for_unindexed(
            self, client, test_workspace, make_file, db_session
    ):
        """UPLOADED/PROCESSING/FAILED files have no chunks to clean."""
        from files.model import ProcessingStatus

        f = make_file(test_workspace.id, processing_status=ProcessingStatus.UPLOADED)
        with patch(
                "rag.vector_store.delete_file_chunks",
                side_effect=AssertionError("should not be called"),
        ):
            resp = client.delete(f"/api/workspaces/{test_workspace.id}/files/{f.id}")
        assert resp.status_code == 200


@pytest.mark.integration
class TestStreamingSizeCap:
    """Audit gap #5: oversized stream must be rejected without buffering it all."""

    def test_oversized_body_rejected(self, client, test_workspace):
        # Body just over the cap; magic bytes look like text
        body = b"hello\n" + b"x" * (cfg().files.max_size + 100)
        resp = client.post(
            f"/api/workspaces/{test_workspace.id}/files",
            files={"file": ("big.txt", body, "text/plain")},
        )
        assert resp.status_code == 413
