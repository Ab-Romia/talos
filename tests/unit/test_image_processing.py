import os
import tempfile
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from files.models import FileAttachment, ProcessingStatus


def _create_test_image(width, height, mode="RGB", fmt="PNG"):
    """Create a real image file for testing."""
    img = Image.new(mode, (width, height), color="red")
    buf = BytesIO()
    if mode in ("RGBA", "P") and fmt == "JPEG":
        img = img.convert("RGB")
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_record(filename="photo.png", content_type="image/png"):
    record = MagicMock(spec=FileAttachment)
    record.id = uuid.uuid4()
    record.workspace_id = uuid.uuid4()
    record.original_filename = filename
    record.content_type = content_type
    record.storage_key = f"workspaces/ws/chatrooms/general/{uuid.uuid4()}.png"
    record.processing_status = ProcessingStatus.PROCESSING
    record.thumbnail_storage_key = None
    return record


@pytest.mark.unit
class TestProcessImage:
    @pytest.mark.asyncio
    async def test_generates_thumbnail_within_bounds(self, mock_storage):
        from processing.images import process_image

        img_data = _create_test_image(1000, 800)
        record = _make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)

        # Verify upload was called (thumbnail created)
        mock_storage.upload_file.assert_awaited_once()
        call_args = mock_storage.upload_file.call_args
        thumb_data = call_args.kwargs.get("data") or call_args[1].get("data") or call_args[0][1]

        # Read the uploaded thumbnail and verify dimensions
        thumb_img = Image.open(thumb_data)
        assert thumb_img.width <= 300
        assert thumb_img.height <= 300

    @pytest.mark.asyncio
    async def test_converts_rgba_to_rgb(self, mock_storage):
        from processing.images import process_image

        img_data = _create_test_image(100, 100, mode="RGBA", fmt="PNG")
        record = _make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)
        # Should not raise (JPEG can't handle RGBA, so conversion must happen)
        mock_storage.upload_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_converts_palette_to_rgb(self, mock_storage):
        from processing.images import process_image

        img = Image.new("P", (100, 100))
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_data = buf.getvalue()

        record = _make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)
        mock_storage.upload_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uploads_thumbnail_with_thumb_key(self, mock_storage):
        from processing.images import process_image

        img_data = _create_test_image(200, 200)
        record = _make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)

        call_kwargs = mock_storage.upload_file.call_args
        storage_key = call_kwargs.kwargs.get("storage_key") or call_kwargs[1].get("storage_key") or call_kwargs[0][0]
        assert storage_key.endswith("_thumb.jpg")

    @pytest.mark.asyncio
    async def test_updates_thumbnail_storage_key(self, mock_storage):
        from processing.images import process_image

        img_data = _create_test_image(200, 200)
        record = _make_record()
        db = MagicMock()

        async def fake_download(key, path):
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)
        assert record.thumbnail_storage_key is not None
        assert record.thumbnail_storage_key.endswith("_thumb.jpg")

    @pytest.mark.asyncio
    async def test_cleans_up_temp_file(self, mock_storage):
        from processing.images import process_image

        img_data = _create_test_image(200, 200)
        record = _make_record()
        db = MagicMock()
        created_paths = []

        async def fake_download(key, path):
            created_paths.append(path)
            with open(path, "wb") as f:
                f.write(img_data)

        mock_storage.download_file_to_path = AsyncMock(side_effect=fake_download)

        await process_image(record, db, mock_storage)
        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0])
