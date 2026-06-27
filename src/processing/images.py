import os
import tempfile
from io import BytesIO

from PIL import Image
from fsspec.asyn import AsyncFileSystem
from sqlalchemy.orm import Session

from config import cfg
from filesystem.model import File
from utils.logger import get_logger

THUMBNAIL_SIZE = cfg().files.thumbnail_size

logger = get_logger(__name__)


# TODO: update storage interface
async def process_image(file_record: File, db: Session, storage: AsyncFileSystem):
    """Download an image from MinIO, generate a thumbnail, upload thumbnail."""
    ext = os.path.splitext(file_record.filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Download original
        await storage.download_file_to_path(file_record.id.hex, tmp_path)

        # Generate thumbnail
        with Image.open(tmp_path) as img:
            # Convert to RGB first (faster to thumbnail a 3-channel image)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.thumbnail(THUMBNAIL_SIZE)

            thumb_buffer = BytesIO()
            img.save(thumb_buffer, format="JPEG", quality=85)
            thumb_size = thumb_buffer.tell()
            thumb_buffer.seek(0)

        # Upload thumbnail
        thumb_key = f"{file_record.id.hex}_thumb.jpg"
        await storage.upload_file(
            storage_key=thumb_key,
            data=thumb_buffer,
            size=thumb_size,
            content_type="image/jpeg",
        )

        # Update record
        file_record.thumbnail_storage_key = thumb_key
        db.commit()

        logger.info(
            "Thumbnail generated",
            file_id=str(file_record.id),
            thumb_key=thumb_key,
            thumb_size=thumb_size,
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
