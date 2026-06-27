"""Unit tests for the Drive import service (filename derivation, MIME guards)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from integrations.drive.service import DriveImportService

from config import cfg
from files.errors import FileTooLarge, UnsupportedFileType


@pytest.mark.unit
class TestDeriveFilename:
    def test_keeps_existing_extension(self):
        assert DriveImportService._derive_filename("report.pdf", ".pdf") == "report.pdf"

    def test_appends_when_missing(self):
        assert DriveImportService._derive_filename("My Doc", ".docx") == "My Doc.docx"

    def test_no_hint_passthrough(self):
        assert DriveImportService._derive_filename("anything", "") == "anything"

    def test_keeps_existing_extension_even_when_different(self):
        # We trust the filename's extension over the export hint
        assert DriveImportService._derive_filename("report.txt", ".docx") == "report.txt"


@pytest.mark.unit
class TestImportFileGuards:
    @pytest.mark.asyncio
    async def test_rejects_non_exportable_google_native_type(self, mock_storage):
        svc = DriveImportService(MagicMock(), mock_storage, uuid.uuid4())
        svc.client = MagicMock()
        svc.client.get_metadata = AsyncMock(return_value={
            "id": "x",
            "name": "drawing",
            "mimeType": "application/vnd.google-apps.drawing",
            "size": "100",
        })
        with pytest.raises(UnsupportedFileType):
            await svc.import_file("x", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_rejects_oversize_per_drive_metadata(self, mock_storage):
        svc = DriveImportService(MagicMock(), mock_storage, uuid.uuid4())
        svc.client = MagicMock()
        svc.client.get_metadata = AsyncMock(return_value={
            "id": "x",
            "name": "huge.pdf",
            "mimeType": "application/pdf",
            "size": str(cfg().files.max_size + 1),
        })
        with pytest.raises(FileTooLarge):
            await svc.import_file("x", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_rejects_unsupported_after_download(self, mock_storage):
        """Drive metadata says PDF but download yields something else."""
        svc = DriveImportService(MagicMock(), mock_storage, uuid.uuid4())
        svc.client = MagicMock()
        svc.client.get_metadata = AsyncMock(return_value={
            "id": "x",
            "name": "fake.pdf",
            "mimeType": "application/pdf",
        })
        svc.client.download = AsyncMock(return_value=("application/zip", "", b"PK\x03\x04"))

        with pytest.raises(UnsupportedFileType):
            await svc.import_file("x", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_happy_path_routes_through_file_service(self, mock_storage):
        ws_id = uuid.uuid4()
        user_id = uuid.uuid4()
        svc = DriveImportService(MagicMock(), mock_storage, user_id)
        svc.client = MagicMock()
        svc.client.get_metadata = AsyncMock(return_value={
            "id": "drive-1",
            "name": "doc",
            "mimeType": "application/vnd.google-apps.document",
        })
        svc.client.download = AsyncMock(
            return_value=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".docx",
                b"PK\x03\x04docx-content",
            )
        )

        captured = {}

        async def _fake_upload_workspace(self_, upload_file, workspace_id, uploader_id):
            captured["filename"] = upload_file.filename
            captured["content_type"] = upload_file.content_type
            captured["workspace_id"] = workspace_id
            captured["uploader_id"] = uploader_id
            return MagicMock(id=uuid.uuid4(), original_filename=upload_file.filename)

        with patch("integrations.drive.service.FileService.upload", new=_fake_upload_workspace):
            await svc.import_file("drive-1", ws_id)

        assert captured["filename"] == "doc.docx"
        assert captured["content_type"] == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert captured["workspace_id"] == ws_id
        assert captured["uploader_id"] == user_id

    @pytest.mark.asyncio
    async def test_happy_path_uses_channel_upload_when_channel_provided(self, mock_storage):
        ws_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        user_id = uuid.uuid4()
        svc = DriveImportService(MagicMock(), mock_storage, user_id)
        svc.client = MagicMock()
        svc.client.get_metadata = AsyncMock(return_value={
            "id": "drive-1",
            "name": "doc",
            "mimeType": "application/vnd.google-apps.document",
        })
        svc.client.download = AsyncMock(
            return_value=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".docx",
                b"PK\x03\x04docx-content",
            )
        )

        captured = {}

        async def _fake_upload_channel(self_, upload_file, channel_id_arg, uploader_id):
            captured["filename"] = upload_file.filename
            captured["content_type"] = upload_file.content_type
            captured["channel_id"] = channel_id_arg
            captured["uploader_id"] = uploader_id
            return MagicMock(id=uuid.uuid4(), original_filename=upload_file.filename)

        with patch("integrations.drive.service.FileService.upload_workspace") as mock_workspace, \
                patch("integrations.drive.service.FileService.upload_channel", new=_fake_upload_channel):
            await svc.import_file("drive-1", ws_id, channel_id)

        mock_workspace.assert_not_called()
        assert captured["channel_id"] == channel_id
        assert captured["uploader_id"] == user_id
