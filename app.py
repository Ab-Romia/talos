from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text, exc
from sqlalchemy.orm import Session

from backend.auth import auth_router
from backend.auth.utils.session import SessionMiddleware
from backend.chat import chat_router
from backend.router import workspace as workspace_router, channel as channel_router
from config import cfg
from files.router import router as files_router
from files.storage import MinIOStorage
from integrations.drive import drive_router
from notifications.router import notifications as notifications_router
from utils.exceptions import dbapi_error_handler

templates = Jinja2Templates(directory="frontend/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from utils.logger import get_logger
    from model import Base, engine

    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)

    storage = MinIOStorage(
        internal_endpoint=cfg().minio.internal_endpoint,
        external_endpoint=cfg().minio.external_endpoint,
        access_key=cfg().minio.access_key,
        secret_key=cfg().minio.secret_key,
        secure=cfg().minio.secure,
        bucket_name=cfg().minio.bucket_name,
    )
    try:
        await storage.ensure_bucket()
        app.state.minio_storage = storage
    except Exception:
        get_logger(__name__).error("Failed to ensure MinIO bucket", exc_info=True)

    app.state.arq_pool = None

    from broker import broker

    if not broker.is_worker_process:
        await broker.startup()

    yield

    if not broker.is_worker_process:
        await broker.startup()


app = FastAPI(title='Talos', lifespan=lifespan)
app.include_router(auth_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(drive_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(channel_router, prefix="/api")

# TODO: replace with reverse proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware)
app.exception_handler(exc.DBAPIError)(dbapi_error_handler)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
