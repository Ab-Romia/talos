from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.auth import auth_router, active_user
from backend.auth.utils.helpers import UserDep
from backend.auth.utils.session import session_middleware
from config import cfg
from files.models import FileAttachment, message_files  # noqa: F401 — register with Base.metadata
from files.router import router as files_router
from files.storage import MinIOStorage
from model import Base, engine

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
    try:
        app.state.arq_pool = await create_pool(get_redis_settings())
    except Exception:
        app.state.arq_pool = None  # Graceful degradation if Redis unavailable

    yield

    # Cleanup
    if app.state.arq_pool:
        await app.state.arq_pool.aclose()


app = FastAPI(title='Temp', lifespan=lifespan)
app.include_router(auth_router, prefix="/api/auth")
app.include_router(files_router, prefix="/api")
app.middleware("http")(session_middleware)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


@app.get('/config')
async def config_page():
    return cfg()


@app.get('/passkey-test', response_class=HTMLResponse)
async def passkey_test_page(request: Request, user: UserDep):
    return templates.TemplateResponse(request, "pages/passkey_test.html", {"username": user.username})


@app.get('/smily')
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smily-protected', dependencies=[Depends(active_user)])
async def smily_protected():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
