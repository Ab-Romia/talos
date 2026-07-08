import os
import tempfile
from io import BytesIO

from PIL import Image
from fsspec.asyn import AsyncFileSystem
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from config import cfg, global_rag_config
from filesystem.model import File
from utils.logger import get_logger

THUMBNAIL_SIZE = cfg().files.thumbnail_size

logger = get_logger(__name__)


def _ocr_image(file_path: str) -> str:
    """OCR any text in an image. Returns "" (never raises) when OCR deps are
    missing or the image has no readable text, so image processing still
    succeeds (the thumbnail is generated regardless)."""
    try:
        import pytesseract
    except ImportError:
        logger.warning("OCR dependencies not installed; cannot OCR image")
        return ""
    try:
        with Image.open(file_path) as img:
            return pytesseract.image_to_string(img)
    except Exception:
        logger.exception("Image OCR failed", file_path=file_path)
        return ""


def _raw_fs():
    """Unscoped MinIO client addressing exact object keys.

    Mirrors processing/documents.py: the workspace-scoped MinIOFileSystem
    cannot address real uploaded keys (its split_path inserts a channel
    segment the keys don't contain), so processors work with the exact
    key from File.uri via a plain S3FileSystem.
    """
    from s3fs import S3FileSystem
    _m = cfg().minio
    endpoint = str(_m.internal_endpoint)
    if not endpoint.startswith("http"):
        endpoint = f"{'https' if _m.secure else 'http'}://{endpoint}"
    return S3FileSystem(
        key=_m.access_key,
        secret=_m.secret_key.get_secret_value(),
        endpoint_url=endpoint,
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
            # JPEG only supports RGB/L; convert anything with alpha or a
            # palette (RGBA, LA, PA, P, ...) so the save below can't fail.
            if img.mode not in ("RGB", "L"):
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

        # OCR the image so its text becomes retrievable for RAG. Images with no
        # readable text (photos) index zero chunks — that's fine, the thumbnail
        # above is still their reason for processing.
        base_metadata = {
            "workspace_id": str(file_record.workspace_id),
            "file_id": str(file_record.id),
            "filename": file_record.filename,
        }
        text = _ocr_image(tmp_path).strip()
        chunks: list[Document] = []
        if text:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=global_rag_config.chunk_size,
                chunk_overlap=global_rag_config.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            chunks = splitter.split_documents(
                [Document(page_content=text, metadata={**base_metadata, "page_number": 1})]
            )
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_index"] = i

        # Idempotent re-ingest: clear any chunks from a prior attempt first
        # (Milvus has no unique constraint on (file_id, chunk_index)).
        from rag.vector_store import delete_file_chunks
        delete_file_chunks(str(file_record.id), workspace_id=str(file_record.workspace_id))
        if chunks:
            from rag.ingestion import ingest_file_chunks
            ingest_file_chunks(chunks, str(file_record.workspace_id), str(file_record.id))

        file_record.chunk_count = len(chunks)
        db.commit()

        logger.info(
            "Image indexed",
            file_id=str(file_record.id),
            num_chunks=len(chunks),
            ocr_chars=len(text),
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
