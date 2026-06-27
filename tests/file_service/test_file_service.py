import hashlib
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from config import cfg
from files.errors import FileTooLarge, UnsupportedFileType
from files.model import File, FileStatus, MessageFile
from files.service__ import FileService


# TODO: use actual test files
@pytest.mark.unit
class TestFileServiceUpload:
    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_detects_mime_via_magic(self, mock_magic, test_workspace, test_user, test_uploaded_file,
                                                 file_service):
        result = await file_service.upload(test_uploaded_file, test_user.id, test_workspace.id)
        mock_magic.assert_called_once()
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="video/mp4")
    async def test_upload_rejects_unsupported_mime(self, test_workspace, test_user, test_uploaded_file, file_service):
        with pytest.raises(UnsupportedFileType):
            await file_service.upload(test_uploaded_file, test_user.id, test_workspace.id)

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_rejects_oversized_file(self, test_workspace, test_user, test_uploaded_file,
                                                 file_service):
        large_content = b"x" * (cfg().files.max_size + 1)
        large_file = test_uploaded_file(filename="large.txt", content=large_content)

        with pytest.raises(FileTooLarge):
            await file_service.upload(large_file, test_user.id, test_workspace.id)

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_computes_sha256(
            self, mock_magic, mock_storage, db_session, test_workspace, test_user, test_uploaded_file
    ):
        content = b"checksum test content"
        svc = FileService(db_session, mock_storage)
        test_uploaded_file = test_uploaded_file(content=content, filename="test.txt")

        result = await svc.upload(upload, test_user.id, test_workspace.id)
        expected = hashlib.sha256(content).hexdigest()
        assert result.sha256checksum == expected

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_calls_storage(
            self, mock_magic, mock_storage, db_session, test_workspace, test_user, test_uploaded_file
    ):
        svc = FileService(db_session, mock_storage)

        await svc.upload(test_uploaded_file, test_user.id, test_workspace.id)
        mock_storage.upload_file.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_persists_to_db(self, mock_storage, db_session, test_workspace, test_user,
                                         test_uploaded_file):
        svc = FileService(db_session, mock_storage)

        result = await svc.upload(test_uploaded_file, test_user.id, test_workspace.id)
        stored = db_session.get(File, result.id)

        assert stored is not None
        assert stored.filename == "test.txt"
        assert stored.content_type == "text/plain"
        assert stored.status == FileStatus.UPLOADED

    @pytest.mark.asyncio
    @patch("files.service.magic.from_descriptor", return_value="text/plain")
    async def test_upload_sets_status_uploaded(
            self, mock_magic, mock_storage, db_session, test_workspace, test_user, test_uploaded_file
    ):
        svc = FileService(db_session, mock_storage)

        result = await svc.upload(test_uploaded_file, test_user.id, test_workspace.id)
        assert result.status == FileStatus.UPLOADED


