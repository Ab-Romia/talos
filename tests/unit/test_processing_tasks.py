import uuid
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from files.model import FileAttachment, ProcessingStatus


@pytest.mark.unit
class TestProcessFile:
    def _make_ctx(self, file_record=None, execute_rowcount=None):
        """Create a mock ARQ context.

        execute_rowcount: if set to 0, the atomic UPDATE returns 0 rows (skip path).
        Leave as None to get a truthy MagicMock (claim path).
        """
        db = MagicMock()
        db.get.return_value = file_record
        if execute_rowcount is not None:
            db.execute.return_value.rowcount = execute_rowcount

        factory = MagicMock(return_value=db)
        factory.return_value.__enter__ = MagicMock(return_value=db)
        factory.return_value.__exit__ = MagicMock(return_value=False)

        ctx = {"db_session_factory": factory, "minio_storage": MagicMock()}
        return ctx, db

    @pytest.mark.asyncio
    async def test_skips_when_not_found(self):
        ctx, db = self._make_ctx(file_record=None, execute_rowcount=0)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        # Commit was called once (for the UPDATE), no status change
        assert db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_when_already_indexed(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.INDEXED
        ctx, db = self._make_ctx(file_record=record, execute_rowcount=0)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        # Should not change status
        assert record.processing_status == ProcessingStatus.INDEXED

    @pytest.mark.asyncio
    async def test_skips_when_already_processing(self):
        """Atomic claim: a file already in PROCESSING state must not be
        double-processed by a second concurrent ARQ worker."""
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.PROCESSING
        ctx, db = self._make_ctx(file_record=record, execute_rowcount=0)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        assert record.processing_status == ProcessingStatus.PROCESSING
        assert db.commit.call_count == 1  # only the UPDATE commit, no processing

    @pytest.mark.asyncio
    async def test_routes_document_mime(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "application/pdf"
        ctx, db = self._make_ctx(file_record=record)

        mock_proc_doc = AsyncMock()
        with patch.dict("sys.modules", {"processing.documents": MagicMock(process_document=mock_proc_doc)}):
            from processing.tasks import process_file
            await process_file(ctx, str(uuid.uuid4()))
        mock_proc_doc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_image_mime(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "image/png"
        ctx, db = self._make_ctx(file_record=record)

        mock_proc_img = AsyncMock()
        with patch.dict("sys.modules", {"processing.images": MagicMock(process_image=mock_proc_img)}):
            from processing.tasks import process_file
            await process_file(ctx, str(uuid.uuid4()))
        mock_proc_img.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unsupported_mime_marks_failed(self):
        """Audit fix: an unknown MIME must FAIL loudly, not silently INDEX
        with zero chunks. Reaching the dispatcher with a MIME outside the
        allow-list means the upload validator and the dispatcher disagree."""
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "application/json"
        ctx, db = self._make_ctx(file_record=record)

        from processing.tasks import process_file
        with pytest.raises(ValueError, match="No processor"):
            await process_file(ctx, str(uuid.uuid4()))
        assert record.processing_status == ProcessingStatus.FAILED
        assert "No processor" in (record.processing_error or "")

    @pytest.mark.asyncio
    async def test_sets_indexed_on_success(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "text/plain"
        ctx, db = self._make_ctx(file_record=record)

        mock_proc_doc = AsyncMock()
        with patch.dict("sys.modules", {"processing.documents": MagicMock(process_document=mock_proc_doc)}):
            from processing.tasks import process_file
            await process_file(ctx, str(uuid.uuid4()))
        assert record.processing_status == ProcessingStatus.INDEXED

    @pytest.mark.asyncio
    async def test_sets_failed_on_error(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "text/plain"
        record.processing_error = None
        ctx, db = self._make_ctx(file_record=record)

        mock_proc_doc = AsyncMock(side_effect=RuntimeError("extraction failed"))
        with patch.dict("sys.modules", {"processing.documents": MagicMock(process_document=mock_proc_doc)}):
            from processing.tasks import process_file
            with pytest.raises(RuntimeError):
                await process_file(ctx, str(uuid.uuid4()))

        db.rollback.assert_called_once()
        assert record.processing_status == ProcessingStatus.FAILED
        assert record.processing_error is not None
