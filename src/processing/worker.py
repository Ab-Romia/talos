"""ARQ worker configuration and startup."""

from datetime import timedelta

from arq import func

from config import cfg
from utils.datetime import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

JOB_TIMEOUT_SECONDS = 600  # 10 minutes for large documents

# Files that have sat in PROCESSING longer than this (2x the job timeout)
# when the worker starts are assumed to be orphans from a crashed run
# and are marked FAILED so they can be retried.
STUCK_AGE = timedelta(seconds=JOB_TIMEOUT_SECONDS * 2)


def recover_stuck_processing(session_factory) -> int:
    """Mark any file stuck in PROCESSING past STUCK_AGE as FAILED.

    Returns the number of files recovered. Safe to call on every worker
    startup: rows still being actively processed will have a recent
    updated_at (touched via onupdate=func.now() on any status commit),
    so they are not candidates.
    """
    from sqlalchemy import select
    from files.model import FileAttachment, ProcessingStatus

    cutoff = utcnow() - STUCK_AGE
    recovered = 0
    with session_factory() as db:
        stuck = db.scalars(
            select(FileAttachment).where(
                FileAttachment.processing_status == ProcessingStatus.PROCESSING,
                FileAttachment.updated_at < cutoff,
            )
        ).all()
        for file_record in stuck:
            file_record.processing_status = ProcessingStatus.FAILED
            file_record.processing_error = "worker restarted while processing"
            recovered += 1
        if recovered:
            db.commit()
            logger.warning("Recovered stuck files from previous worker", count=recovered)
    return recovered


async def on_startup(ctx):
    """Initialize DB session factory and MinIO storage for the worker."""
    from model import SessionLocal
    from files.storage import MinIOStorage

    app_cfg = cfg()
    minio_cfg = app_cfg.minio

    ctx["db_session_factory"] = SessionLocal
    ctx["minio_storage"] = MinIOStorage(
        internal_endpoint=minio_cfg.internal_endpoint,
        external_endpoint=minio_cfg.external_endpoint,
        access_key=minio_cfg.access_key,
        secret_key=minio_cfg.secret_key,
        secure=minio_cfg.secure,
        bucket_name=minio_cfg.bucket_name,
    )

    recover_stuck_processing(SessionLocal)


async def on_shutdown(ctx):
    """Cleanup worker resources."""
    pass


class WorkerSettings:
    """ARQ worker settings."""

    functions = [func("processing.tasks.process_file", name="process_file", max_tries=3)]
    redis_settings = cfg().redis.to_redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 5
    job_timeout = JOB_TIMEOUT_SECONDS
