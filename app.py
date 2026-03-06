from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import auth_router
from backend.auth.dependencies import active_user, SessionCookieToHeaderMiddleware
from config import config
from files.models import FileAttachment, message_files  # noqa: F401 — register with Base.metadata
from files.router import router as files_router
from files.storage import MinIOStorage
from model.base import engine, Base

__all__ = []

load_dotenv()


def _get_minio_storage() -> MinIOStorage:
    cfg = config().minio
    return MinIOStorage(
        internal_endpoint=cfg.internal_endpoint,
        external_endpoint=cfg.external_endpoint,
        access_key=cfg.access_key,
        secret_key=cfg.secret_key,
        secure=cfg.secure,
        bucket_name=cfg.bucket_name,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)

    storage = _get_minio_storage()
    await storage.ensure_bucket()
    app.state.minio_storage = storage

    # Initialize ARQ Redis pool for background task enqueueing
    from arq import create_pool
    from processing.worker import get_redis_settings
    try:
        app.state.arq_pool = await create_pool(get_redis_settings())
    except Exception:
        app.state.arq_pool = None  # Graceful degradation if Redis unavailable

    yield

    # Cleanup
    if app.state.arq_pool:
        await app.state.arq_pool.aclose()


app = FastAPI(title='Temp', lifespan=lifespan)
app.include_router(auth_router, prefix="/auth")
app.include_router(files_router, prefix="/api")
app.add_middleware(SessionCookieToHeaderMiddleware)


@app.get('/')
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


@app.get('/config')
async def config_page():
    return config()


@app.get('/smily')
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smily-protected', dependencies=[Depends(active_user)])
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app,
                host=config().app_host,
                port=config().app_port,
                )
