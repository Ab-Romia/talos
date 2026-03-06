import uuid
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from files.models import FileAttachment, ProcessingStatus


@pytest.mark.unit
class TestProcessFile:
    def _make_ctx(self, file_record=None):
        """Create a mock ARQ context."""
        db = MagicMock()
        db.get.return_value = file_record
        factory = MagicMock(return_value=db)
        factory.return_value.__enter__ = MagicMock(return_value=db)
        factory.return_value.__exit__ = MagicMock(return_value=False)

        ctx = {"db_session_factory": factory, "minio_storage": MagicMock()}
        return ctx, db

    @pytest.mark.asyncio
    async def test_skips_when_not_found(self):
        ctx, db = self._make_ctx(file_record=None)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        # No exception, no status update
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_already_indexed(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.INDEXED
        ctx, db = self._make_ctx(file_record=record)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        # Should not change status
        assert record.processing_status == ProcessingStatus.INDEXED

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
    async def test_warns_unsupported_mime(self):
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "application/json"
        ctx, db = self._make_ctx(file_record=record)

        from processing.tasks import process_file
        await process_file(ctx, str(uuid.uuid4()))
        # Should still mark as INDEXED (no processor, no error)
        assert record.processing_status == ProcessingStatus.INDEXED

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
        file_id = uuid.uuid4()
        record = MagicMock(spec=FileAttachment)
        record.processing_status = ProcessingStatus.UPLOADED
        record.content_type = "text/plain"
        record.processing_error = None

        db = MagicMock()
        db.get.return_value = record
        factory = MagicMock(return_value=db)
        factory.return_value.__enter__ = MagicMock(return_value=db)
        factory.return_value.__exit__ = MagicMock(return_value=False)
        ctx = {"db_session_factory": factory, "minio_storage": MagicMock()}

        mock_proc_doc = AsyncMock(side_effect=RuntimeError("extraction failed"))
        with patch.dict("sys.modules", {"processing.documents": MagicMock(process_document=mock_proc_doc)}):
            from processing.tasks import process_file
            with pytest.raises(RuntimeError):
                await process_file(ctx, str(file_id))

        db.rollback.assert_called_once()
        assert record.processing_status == ProcessingStatus.FAILED
        assert record.processing_error is not None
