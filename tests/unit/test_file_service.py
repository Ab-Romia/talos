import hashlib
import uuid
from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from files.constants import MAX_FILE_SIZE
from files.exceptions import FileTooLarge, UnsupportedFileType
from files.models import FileAttachment, ProcessingStatus
from files.service import FileService


def _make_upload_file(content: bytes = b"hello world", filename: str = "test.txt"):
    """Create a mock UploadFile."""
    mock = AsyncMock()
    mock.filename = filename

    buf = BytesIO(content)
    mock.file = buf
    mock.read = AsyncMock(return_value=content[:2048])
    mock.seek = AsyncMock(side_effect=lambda pos: buf.seek(pos))

    return mock


@pytest.mark.unit
class TestFileServiceUpload:
    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_detects_mime_via_magic(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file()

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        mock_magic.assert_called_once()
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="video/mp4")
    async def test_upload_rejects_unsupported_mime(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file()

        with pytest.raises(UnsupportedFileType):
            await svc.upload(upload, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_rejects_oversized_file(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        # Create a file object whose seek-to-end reports > MAX_FILE_SIZE
        big_buf = BytesIO(b"x")
        big_buf.seek = lambda offset, whence=0: MAX_FILE_SIZE + 1 if whence == 2 else 0
        big_buf.tell = lambda: MAX_FILE_SIZE + 1
        big_buf.read = lambda size=-1: b""

        upload = AsyncMock()
        upload.filename = "big.txt"
        upload.file = big_buf
        upload.read = AsyncMock(return_value=b"x" * 2048)
        upload.seek = AsyncMock()

        with pytest.raises(FileTooLarge):
            await svc.upload(upload, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_generates_key_with_chatroom(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file(filename="doc.txt")
        chatroom_id = uuid.uuid4()

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4(), chatroom_id)
        assert str(chatroom_id) in result.storage_key

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_generates_key_general_without_chatroom(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file(filename="doc.txt")

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4(), None)
        assert "general" in result.storage_key

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_computes_sha256(self, mock_magic, mock_storage):
        content = b"checksum test content"
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file(content=content, filename="test.txt")

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        expected = hashlib.sha256(content).hexdigest()
        assert result.checksum == expected

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_calls_storage(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file()

        await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        mock_storage.upload_file.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_persists_to_db(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file()

        await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_sets_status_uploaded(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file()

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        assert result.processing_status == ProcessingStatus.UPLOADED


@pytest.mark.unit
class TestFileServiceQueries:
    def test_get_file_returns_none_for_missing(self):
        db = MagicMock()
        db.scalar.return_value = None
        svc = FileService(db, storage=None)

        result = svc.get_file(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url_returns_none_when_not_found(self, mock_storage):
        db = MagicMock()
        db.scalar.return_value = None
        svc = FileService(db, mock_storage)

        result = await svc.get_download_url(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url_returns_tuple(self, mock_storage):
        db = MagicMock()
        file_record = MagicMock()
        file_record.storage_key = "key"
        file_record.original_filename = "test.pdf"
        db.scalar.return_value = file_record
        svc = FileService(db, mock_storage)

        result = await svc.get_download_url(uuid.uuid4(), uuid.uuid4())
        assert result is not None
        url, filename = result
        assert filename == "test.pdf"


@pytest.mark.unit
class TestFileServiceDelete:
    def test_soft_delete_sets_deleted_at(self):
        db = MagicMock()
        file_record = MagicMock(spec=FileAttachment)
        file_record.deleted_at = None
        db.scalar.return_value = file_record
        svc = FileService(db, storage=None)

        with patch("files.service.delete_file_chunks", create=True):
            svc.soft_delete(uuid.uuid4(), uuid.uuid4())

        assert file_record.deleted_at is not None
        db.commit.assert_called()

    def test_soft_delete_calls_vector_cleanup(self):
        db = MagicMock()
        file_record = MagicMock(spec=FileAttachment)
        file_record.deleted_at = None
        db.scalar.return_value = file_record
        svc = FileService(db, storage=None)

        mock_del = MagicMock()
        mock_rag_vs = MagicMock(delete_file_chunks=mock_del)
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.vector_store": mock_rag_vs}):
            svc.soft_delete(uuid.uuid4(), uuid.uuid4())
        mock_del.assert_called_once()

    def test_soft_delete_tolerates_vector_failure(self):
        db = MagicMock()
        file_record = MagicMock(spec=FileAttachment)
        file_record.deleted_at = None
        db.scalar.return_value = file_record
        svc = FileService(db, storage=None)

        mock_rag_vs = MagicMock(delete_file_chunks=MagicMock(side_effect=Exception("milvus down")))
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.vector_store": mock_rag_vs}):
            result = svc.soft_delete(uuid.uuid4(), uuid.uuid4())

        # Should not raise, should return the file
        assert result is not None

    def test_attach_idempotent(self):
        db = MagicMock()
        file_record = MagicMock()
        msg = MagicMock()
        db.scalar.side_effect = [file_record, msg]
        # Existing association found
        existing = MagicMock()
        db.execute.return_value.first.return_value = existing
        svc = FileService(db, storage=None)

        result = svc.attach_to_message(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert result is True

    def test_attach_returns_false_when_message_not_found(self):
        db = MagicMock()
        file_record = MagicMock()
        db.scalar.side_effect = [file_record, None]  # file found, message not
        svc = FileService(db, storage=None)

        result = svc.attach_to_message(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert result is False


@pytest.mark.unit
class TestFileServiceUploadEdgeCases:
    @pytest.mark.asyncio
    @patch("files.service.magic.from_buffer", return_value="text/plain")
    async def test_upload_handles_no_extension(self, mock_magic, mock_storage):
        db = MagicMock()
        svc = FileService(db, mock_storage)
        upload = _make_upload_file(filename="README")

        result = await svc.upload(upload, uuid.uuid4(), uuid.uuid4())
        assert not result.storage_key.endswith(".")


@pytest.mark.unit
class TestFileServiceListFiles:
    def test_list_files_empty_results(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        svc = FileService(db, storage=None)

        files, cursor = svc.list_files(uuid.uuid4())
        assert files == []
        assert cursor is None

    def test_list_files_invalid_cursor_ignored(self):
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        svc = FileService(db, storage=None)

        files, cursor = svc.list_files(uuid.uuid4(), cursor="not-a-valid-cursor")
        assert files == []
        assert cursor is None

    def test_list_files_returns_next_cursor_when_more(self):
        db = MagicMock()
        records = []
        for i in range(21):
            r = MagicMock()
            r.created_at = datetime(2025, 1, 1, 0, 0, i)
            r.id = uuid.uuid4()
            records.append(r)
        db.scalars.return_value.all.return_value = records
        svc = FileService(db, storage=None)

        files, cursor = svc.list_files(uuid.uuid4(), limit=20)
        assert len(files) == 20
        assert cursor is not None
        assert "|" in cursor

    def test_list_files_no_cursor_when_exactly_at_limit(self):
        db = MagicMock()
        records = []
        for i in range(20):
            r = MagicMock()
            r.created_at = datetime(2025, 1, 1, 0, 0, i)
            r.id = uuid.uuid4()
            records.append(r)
        db.scalars.return_value.all.return_value = records
        svc = FileService(db, storage=None)

        files, cursor = svc.list_files(uuid.uuid4(), limit=20)
        assert len(files) == 20
        assert cursor is None
