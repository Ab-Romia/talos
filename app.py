from contextlib import asynccontextmanager

import redis.asyncio
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text, exc
from sqlalchemy.orm import Session

from auth.router import router as auth_router
from auth.utils.session import SessionMiddleware
from chat.realtime import sio
from config import cfg
from filesystem.storage.gdrive.router import router as gdrive_proxy_router
from notifications.router import notifications as notifications_router
from utils.exceptions import dbapi_error_handler
from workspace.router import workspace as workspace_router, channel as channel_router
from workspace.discovery import router as workspaces_list_router
from filesystem.documents import router as documents_router
from ai import router as ai_router

templates = Jinja2Templates(directory="frontend/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from chat.storage import bind_chat_storage, DatabaseStorageBackend
    from broker import broker
    from database import Base, engine

    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)

    bind_chat_storage(DatabaseStorageBackend())

    app.state.redis = redis.asyncio.from_url(cfg().redis.url, decode_responses=True)

    if not broker.is_worker_process:
        await broker.startup()
    app.state.arq_pool = None

    yield

    # Cleanup
    if not broker.is_worker_process:
        await broker.startup()
    await app.state.redis.aclose()


app = FastAPI(title='Talos', lifespan=lifespan)

app.mount('/socket.io', socketio.ASGIApp(sio), name='socketio')
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(notifications_router, prefix="/api")
app.include_router(workspaces_list_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(channel_router, prefix="/api")
app.include_router(gdrive_proxy_router, prefix="/api/storage", tags=["gdrive-proxy"])

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
