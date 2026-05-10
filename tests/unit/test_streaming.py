import hashlib
from io import BytesIO

import pytest

from files.streaming import HashingReader


@pytest.mark.unit
class TestHashingReader:
    def test_checksum_matches_hashlib_for_full_read(self):
        payload = b"the quick brown fox jumps over the lazy dog"
        reader = HashingReader(BytesIO(payload))

        # Drain the stream the way minio-py does, in arbitrary-sized chunks.
        out = b""
        while True:
            chunk = reader.read(8)
            if not chunk:
                break
            out += chunk

        assert out == payload
        assert reader.checksum == hashlib.sha256(payload).hexdigest()
        assert reader.bytes_read == len(payload)

    def test_chunked_reads_match_single_read(self):
        # Same bytes, different read patterns must produce the same hash —
        # otherwise the wrapper would corrupt uploads depending on how
        # minio-py decided to chunk them.
        payload = b"x" * 10_000 + b"y" * 10_000

        full = HashingReader(BytesIO(payload))
        full.read(-1)

        chunked = HashingReader(BytesIO(payload))
        while chunked.read(1024):
            pass

        assert full.checksum == chunked.checksum
        assert full.bytes_read == chunked.bytes_read == len(payload)

    def test_eof_returns_empty_and_does_not_advance_counters(self):
        reader = HashingReader(BytesIO(b"abc"))
        reader.read(-1)

        before = reader.bytes_read
        before_checksum = reader.checksum

        assert reader.read(1024) == b""
        assert reader.bytes_read == before
        assert reader.checksum == before_checksum

    def test_empty_stream_yields_sha256_of_empty(self):
        reader = HashingReader(BytesIO(b""))
        assert reader.read(1024) == b""
        assert reader.bytes_read == 0
        assert reader.checksum == hashlib.sha256(b"").hexdigest()
