import hashlib
from typing import BinaryIO


class HashingReader:
    """File-like wrapper that updates a SHA-256 hasher and a byte counter
    as bytes are read. Lets the upload and the checksum share one read
    pass over the body instead of buffering it twice."""

    def __init__(self, source: BinaryIO):
        self._source = source
        self._hasher = hashlib.sha256()
        self._bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        if chunk:
            self._bytes_read += len(chunk)
            self._hasher.update(chunk)
        return chunk

    @property
    def checksum(self) -> str:
        return self._hasher.hexdigest()

    @property
    def bytes_read(self) -> int:
        return self._bytes_read
