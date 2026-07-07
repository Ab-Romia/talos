"""Task dispatcher for file processing."""

import uuid

from sqlalchemy import update as sa_update

from broker import broker
from config import cfg
from database import SessionLocal
from filesystem.model import File, FileStatus
from filesystem.storage.minio import MinIOFileSystem
from utils.logger import get_logger

logger = get_logger(__name__)


# TODO: retry, backoff, timeout..
@broker.task()
async def process_file(file_id: uuid.UUID):
    """Main task dispatcher. Routes to document or image processor by MIME type."""
    # The body is written sync-style (plain execute/commit, and the processors
    # take a sync Session) — use the sync factory, not AsyncSessionLocal.
    with SessionLocal() as db:
        """
        Atomically claim the file: flip status to PROCESSING only when the
        current state is workable (UPLOADED or FAILED). rowcount == 0 means
        another worker already owns it, it is already INDEXED, or the row is
        gone — all safe to skip.
        """
        # TODO: consider letting taskiq handle locking.
        result = db.execute(
            sa_update(File)
            .where(
                File.id == file_id,
                File.processing_status.in_([
                    FileStatus.UPLOADED,
                    FileStatus.PROCESSING_FAILED,
                ])
            )
            .values(processing_status=FileStatus.PROCESSING)
        )
        db.commit()

        if result.rowcount == 0:
            file_record = db.get(File, file_id)
            if file_record is None:
                logger.warning("File not found for processing", file_id=file_id)
            else:
                logger.info(
                    "File not in processable state, skipping",
                    file_id=file_id,
                    status=file_record.processing_status.value,
                )
            return

        file_record = db.get(File, file_id)
        if file_record is None:
            logger.warning("File row vanished after claim", file_id=file_id)
            return

        # Workspace-scoped storage: on this branch File.uri is a RELATIVE
        # virtual path ("minio://<parent>/<name>"); MinIOFileSystem.split_path
        # re-prepends {bucket}/{workspace}/{channel} — so the filesystem must
        # be constructed per file with the file's own scope.
        storage = MinIOFileSystem(
            cfg().minio,
            workspace_id=file_record.workspace_id,
            channel_id=file_record.channel_id,
        )

        try:
            if file_record.content_type in cfg().files.document_mime_types:
                from processing.documents import process_document
                await process_document(file_record, db, storage)

            elif file_record.content_type in cfg().files.image_mime_types:
                from processing.images import process_image
                await process_image(file_record, db, storage)

            else:
                raise ValueError(
                    f"No processor registered for MIME type {file_record.content_type}"
                )

            file_record.processing_status = FileStatus.INDEXED
            file_record.processing_error = None  # clear any stale error from a prior failed attempt
            db.commit()
            logger.info("File processing complete", file_id=file_id)

        except Exception as e:
            logger.exception("File processing failed", file_id=file_id)
            db.rollback()
            file_record = db.get(File, file_id)
            if file_record is None:
                logger.error(
                    "File row disappeared during processing",
                    file_id=file_id,
                    underlying_error=str(e)[:500],
                )
                return
            file_record.processing_status = FileStatus.PROCESSING_FAILED
            file_record.processing_error = str(e)[:2048]
            db.commit()
            raise
