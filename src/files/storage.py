"""MinIO storage client with two-client pattern for internal ops and pre-signed URLs."""

from datetime import timedelta
from io import BytesIO

import urllib3
from fastapi.concurrency import run_in_threadpool
from minio import Minio
from minio.error import S3Error

from files.exceptions import StorageError
from utils.logger import get_logger

logger = get_logger(__name__)


class MinIOStorage:
    """Wraps two MinIO clients: internal (server-to-server) and external (pre-signed URLs)."""

    def __init__(
        self,
        internal_endpoint: str,
        external_endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        bucket_name: str = "talos-uploads",
    ):
        self.bucket_name = bucket_name

        http_client = urllib3.PoolManager(
            num_pools=10,
            maxsize=10,
            timeout=urllib3.Timeout(connect=5, read=30),
            retries=urllib3.Retry(total=3, backoff_factor=0.2),
        )

        self._internal = Minio(
            internal_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            http_client=http_client,
        )

        self._external = Minio(
            external_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    async def ensure_bucket(self):
        """Create the uploads bucket if it doesn't exist."""
        try:
            exists = await run_in_threadpool(
                self._internal.bucket_exists, self.bucket_name
            )
            if not exists:
                await run_in_threadpool(
                    self._internal.make_bucket, self.bucket_name
                )
                logger.info(f"Created bucket: {self.bucket_name}")
            else:
                logger.info(f"Bucket already exists: {self.bucket_name}")
        except S3Error as e:
            raise StorageError("ensure_bucket", str(e)) from e

    async def upload_file(
        self,
        storage_key: str,
        data: BytesIO,
        size: int,
        content_type: str,
    ) -> str:
        """Upload a file to MinIO. Returns the etag."""
        try:
            result = await run_in_threadpool(
                self._internal.put_object,
                self.bucket_name,
                storage_key,
                data,
                size,
                content_type=content_type,
                part_size=10 * 1024 * 1024,
            )
            logger.info(f"Uploaded {storage_key} ({size} bytes)")
            return result.etag
        except S3Error as e:
            raise StorageError("upload_file", str(e)) from e

    async def download_file(self, storage_key: str) -> bytes:
        """Download a file from MinIO and return its contents."""
        try:
            response = await run_in_threadpool(
                self._internal.get_object, self.bucket_name, storage_key
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as e:
            raise StorageError("download_file", str(e)) from e

    async def download_file_to_path(self, storage_key: str, file_path: str):
        """Download a file from MinIO to a local path."""
        try:
            await run_in_threadpool(
                self._internal.fget_object, self.bucket_name, storage_key, file_path
            )
        except S3Error as e:
            raise StorageError("download_file_to_path", str(e)) from e

    async def delete_file(self, storage_key: str):
        """Delete a file from MinIO."""
        try:
            await run_in_threadpool(
                self._internal.remove_object, self.bucket_name, storage_key
            )
            logger.info(f"Deleted {storage_key}")
        except S3Error as e:
            raise StorageError("delete_file", str(e)) from e

    async def generate_presigned_download_url(
        self,
        storage_key: str,
        original_filename: str,
        expires: timedelta = timedelta(minutes=15),
    ) -> str:
        """Generate a pre-signed download URL using the external client."""
        try:
            url = await run_in_threadpool(
                self._external.presigned_get_object,
                self.bucket_name,
                storage_key,
                expires=expires,
                response_headers={
                    "response-content-disposition": f'attachment; filename="{original_filename}"'
                },
            )
            return url
        except S3Error as e:
            raise StorageError("generate_presigned_download_url", str(e)) from e

    async def generate_presigned_upload_url(
        self,
        storage_key: str,
        expires: timedelta = timedelta(minutes=30),
    ) -> str:
        """Generate a pre-signed upload URL using the external client."""
        try:
            url = await run_in_threadpool(
                self._external.presigned_put_object,
                self.bucket_name,
                storage_key,
                expires=expires,
            )
            return url
        except S3Error as e:
            raise StorageError("generate_presigned_upload_url", str(e)) from e
