import uuid

import fsspec
from s3fs import S3FileSystem

from config.config_ import MinIOConfig


class MinIOFileSystem(S3FileSystem):
    protocol = "minio"

    def __init__(self, config: MinIOConfig,
                 workspace_id: uuid.UUID,
                 channel_id: uuid.UUID | None = None):
        super().__init__(
            key=config.access_key,
            secret=config.secret_key.get_secret_value(),
            endpoint_url=config.internal_endpoint,
            use_ssl=config.secure,
            asynchronous=True,
        )
        self.bucket = config.bucket
        self.public_endpoint = config.public_endpoint or None
        self.ws_id = workspace_id
        self.ch_id = channel_id

    def split_path(self, path):
        """Map the user-facing path to a structured S3 key."""
        scope = f"{self.ws_id}/{self.ch_id or '.'}"
        path = path.lstrip("/")
        return super().split_path(f"{self.bucket}/{scope}/{path}")

    async def _url(self, path, expires=3600, client_method="get_object", **kwargs):
        url = await super()._url(path, expires=expires, client_method=client_method, **kwargs)

        if self.public_endpoint:
            url = url.replace(self.endpoint_url, self.public_endpoint)

        return url


fsspec.register_implementation("minio", MinIOFileSystem)
