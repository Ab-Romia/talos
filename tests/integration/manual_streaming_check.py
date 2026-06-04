"""Manual smoke test for the streaming upload path.

Runs FileService.upload against real MinIO with a real file, then downloads
it back and verifies the SHA-256 round-trips. No HTTP, no auth, no DB.

Usage:
    PYTHONPATH=src uv run python tests/integration/manual_streaming_check.py /tmp/big.txt
"""

import asyncio
import hashlib
import resource
import sys
import uuid
from io import BufferedReader, FileIO
from unittest.mock import MagicMock

from starlette.datastructures import UploadFile

from config import cfg
from files.service import FileService
from files.storage import S3Storage


async def main(path: str) -> None:
    with open(path, "rb") as f:
        body = f.read()
    expected_sha = hashlib.sha256(body).hexdigest()

    storage_cfg = cfg().minio
    storage = S3Storage(
        internal_endpoint=storage_cfg.internal_endpoint,
        public_endpoint=storage_cfg.external_endpoint,
        access_key=storage_cfg.access_key,
        secret_key=storage_cfg.secret_key,
        bucket_name=storage_cfg.bucket_name,
    )
    await storage.ensure_bucket()

    db = MagicMock()
    svc = FileService(db, storage)

    upload = UploadFile(
        file=BufferedReader(FileIO(path, "rb")),
        filename=path.rsplit("/", 1)[-1],
    )

    workspace_id = uuid.uuid4()
    uploader_id = uuid.uuid4()

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = await svc.upload(upload, workspace_id, uploader_id)
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    assert result.checksum == expected_sha, (
        f"checksum mismatch: service={result.checksum} expected={expected_sha}"
    )

    downloaded = await storage.download_file(result.storage_key)
    assert hashlib.sha256(downloaded).hexdigest() == expected_sha, "round-trip mismatch"
    assert len(downloaded) == len(body), "size mismatch"

    print(f"file:        {path}")
    print(f"size:        {len(body):,} bytes")
    print(f"sha256:      {expected_sha}")
    print(f"storage key: {result.storage_key}")
    print(f"max RSS:     {rss_before:,} kB before -> {rss_after:,} kB after upload")
    print("OK: streaming upload + SHA-256 round-trip verified against real MinIO")

    await storage.delete_file(result.storage_key)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
