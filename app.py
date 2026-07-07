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
    import asyncio
    from chat.storage import bind_chat_storage, DatabaseStorageBackend
    from chat.sync import bind_loop
    from broker import broker
    from database import Base, engine

    bind_loop(asyncio.get_running_loop())

    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto";'))
        session.commit()

    Base.metadata.create_all(engine)

    # create_all never alters existing tables; patch columns added after a
    # table was first created so long-lived databases stay in sync.
    with Session(engine) as session:
        session.execute(text(
            "ALTER TABLE channels ADD COLUMN IF NOT EXISTS is_group boolean NOT NULL DEFAULT false"
        ))
        session.execute(text(
            "ALTER TABLE files ADD COLUMN IF NOT EXISTS is_private boolean NOT NULL DEFAULT false"
        ))
        session.execute(text(
            "ALTER TABLE ai_chat_messages ADD COLUMN IF NOT EXISTS conversation_id uuid"
        ))
        # Fold legacy single-thread history into one conversation per (workspace,
        # user) so pre-existing chats survive the move to multiple conversations.
        session.execute(text(
            "UPDATE ai_chat_messages m SET conversation_id = g.cid "
            "FROM (SELECT workspace_id, user_id, gen_random_uuid() AS cid "
            "FROM ai_chat_messages WHERE conversation_id IS NULL "
            "GROUP BY workspace_id, user_id) g "
            "WHERE m.workspace_id = g.workspace_id AND m.user_id = g.user_id "
            "AND m.conversation_id IS NULL"
        ))
        session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_messages_conversation_id "
            "ON ai_chat_messages (conversation_id)"
        ))
        session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_ws_user_conv_created "
            "ON ai_chat_messages (workspace_id, user_id, conversation_id, created_at)"
        ))
        # Give every workspace a description so the settings screen isn't blank.
        session.execute(text(
            "UPDATE workspaces SET description = "
            "name || ' — a shared space for your team''s channels, conversations and documents.' "
            "WHERE description IS NULL OR description = ''"
        ))
        session.commit()

    from workspace.discovery import ensure_permissions_registered
    ensure_permissions_registered()

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

from chat.attachments import media as media_router
app.include_router(media_router, prefix="/api")

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
