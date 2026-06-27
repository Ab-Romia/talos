"""Unit tests for the processing task dispatcher (audit fixes)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from files.model import FileStatus


@pytest.mark.unit
class TestProcessFileDispatcher:
    @pytest.mark.asyncio
    async def test_unknown_mime_marks_failed(self, sample_file_record):
        """Audit nit #14: unknown MIME must FAIL, not silently INDEX."""
        from processing.tasks import process_file

        sample_file_record.content_type = "application/x-fictional"
        sample_file_record.status = FileStatus.UPLOADED

        db = MagicMock()
        db.get.return_value = sample_file_record
        db_factory = MagicMock(return_value=_ctx_db(db))
        ctx = {"db_session_factory": db_factory, "minio_storage": MagicMock()}

        with pytest.raises(ValueError, match="No processor"):
            await process_file(ctx, str(sample_file_record.id))

        assert sample_file_record.status == FileStatus.PROCESSING_FAILED
        assert "No processor" in (sample_file_record.processing_error or "")

    @pytest.mark.asyncio
    async def test_missing_row_during_processing_does_not_re_raise(self):
        """Audit bug #3: vanished file row should log + return, not retry forever."""
        from processing.tasks import process_file
        from files.model import File

        existing = MagicMock(spec=File)
        existing.id = uuid.uuid4()
        existing.processing_status = FileStatus.UPLOADED
        existing.content_type = "text/plain"

        db = MagicMock()
        # First .get returns the row; the post-rollback .get returns None
        db.get.side_effect = [existing, None]

        with patch("processing.documents.process_document", side_effect=RuntimeError("boom")):
            db_factory = MagicMock(return_value=_ctx_db(db))
            ctx = {"db_session_factory": db_factory, "minio_storage": MagicMock()}
            # Should NOT re-raise
            await process_file(ctx, str(existing.id))


def _ctx_db(db):
    """Wrap a MagicMock to behave like a context manager yielding the DB."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=db)
    cm.__exit__ = MagicMock(return_value=False)
    return cm
