import pytest
from io import BytesIO
from unittest.mock import MagicMock, patch, AsyncMock

from minio.error import S3Error

from files.exceptions import StorageError
from files.storage import MinIOStorage


def _make_storage():
    """Create a MinIOStorage with mocked Minio clients."""
    with patch("files.storage.Minio") as MockMinio:
        internal = MagicMock()
        external = MagicMock()
        MockMinio.side_effect = [internal, external]

        storage = MinIOStorage(
            internal_endpoint="localhost:9000",
            external_endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
        )
    return storage, internal, external


def _s3_error():
    return S3Error(
        code="TestError",
        message="test error",
        resource="/bucket/key",
        request_id="req-123",
        host_id="host-123",
        response=MagicMock(),
    )


@pytest.mark.unit
class TestMinIOStorage:
    @pytest.mark.asyncio
    async def test_ensure_bucket_creates_when_not_exists(self):
        storage, internal, _ = _make_storage()
        internal.bucket_exists.return_value = False
        await storage.ensure_bucket()
        internal.make_bucket.assert_called_once_with("talos-uploads")

    @pytest.mark.asyncio
    async def test_ensure_bucket_skips_when_exists(self):
        storage, internal, _ = _make_storage()
        internal.bucket_exists.return_value = True
        await storage.ensure_bucket()
        internal.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_bucket_raises_storage_error(self):
        storage, internal, _ = _make_storage()
        internal.bucket_exists.side_effect = _s3_error()
        with pytest.raises(StorageError):
            await storage.ensure_bucket()

    @pytest.mark.asyncio
    async def test_upload_file_returns_etag(self):
        storage, internal, _ = _make_storage()
        result = MagicMock()
        result.etag = "abc-etag"
        internal.put_object.return_value = result

        etag = await storage.upload_file("key", BytesIO(b"data"), 4, "text/plain")
        assert etag == "abc-etag"

    @pytest.mark.asyncio
    async def test_upload_file_passes_correct_args(self):
        storage, internal, _ = _make_storage()
        result = MagicMock()
        result.etag = "etag"
        internal.put_object.return_value = result

        data = BytesIO(b"hello")
        await storage.upload_file("my/key", data, 5, "text/plain")

        call_args = internal.put_object.call_args
        assert call_args[0][0] == "talos-uploads"  # bucket
        assert call_args[0][1] == "my/key"  # key
        assert call_args[0][2] is data  # data
        assert call_args[0][3] == 5  # size

    @pytest.mark.asyncio
    async def test_upload_file_raises_storage_error(self):
        storage, internal, _ = _make_storage()
        internal.put_object.side_effect = _s3_error()
        with pytest.raises(StorageError):
            await storage.upload_file("key", BytesIO(b"data"), 4, "text/plain")

    @pytest.mark.asyncio
    async def test_download_file_returns_bytes_and_releases(self):
        storage, internal, _ = _make_storage()
        response = MagicMock()
        response.read.return_value = b"file-content"
        internal.get_object.return_value = response

        result = await storage.download_file("key")
        assert result == b"file-content"
        response.close.assert_called_once()
        response.release_conn.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_file_to_path_calls_fget(self):
        storage, internal, _ = _make_storage()
        await storage.download_file_to_path("key", "/tmp/test")
        internal.fget_object.assert_called_once_with("talos-uploads", "key", "/tmp/test")

    @pytest.mark.asyncio
    async def test_delete_file_calls_remove_object(self):
        storage, internal, _ = _make_storage()
        await storage.delete_file("key")
        internal.remove_object.assert_called_once_with("talos-uploads", "key")

    @pytest.mark.asyncio
    async def test_presigned_download_uses_external_client(self):
        storage, internal, external = _make_storage()
        external.presigned_get_object.return_value = "http://url"
        url = await storage.generate_presigned_download_url("key", "file.pdf")
        assert url == "http://url"
        external.presigned_get_object.assert_called_once()
        internal.presigned_get_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_presigned_download_sets_content_disposition(self):
        storage, _, external = _make_storage()
        external.presigned_get_object.return_value = "http://url"
        await storage.generate_presigned_download_url("key", "report.pdf")

        call_kwargs = external.presigned_get_object.call_args
        headers = call_kwargs.kwargs.get("response_headers", {})
        assert "report.pdf" in headers.get("response-content-disposition", "")

    @pytest.mark.asyncio
    async def test_presigned_upload_uses_external_client(self):
        storage, internal, external = _make_storage()
        external.presigned_put_object.return_value = "http://upload-url"
        url = await storage.generate_presigned_upload_url("key")
        assert url == "http://upload-url"
        external.presigned_put_object.assert_called_once()
        internal.presigned_put_object.assert_not_called()
