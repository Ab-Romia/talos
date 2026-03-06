import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from files.models import FileAttachment, ProcessingStatus


@pytest.mark.unit
class TestFallbackExtract:
    def test_plain_text(self):
        from processing.documents import _fallback_extract

        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            path = f.name

        try:
            result = _fallback_extract(path, "text/plain")
            assert len(result) == 1
            assert result[0][0] == "Hello, world!"
            assert result[0][1]["page_number"] == 0
        finally:
            os.unlink(path)

    def test_markdown(self):
        from processing.documents import _fallback_extract

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Title\n\nSome content")
            f.flush()
            path = f.name

        try:
            result = _fallback_extract(path, "text/markdown")
            assert len(result) == 1
            assert "# Title" in result[0][0]
        finally:
            os.unlink(path)

    def test_unsupported_returns_empty(self):
        from processing.documents import _fallback_extract

        result = _fallback_extract("/tmp/nonexistent.pdf", "application/pdf")
        assert result == []


@pytest.mark.unit
class TestExtractText:
    def test_falls_back_on_import_error(self):
        from processing.documents import _extract_text

        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("fallback content")
            f.flush()
            path = f.name

        try:
            # _extract_text tries `from unstructured.partition.auto import partition`
            # If unstructured is not installed, it catches ImportError and uses fallback
            # We mock sys.modules to force the ImportError
            with patch.dict("sys.modules", {"unstructured": None, "unstructured.partition": None, "unstructured.partition.auto": None}):
                # Need to reload to pick up the mocked modules
                result = _extract_text(path, "text/plain")
                assert len(result) == 1
                assert "fallback content" in result[0][0]
        finally:
            os.unlink(path)


@pytest.mark.unit
class TestProcessDocument:
    def _make_record(self, content_type="text/plain", filename="test.txt"):
        record = MagicMock(spec=FileAttachment)
        record.id = uuid.uuid4()
        record.workspace_id = uuid.uuid4()
        record.original_filename = filename
        record.content_type = content_type
        record.storage_key = "test/key"
        record.processing_status = ProcessingStatus.PROCESSING
        record.chunk_count = None
        return record

    @pytest.mark.asyncio
    async def test_downloads_file(self, mock_storage):
        from processing.documents import process_document

        record = self._make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "w") as f:
                f.write("test content for download")

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        mock_rag_ingestion = MagicMock(ingest_file_chunks=MagicMock())
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.ingestion": mock_rag_ingestion}):
            await process_document(record, db, mock_storage)

        mock_storage.download_file_to_path.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_calls_ingest(self, mock_storage):
        from processing.documents import process_document

        record = self._make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "w") as f:
                f.write("some text content to chunk and ingest")

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        mock_ingest = MagicMock()
        mock_rag_ingestion = MagicMock(ingest_file_chunks=mock_ingest)
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.ingestion": mock_rag_ingestion}):
            await process_document(record, db, mock_storage)

        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_zero_chunks_no_text(self, mock_storage):
        from processing.documents import process_document

        record = self._make_record(content_type="application/pdf", filename="empty.pdf")
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(b"\x00\x00\x00")

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_document(record, db, mock_storage)
        assert record.chunk_count == 0

    @pytest.mark.asyncio
    async def test_cleans_up_temp_file(self, mock_storage):
        from processing.documents import process_document

        record = self._make_record()
        db = MagicMock()
        created_paths = []

        async def fake_download(key, path):
            created_paths.append(path)
            with open(path, "w") as f:
                f.write("temp content")

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        mock_rag_ingestion = MagicMock(ingest_file_chunks=MagicMock())
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.ingestion": mock_rag_ingestion}):
            await process_document(record, db, mock_storage)

        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0])
