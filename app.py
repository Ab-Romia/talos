from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import auth_router
from backend.auth.utils.session import SessionMiddleware
from backend.chat import chat_router
from config import cfg
from files.router import router as files_router
from files.storage import MinIOStorage
from integrations.drive import drive_router
from model import Base, engine
from notifications.router import router as notifications_router

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
async def lifespan(app: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)

    try:
        storage = _get_minio_storage()
        await storage.ensure_bucket()
        app.state.minio_storage = storage
    except Exception as e:
        print(f"Error initializing MinIO storage: {e}")

    app.state.arq_pool = None

    from broker import broker

    if not broker.is_worker_process:
        await broker.startup()

    yield

    if not broker.is_worker_process:
        await broker.startup()


app = FastAPI(title='Temp', lifespan=lifespan)
app.add_middleware(SessionMiddleware)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
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

app.include_router(notifications_router, prefix="/api")


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
