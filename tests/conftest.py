import os
import uuid
from unittest.mock import AsyncMock

import pytest

# Must be set before any src import
os.environ.setdefault("DATABASE_URL", "postgresql://talos_app:password@localhost:5432/talos_test")

# Import identity/messaging models first so SQLAlchemy can resolve relationships
import model.identity  # noqa: F401
import model.messaging  # noqa: F401

from files.models import FileAttachment, ProcessingStatus
from files.storage import MinIOStorage


@pytest.fixture
def mock_storage():
    """Fully mocked MinIOStorage."""
    storage = AsyncMock(spec=MinIOStorage)
    storage.bucket_name = "talos-uploads"
    storage.upload_file = AsyncMock(return_value="test-etag")
    storage.download_file = AsyncMock(return_value=b"file content")
    storage.download_file_to_path = AsyncMock()
    storage.delete_file = AsyncMock()
    storage.ensure_bucket = AsyncMock()
    storage.generate_presigned_download_url = AsyncMock(
        return_value="http://localhost:9000/presigned"
    )
    storage.generate_presigned_upload_url = AsyncMock(
        return_value="http://localhost:9000/presigned-upload"
    )
    return storage


@pytest.fixture
def sample_file_record():
    """A FileAttachment with sensible defaults for unit tests."""
    file_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    return FileAttachment(
        id=file_id,
        workspace_id=workspace_id,
        chatroom_id=None,
        uploader_id=uuid.uuid4(),
        original_filename="test.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_key=f"workspaces/{workspace_id}/chatrooms/general/{file_id}.pdf",
        checksum="abc123def456",
        processing_status=ProcessingStatus.UPLOADED,
    )
