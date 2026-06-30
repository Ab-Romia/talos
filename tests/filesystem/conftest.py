"""
Filesystem-scoped fixtures for tests/files/.

Provides:
  - minio_fs     — real MinIOFileSystem via testcontainers
  - gdrive_fs    — GDriveFileSystem with aiogoogle transport mocked
  - fs           — parametrized over both (use in test_filesystem.py)
  - tmp_prefix   — per-test isolated path prefix to avoid cross-test pollution

All other fixtures (test_user, workspace, channel, auth_headers, db_session,
path, client) are assumed to exist in the root conftest.
"""

from __future__ import annotations

import os
import uuid
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import cfg
from filesystem.storage.gdrive.fs import GDriveFileSystem
from filesystem.storage.minio import MinIOFileSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_prefix() -> str:
    """Return a short unique prefix safe for use in both GDrive and MinIO paths."""
    return f"test/{uuid.uuid4().hex[:12]}"


@pytest.fixture
def minio_fs(test_workspace, test_channel) -> MinIOFileSystem:
    """
    MinIOFileSystem pointed at the session-scoped container.
    Bucket is created fresh per test via a unique prefix — no teardown needed.
    """
    fs = MinIOFileSystem(
        config=cfg().minio,
        workspace_id=test_workspace,
        channel_id=test_channel
    )
    # Ensure bucket exists (idempotent)
    if not fs.exists("test-bucket"):
        fs.mkdir("test-bucket")
    return fs


class _InMemoryDriveTransport:
    """
    Minimal in-memory backing store that mimics the aiogoogle Drive API
    surface used by GDriveFileSystem.

    Stores files as:  _blobs[path] = bytes
    Stores metadata:  _meta[path]  = {"name": str, "size": int, "mimeType": str, ...}

    Only the methods GDriveFileSystem actually calls are implemented.
    Any call to an unimplemented method raises AttributeError immediately
    so tests fail loudly instead of silently swallowing behaviour.
    """

    def __init__(self):
        self._blobs: dict[str, bytes] = {}
        self._meta: dict[str, dict] = {}
        # Maps parent_path → set of child paths for ls/directory support
        self._children: dict[str, set[str]] = defaultdict(set)

    # --- files.list (used by _ls, exists, isdir) ---
    async def list(self, *, q: str, fields: str = "", **kwargs) -> dict:
        # Parse simple name='...' and parents in [...] queries
        results = []
        for path, meta in self._meta.items():
            results.append({**meta, "id": path, "parents": [os.path.dirname(path)]})
        return {"files": results}

    # --- files.get (used by info) ---
    async def get(self, *, fileId: str, fields: str = "", **kwargs) -> dict:
        if fileId not in self._meta:
            raise FileNotFoundError(fileId)
        return {**self._meta[fileId], "id": fileId}

    # --- files.create (used by mkdir, _upload) ---
    async def create(self, *, json: dict | None = None, upload: bytes | None = None, **kwargs) -> dict:
        name = (json or {}).get("name", "unnamed")
        parent = ((json or {}).get("parents") or [""])[0]
        path = f"{parent}/{name}".lstrip("/")
        mime = (json or {}).get("mimeType", "application/octet-stream")

        self._blobs[path] = upload or b""
        self._meta[path] = {
            "name": name,
            "size": len(self._blobs[path]),
            "mimeType": mime,
            "id": path,
        }
        if parent:
            self._children[parent].add(path)
        return self._meta[path]

    # --- media download (used by cat_file / open) ---
    async def get_media(self, *, fileId: str, **kwargs) -> bytes:
        if fileId not in self._blobs:
            raise FileNotFoundError(fileId)
        return self._blobs[fileId]

    # --- files.delete (used by rm) ---
    async def delete(self, *, fileId: str, **kwargs) -> None:
        if fileId not in self._meta:
            raise FileNotFoundError(fileId)
        parent = os.path.dirname(fileId)
        self._children[parent].discard(fileId)
        del self._blobs[fileId]
        del self._meta[fileId]

    # --- files.copy (used by copy) ---
    async def copy(self, *, fileId: str, json: dict | None = None, **kwargs) -> dict:
        src = fileId
        if src not in self._blobs:
            raise FileNotFoundError(src)
        dest_name = (json or {}).get("name", os.path.basename(src))
        dest_parent = ((json or {}).get("parents") or [os.path.dirname(src)])[0]
        dest_path = f"{dest_parent}/{dest_name}".lstrip("/")
        self._blobs[dest_path] = self._blobs[src]
        self._meta[dest_path] = {**self._meta[src], "name": dest_name, "id": dest_path}
        self._children[dest_parent].add(dest_path)
        return self._meta[dest_path]


@pytest.fixture
def gdrive_fs() -> GDriveFileSystem:
    """
    GDriveFileSystem with aiogoogle replaced by an in-memory transport.
    Tests exercise the real GDriveFileSystem code paths; only the HTTP layer is mocked.
    """
    transport = _InMemoryDriveTransport()

    mock_aiogoogle = MagicMock()
    mock_aiogoogle.__aenter__ = AsyncMock(return_value=mock_aiogoogle)
    mock_aiogoogle.__aexit__ = AsyncMock(return_value=False)
    mock_aiogoogle.discover = AsyncMock(return_value=MagicMock(files=transport))

    with patch("files.storage.gdrive.Aiogoogle", return_value=mock_aiogoogle):
        fs = GDriveFileSystem(credentials={})
    return fs


# ---------------------------------------------------------------------------
# Parametrized combined fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=["minio", "gdrive"])
def fs(request, minio_fs, gdrive_fs):
    """Run the same filesystem test against both backends."""
    return {"minio": minio_fs, "gdrive": gdrive_fs}[request.param]


# ---------------------------------------------------------------------------
# Isolated path prefix (per-test)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_prefix() -> str:
    """
    Unique path prefix for each test.
    Prevents cross-test pollution without needing teardown.
    """
    return _unique_prefix()
