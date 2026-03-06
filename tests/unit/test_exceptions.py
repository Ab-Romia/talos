import pytest

from files.exceptions import (
    FileError,
    FileTooLarge,
    FileNotFoundError,
    StorageError,
    UnsupportedFileType,
)


@pytest.mark.unit
class TestExceptions:
    def test_file_too_large_attrs(self):
        exc = FileTooLarge(size=100, max_size=50)
        assert exc.size == 100
        assert exc.max_size == 50
        assert "100" in str(exc)
        assert "50" in str(exc)

    def test_unsupported_file_type_attrs(self):
        exc = UnsupportedFileType("video/mp4")
        assert exc.mime_type == "video/mp4"
        assert "video/mp4" in str(exc)

    def test_file_not_found_attrs(self):
        exc = FileNotFoundError("abc-123")
        assert exc.file_id == "abc-123"
        assert "abc-123" in str(exc)

    def test_storage_error_attrs(self):
        exc = StorageError("upload", "connection refused")
        assert exc.operation == "upload"
        assert exc.detail == "connection refused"
        assert "upload" in str(exc)

    def test_hierarchy(self):
        assert issubclass(FileTooLarge, FileError)
        assert issubclass(UnsupportedFileType, FileError)
        assert issubclass(FileNotFoundError, FileError)
        assert issubclass(StorageError, FileError)
