"""Task dispatcher for file processing."""

import uuid

from files.constants import DOCUMENT_MIME_TYPES, IMAGE_MIME_TYPES
from files.models import FileAttachment, ProcessingStatus
from utils.logger import get_logger

logger = get_logger(__name__)


async def process_file(ctx: dict, file_id: str):
    """Main task dispatcher. Routes to document or image processor by MIME type."""
    db_factory = ctx["db_session_factory"]
    storage = ctx["minio_storage"]

    with db_factory() as db:
        file_record = db.get(FileAttachment, uuid.UUID(file_id))
        if file_record is None:
            logger.warning("File not found for processing", file_id=file_id)
            return

        # Idempotent: skip if already processed
        if file_record.processing_status == ProcessingStatus.INDEXED:
            logger.info("File already indexed, skipping", file_id=file_id)
            return

        # Mark as processing
        file_record.processing_status = ProcessingStatus.PROCESSING
        db.commit()

        try:
            if file_record.content_type in DOCUMENT_MIME_TYPES:
                from processing.documents import process_document
                await process_document(file_record, db, storage)

            elif file_record.content_type in IMAGE_MIME_TYPES:
                from processing.images import process_image
                await process_image(file_record, db, storage)

            else:
                logger.warning(
                    "No processor for MIME type",
                    file_id=file_id,
                    mime=file_record.content_type,
                )

            file_record.processing_status = ProcessingStatus.INDEXED
            db.commit()
            logger.info("File processing complete", file_id=file_id)

        except Exception as e:
            logger.exception("File processing failed", file_id=file_id)
            # Re-fetch in case session is dirty
            db.rollback()
            file_record = db.get(FileAttachment, uuid.UUID(file_id))
            if file_record:
                file_record.processing_status = ProcessingStatus.FAILED
                file_record.processing_error = str(e)[:2048]
                db.commit()
            raise  # Let ARQ handle retry
