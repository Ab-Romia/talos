from contextlib import asynccontextmanager

from backend.auth.utils.session import SessionMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from files.router import router as files_router
from files.storage import MinIOStorage
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import auth_router
from backend.chat import chat_router
from config import cfg
from integrations.drive import drive_router
from model import Base, engine
from modules.app.preferences import router as preferences_router
from modules.app.websocket import router as websocket_router

templates = Jinja2Templates(directory="frontend/templates")



def _get_minio_storage() -> MinIOStorage:
    minio_cfg = cfg().minio
    return MinIOStorage(
        internal_endpoint=minio_cfg.internal_endpoint,
        external_endpoint=minio_cfg.external_endpoint,
        access_key=minio_cfg.access_key,
        secret_key=minio_cfg.secret_key,
        secure=minio_cfg.secure,
        bucket_name=minio_cfg.bucket_name,
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
    from utils.logger import get_logger
    try:
        app.state.arq_pool = await create_pool(get_redis_settings())
    except Exception as e:
        # Keep the app running so non-upload endpoints stay usable
        # uploads will now fail with 503
        get_logger(__name__).error("Failed to initialize ARQ Redis pool", exc_info=True)
        app.state.arq_pool = None

    yield

    # Cleanup
    if app.state.arq_pool:
        await app.state.arq_pool.aclose()


app = FastAPI(title='Temp', lifespan=lifespan)
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.add_middleware(SessionMiddleware)
app.include_router(auth_router, prefix="/api/auth")
app.include_router(chat_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(drive_router, prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware)

app.include_router(auth_router)
app.include_router(websocket_router)
app.include_router(preferences_router)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
