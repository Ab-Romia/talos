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


def _raw_fs():
    """Unscoped MinIO client addressing exact object keys.

    Mirrors processing/documents.py: the workspace-scoped MinIOFileSystem
    cannot address real uploaded keys (its split_path inserts a channel
    segment the keys don't contain), so processors work with the exact
    key from File.uri via a plain S3FileSystem.
    """
    from s3fs import S3FileSystem
    _m = cfg().minio
    return S3FileSystem(
        key=_m.access_key,
        secret=_m.secret_key.get_secret_value(),
        endpoint_url=_m.internal_endpoint,
        use_ssl=_m.secure,
        asynchronous=True,
        skip_instance_cache=True,
    )


# TODO: update storage interface
async def process_image(file_record: File, db: Session, storage: AsyncFileSystem):
    """Download an image from MinIO, generate a thumbnail, upload it next to
    the original (<key>_thumb.jpg).

    NOTE: `storage` is unused for the same reason as in documents.py — kept
    for signature parity until the storage interface TODO is resolved.
    """
    ext = os.path.splitext(file_record.filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        object_key = str(file_record.uri).removeprefix("minio://")
        fs = _raw_fs()
        await fs._get_file(object_key, tmp_path)

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

        thumb_key = f"{object_key}_thumb.jpg"
        await fs._pipe_file(thumb_key, thumb_buffer.getvalue())

        logger.info(
            "Thumbnail generated",
            file_id=str(file_record.id),
            thumb_key=thumb_key,
            thumb_size=thumb_size,
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
