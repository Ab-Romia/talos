"""Task dispatcher for file processing."""

import uuid

from sqlalchemy import update as sa_update

from config import cfg
from files.model import FileAttachment, ProcessingStatus
from utils.logger import get_logger

DOCUMENT_MIME_TYPES = cfg().files.document_mime_types
IMAGE_MIME_TYPES = cfg().files.image_mime_types

logger = get_logger(__name__)


async def process_file(ctx: dict, file_id: str):
    """Main task dispatcher. Routes to document or image processor by MIME type."""
    db_factory = ctx["db_session_factory"]
    storage = ctx["minio_storage"]

    fid = uuid.UUID(file_id)
    with db_factory() as db:
        # Atomically claim the file: flip status to PROCESSING only when the
        # current state is workable (UPLOADED or FAILED). rowcount == 0 means
        # another worker already owns it, it is already INDEXED, or the row is
        # gone — all safe to skip.
        result = db.execute(
            sa_update(FileAttachment)
            .where(
                FileAttachment.id == fid,
                FileAttachment.processing_status.in_([
                    ProcessingStatus.UPLOADED,
                    ProcessingStatus.FAILED,
                ])
            )
            .values(processing_status=ProcessingStatus.PROCESSING)
        )
        db.commit()

        if result.rowcount == 0:
            file_record = db.get(FileAttachment, fid)
            if file_record is None:
                logger.warning("File not found for processing", file_id=file_id)
            else:
                logger.info(
                    "File not in processable state, skipping",
                    file_id=file_id,
                    status=file_record.processing_status.value,
                )
            return

        file_record = db.get(FileAttachment, fid)
        if file_record is None:
            logger.warning("File row vanished after claim", file_id=file_id)
            return

        try:
            if file_record.content_type in DOCUMENT_MIME_TYPES:
                from processing.documents import process_document
                await process_document(file_record, db, storage)

            elif file_record.content_type in IMAGE_MIME_TYPES:
                from processing.images import process_image
                await process_image(file_record, db, storage)

            else:
                raise ValueError(
                    f"No processor registered for MIME type {file_record.content_type}"
                )

            file_record.processing_status = ProcessingStatus.INDEXED
            db.commit()
            logger.info("File processing complete", file_id=file_id)

        except Exception as e:
            logger.exception("File processing failed", file_id=file_id)
            db.rollback()
            file_record = db.get(FileAttachment, fid)
            if file_record is None:
                logger.error(
                    "File row disappeared during processing",
                    file_id=file_id,
                    underlying_error=str(e)[:500],
                )
                return
            file_record.processing_status = ProcessingStatus.FAILED
            file_record.processing_error = str(e)[:2048]
            db.commit()
            raise
