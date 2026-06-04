from datetime import timedelta
from typing import BinaryIO, Protocol, Literal

import aioboto3

from config.config_ import MinIOConfig
from files.schemas import FileMetadata
from utils.logger import get_logger

logger = get_logger(__name__)


class StorageBackend(Protocol):
    async def put(self, key: str, stream: BinaryIO, metadata: FileMetadata) -> str: ...

    async def get(self, key: str) -> BinaryIO: ...

    async def delete(self, key: str) -> None: ...

    async def presigned_url(
            self, key: str, expiry: timedelta,
            operation: Literal["get_object", "put_object"]
    ) -> str | None:
        ...


class S3Storage(StorageBackend):
    """A simple S3-compatible async storage backend using `aioboto3`."""

    def __init__(self, config: MinIOConfig):
        self.bucket_name = config.bucket_name
        self._config = config
        self._session = aioboto3.Session(
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key.get_secret_value(),
        )
        self._internal_client = None
        self._public_client = None

    async def connect(self):
        self._internal_client = await self._session.client("s3", endpoint_url=self._config.internal_endpoint,
                                                           use_ssl=self._config.secure).__aenter__()
        self._public_client = await self._session.client("s3", endpoint_url=self._config.public_endpoint,
                                                         use_ssl=self._config.secure).__aenter__()

    async def disconnect(self):
        if self._internal_client:
            await self._internal_client.__aexit__(None, None, None)
        if self._public_client:
            await self._public_client.__aexit__(None, None, None)

    async def put(self, key: str, stream: BinaryIO, metadata: FileMetadata) -> str:
        assert self._internal_client is not None, "Storage client not connected"
        result = await self._internal_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=stream,
            ContentType=metadata.content_type,
        )
        logger.info(f"Uploaded {key} ({metadata.size_bytes} bytes)")
        return result.etag

    async def get(self, key: str) -> BinaryIO:
        assert self._internal_client is not None, "Storage client not connected"
        response = await self._internal_client.get_object(Bucket=self.bucket_name, Key=key)
        return response["Body"]

    async def delete(self, key: str) -> None:
        assert self._internal_client is not None, "Storage client not connected"
        await self._internal_client.delete_object(Bucket=self.bucket_name, Key=key)
        logger.info(f"Deleted {key}")

    async def presigned_url(self, key: str, expiry: timedelta,
                            operation: Literal["get_object", "put_object"]) -> str | None:
        assert self._public_client is not None, "Storage client not connected"
        url = await self._public_client.generate_presigned_url(
            operation_name=operation,
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=int(expiry.total_seconds()),
        )
        return url
