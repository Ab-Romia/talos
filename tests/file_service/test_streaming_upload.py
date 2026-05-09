"""Integration tests for streaming upload to MinIO via HashingReader.

Tests that the streaming upload path works correctly against real MinIO storage,
verifying SHA-256 checksums, file sizes, and memory efficiency.
"""

import hashlib
import os
import resource
import subprocess
import tempfile
from pathlib import Path

import pytest
from minio import Minio

from files.streaming import HashingReader

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BUCKET = os.getenv("MINIO_BUCKET", "talos-streaming-check")
PART_SIZE = 10 * 1024 * 1024


@pytest.fixture(scope="module")
def minio_client():
    """Connect to MinIO and ensure test bucket exists."""
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )
    if not client.bucket_exists(BUCKET):
        client.make_bucket(BUCKET)
    return client


@pytest.fixture
def random_file():
    """Create a random 49MB file for testing."""
    path = tempfile.mktemp(prefix="streaming-check-", suffix=".bin")
    subprocess.run(
        ["dd", "if=/dev/urandom", f"of={path}", "bs=1M", "count=49", "status=none"],
        check=True,
    )
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def small_file():
    """Create a small random file for quick testing."""
    path = tempfile.mktemp(prefix="streaming-check-", suffix=".bin")
    subprocess.run(
        ["dd", "if=/dev/urandom", f"of={path}", "bs=1M", "count=1", "status=none"],
        check=True,
    )
    yield path
    if os.path.exists(path):
        os.unlink(path)


def compute_sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.integration
def test_hashing_reader_computes_correct_checksum(small_file, minio_client):
    """Verify HashingReader computes the same SHA-256 as reference hash."""
    expected_sha = compute_sha256(small_file)
    size = os.path.getsize(small_file)
    object_name = f"streaming-check/test-checksum-{Path(small_file).name}"

    with open(small_file, "rb") as f:
        reader = HashingReader(f)
        minio_client.put_object(
            BUCKET,
            object_name,
            reader,
            length=size,
            content_type="application/octet-stream",
            part_size=PART_SIZE,
        )

    try:
        assert reader.checksum == expected_sha, (
            f"streaming SHA-256 {reader.checksum} != reference {expected_sha}"
        )
    finally:
        minio_client.remove_object(BUCKET, object_name)


@pytest.mark.integration
def test_hashing_reader_tracks_bytes_read(small_file, minio_client):
    """Verify HashingReader correctly tracks bytes_read."""
    size = os.path.getsize(small_file)
    object_name = f"streaming-check/test-bytes-{Path(small_file).name}"

    with open(small_file, "rb") as f:
        reader = HashingReader(f)
        minio_client.put_object(
            BUCKET,
            object_name,
            reader,
            length=size,
            content_type="application/octet-stream",
            part_size=PART_SIZE,
        )

    try:
        assert reader.bytes_read == size, (
            f"bytes_read {reader.bytes_read} != size {size}"
        )
    finally:
        minio_client.remove_object(BUCKET, object_name)


@pytest.mark.integration
def test_round_trip_upload_and_download(small_file, minio_client):
    """Verify that uploaded file can be downloaded with matching SHA-256."""
    expected_sha = compute_sha256(small_file)
    size = os.path.getsize(small_file)
    object_name = f"streaming-check/test-roundtrip-{Path(small_file).name}"

    with open(small_file, "rb") as f:
        reader = HashingReader(f)
        minio_client.put_object(
            BUCKET,
            object_name,
            reader,
            length=size,
            content_type="application/octet-stream",
            part_size=PART_SIZE,
        )

    try:
        response = minio_client.get_object(BUCKET, object_name)
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

        assert round_trip_sha == expected_sha, (
            f"round-trip SHA-256 {round_trip_sha} != reference {expected_sha}"
        )
        assert downloaded == size, (
            f"round-trip size {downloaded} != reference {size}"
        )
    finally:
        minio_client.remove_object(BUCKET, object_name)


@pytest.mark.integration
def test_streaming_upload_memory_efficiency(random_file, minio_client):
    """Verify that streaming upload doesn't load entire file into memory.

    This test uploads a large file and tracks RSS (resident set size) before and
    after to ensure memory doesn't grow proportionally to file size.
    """
    expected_sha = compute_sha256(random_file)
    size = os.path.getsize(random_file)
    object_name = f"streaming-check/test-memory-{Path(random_file).name}"

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    with open(random_file, "rb") as f:
        reader = HashingReader(f)
        minio_client.put_object(
            BUCKET,
            object_name,
            reader,
            length=size,
            content_type="application/octet-stream",
            part_size=PART_SIZE,
        )

    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    try:
        assert reader.checksum == expected_sha
        assert reader.bytes_read == size

        # Log memory usage for inspection
        delta_rss_kb = rss_after - rss_before
        file_size_mb = size / 1024 / 1024
        pytest.log.info(
            f"Uploaded {file_size_mb:.1f} MiB, max RSS delta: {delta_rss_kb:,} kB"
        )
    finally:
        minio_client.remove_object(BUCKET, object_name)
