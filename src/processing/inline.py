import asyncio
import uuid

from utils.logger import get_logger

logger = get_logger(__name__)


def schedule_process_file(app, file_id: uuid.UUID) -> None:
    asyncio.get_running_loop().create_task(_run_process_file(app, file_id))


async def _run_process_file(app, file_id: uuid.UUID) -> None:
    from model import SessionLocal
    from processing.tasks import process_file

    ctx = {
        "db_session_factory": SessionLocal,
        "minio_storage": app.state.minio_storage,
    }
    try:
        await process_file(ctx, str(file_id))
    except Exception:
        logger.exception("Inline file processing failed", file_id=str(file_id))
