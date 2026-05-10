"""Live verification of the streaming upload path.

Streams a file to MinIO through HashingReader (the same wrapper FileService
uses), downloads it back, and prints the SHA-256s + process RSS so you can
see the streaming actually works against real storage.

Run:
    uv run python scripts/check_streaming.py
    uv run python scripts/check_streaming.py /path/to/your/file
"""

import hashlib
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from minio import Minio  # noqa: E402

from files.streaming import HashingReader  # noqa: E402


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BUCKET = os.getenv("MINIO_BUCKET", "talos-streaming-check")
PART_SIZE = 10 * 1024 * 1024  # same as MinIOStorage.upload_file


def make_random_file(size_mb: int = 49) -> str:
    path = tempfile.mktemp(prefix="streaming-check-", suffix=".bin")
    subprocess.run(
        ["dd", "if=/dev/urandom", f"of={path}", "bs=1M", f"count={size_mb}", "status=none"],
        check=True,
    )
    return path


def reference_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fmt_bytes(n: int) -> str:
    return f"{n:,}"


def main() -> int:
    if len(sys.argv) > 1:
        path = sys.argv[1]
        cleanup = False
    else:
        path = make_random_file(49)
        cleanup = True

    size = os.path.getsize(path)
    expected_sha = reference_sha256(path)

    print(f"file:        {path}")
    print(f"size:        {fmt_bytes(size)} bytes ({size / 1024 / 1024:.1f} MiB)")
    print(f"expected:    {expected_sha}")

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )
    if not client.bucket_exists(BUCKET):
        client.make_bucket(BUCKET)

    object_name = f"streaming-check/{Path(path).name}"

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    with open(path, "rb") as f:
        reader = HashingReader(f)
        client.put_object(
            BUCKET,
            object_name,
            reader,
            length=size,
            content_type="application/octet-stream",
            part_size=PART_SIZE,
        )

    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    if reader.checksum != expected_sha:
        print(f"FAIL: streaming SHA-256 {reader.checksum} != reference {expected_sha}")
        return 1
    if reader.bytes_read != size:
        print(f"FAIL: bytes_read {reader.bytes_read} != size {size}")
        return 1

    response = client.get_object(BUCKET, object_name)
    try:
        h = hashlib.sha256()
        downloaded = 0
        for chunk in response.stream(1024 * 1024):
            h.update(chunk)
            downloaded += len(chunk)
        round_trip_sha = h.hexdigest()
    finally:
        response.close()
        response.release_conn()

    if round_trip_sha != expected_sha:
        print(f"FAIL: round-trip SHA-256 {round_trip_sha} != reference {expected_sha}")
        return 1
    if downloaded != size:
        print(f"FAIL: round-trip size {downloaded} != reference {size}")
        return 1

    client.remove_object(BUCKET, object_name)
    if cleanup:
        os.unlink(path)

    print(f"streamed:    {reader.checksum}")
    print(f"round-trip:  {round_trip_sha}")
    print(f"max RSS:     {fmt_bytes(rss_before)} kB before, {fmt_bytes(rss_after)} kB after")
    print(f"delta RSS:   {fmt_bytes(rss_after - rss_before)} kB for a {size / 1024 / 1024:.1f} MiB upload")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
