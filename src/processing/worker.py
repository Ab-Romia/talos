"""ARQ worker configuration and startup."""

from arq import func
from arq.connections import RedisSettings

from config import cfg


def get_redis_settings() -> RedisSettings:
    """Parse redis URL into ARQ RedisSettings."""
    app_cfg = cfg()
    redis_url = app_cfg.redis.url if app_cfg.redis else "redis://localhost:6379"

    # Parse redis://host:port/db format
    from urllib.parse import urlparse
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
    )


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


async def on_shutdown(ctx):
    """Cleanup worker resources."""
    pass


class WorkerSettings:
    """ARQ worker settings."""

    from processing.tasks import process_file

    functions = [func(process_file, max_tries=3)]
    redis_settings = get_redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 5
    job_timeout = 600  # 10 minutes for large documents