@pytest.mark.unit
class TestFileServiceQueries:
    def test_get_file_returns_none_for_missing(self, db_session):
        svc = FileService(db_session, storage=None)

        result = svc.get_file(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url_returns_none_when_not_found(self, db_session, mock_storage):
        svc = FileService(db_session, mock_storage)

        result = await svc.get_download_url(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url_returns_tuple(
            self, db_session, mock_storage, test_workspace, test_file_record
    ):
        mock_storage.generate_presigned_download_url.return_value = "http://localhost:9000/presigned"
        test_file_record.filename = "test.pdf"
        db_session.flush()
        svc = FileService(db_session, mock_storage)

        result = await svc.get_download_url(test_file_record.id)
        assert result is not None
        url, filename = result
        assert url == "http://localhost:9000/presigned"
        assert filename == "test.pdf"
        mock_storage.generate_presigned_download_url.assert_awaited_once_with(
            storage_key=test_file_record.id.hex,
            original_filename="test.pdf",
        )


@pytest.mark.unit
class TestFileServiceDelete:
    def test_soft_delete_sets_deleted_at(self, db_session, test_workspace, test_file_record):
        svc = FileService(db_session, storage=None)

        svc.soft_delete(test_file_record.id, test_workspace.id)

        db_session.refresh(test_file_record)
        assert test_file_record.deleted_at is not None

    def test_soft_delete_calls_vector_cleanup_scoped_to_workspace(
            self, db_session, test_workspace, indexed_file_record
    ):
        svc = FileService(db_session, storage=None)

        mock_del = MagicMock()
        mock_rag_vs = MagicMock(delete_file_chunks=mock_del)
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.vector_store": mock_rag_vs}):
            svc.soft_delete(indexed_file_record.id, test_workspace.id)

        mock_del.assert_called_once_with(str(indexed_file_record.id), workspace_id=str(test_workspace.id))
        db_session.refresh(indexed_file_record)
        assert indexed_file_record.deleted_at is not None

    def test_soft_delete_aborts_on_vector_failure(
            self, db_session, test_workspace, indexed_file_record
    ):
        """Audit fix: vector cleanup must succeed before the row is tombstoned,
        otherwise we leave orphaned chunks queryable in Milvus."""
        svc = FileService(db_session, storage=None)

        mock_rag_vs = MagicMock(
            delete_file_chunks=MagicMock(side_effect=Exception("milvus down"))
        )
        with patch.dict("sys.modules", {"rag": MagicMock(), "rag.vector_store": mock_rag_vs}):
            with pytest.raises(Exception, match="milvus down"):
                svc.soft_delete(indexed_file_record.id, test_workspace.id)

        db_session.refresh(indexed_file_record)
        assert indexed_file_record.deleted_at is None  # not tombstoned

    def test_attach_idempotent(
            self, db_session, test_workspace, channel_file_record, test_message
    ):
        mf = MessageFile(message_id=test_message.id, file_id=channel_file_record.id)
        db_session.add(mf)
        db_session.commit()

        svc = FileService(db_session, storage=None)

        result = svc.attach_to_message(channel_file_record.id, test_message.id)
        assert result is True

    def test_attach_returns_false_when_message_not_found(
            self, db_session, test_file_record
    ):
        svc = FileService(db_session, storage=None)

        result = svc.attach_to_message(test_file_record.id, uuid.uuid4())
        assert result is False


@pytest.mark.unit
class TestFileServiceListFiles:
    def test_list_files_empty_results(self, db_session, test_workspace):
        svc = FileService(db_session, storage=None)

        files, cursor = svc.list_files(test_workspace.id)
        assert files == []
        assert cursor is None

    def test_list_files_invalid_cursor_ignored(self, db_session, test_workspace):
        svc = FileService(db_session, storage=None)

        files, cursor = svc.list_files(test_workspace.id, cursor="not-a-valid-cursor")
        assert files == []
        assert cursor is None

    def test_list_files_returns_next_cursor_when_more(
            self, db_session, test_workspace, test_user
    ):
        for i in range(21):
            record = File(
                workspace_id=test_workspace.id,
                uploader_id=test_user.id,
                original_filename=f"file-{i}.txt",
                content_type="text/plain",
                size_bytes=100,
                checksum=f"checksum-{i}",
                processing_status=FileStatus.UPLOADED,
            )
            db_session.add(record)
            db_session.flush()
            record.created_at = datetime(2025, 1, 1, 0, 0, i)
        db_session.flush()

        svc = FileService(db_session, storage=None)

        files, cursor = svc.list_files(test_workspace.id, limit=20)
        assert len(files) == 20
        assert cursor is not None
        assert "|" in cursor

    def test_list_files_no_cursor_when_exactly_at_limit(
            self, db_session, test_workspace, test_user
    ):
        for i in range(20):
            record = File(
                workspace_id=test_workspace.id,
                uploader_id=test_user.id,
                original_filename=f"file-{i}.txt",
                content_type="text/plain",
                size_bytes=100,
                checksum=f"checksum-{i}",
                processing_status=FileStatus.UPLOADED,
            )
            db_session.add(record)
            db_session.flush()
            record.created_at = datetime(2025, 1, 1, 0, 0, i)
        db_session.flush()

        svc = FileService(db_session, storage=None)

        files, cursor = svc.list_files(test_workspace.id, limit=20)
        assert len(files) == 20
        assert cursor is None
