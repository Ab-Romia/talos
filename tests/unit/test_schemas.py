import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from files.models import ProcessingStatus
from files.schemas import (
    FileDownloadResponse,
    FileListResponse,
    FileMetadata,
    FileUploadResponse,
)


@pytest.mark.unit
class TestSchemas:
    def test_file_upload_response_from_dict(self):
        data = {
            "file_id": uuid.uuid4(),
            "status": ProcessingStatus.UPLOADED,
            "filename": "test.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        }
        resp = FileUploadResponse(**data)
        assert resp.filename == "test.pdf"
        assert resp.status == ProcessingStatus.UPLOADED

    def test_file_metadata_from_attributes(self):
        obj = MagicMock()
        obj.id = uuid.uuid4()
        obj.workspace_id = uuid.uuid4()
        obj.chatroom_id = None
        obj.uploader_id = uuid.uuid4()
        obj.original_filename = "test.pdf"
        obj.content_type = "application/pdf"
        obj.size_bytes = 1024
        obj.checksum = "abc123"
        obj.processing_status = ProcessingStatus.UPLOADED
        obj.processing_error = None
        obj.thumbnail_storage_key = None
        obj.chunk_count = None
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

        meta = FileMetadata.model_validate(obj, from_attributes=True)
        assert meta.original_filename == "test.pdf"
        assert meta.processing_status == ProcessingStatus.UPLOADED

    def test_file_list_response_with_cursor(self):
        resp = FileListResponse(files=[], next_cursor="2024-01-01T00:00:00|some-uuid")
        assert resp.next_cursor is not None
        assert resp.files == []

    def test_processing_status_enum_values(self):
        values = {s.value for s in ProcessingStatus}
        assert values == {"uploaded", "processing", "indexed", "failed"}
