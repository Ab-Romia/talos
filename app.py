import os

# Before other imports: quieter HF model downloads/loads in server logs and console.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

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
from backend.ai_settings import ai_settings_router
from backend.authorization import authorization_router
from backend.auth.utils.helpers import UserDep
from backend.auth.utils.session import session_middleware
from config import cfg
from files.router import router as files_router
from files.storage import MinIOStorage
from integrations.drive import drive_router
from model import Base, engine
from notifications.router import router as notifications_router

templates = Jinja2Templates(directory="frontend/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from arq import create_pool
    from utils.logger import get_logger

    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.execute(
            text(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_extra JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        # Older DBs created before JSON ``data`` columns — ORM expects these for OAuth, profile, etc.
        s.execute(
            text(
                "ALTER TABLE identity_providers ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        s.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        s.execute(
            text(
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent TEXT"
            )
        )
        # identity_providers.issuer: old DBs used a native PG enum whose labels did not match
        # SQLAlchemy's bind values (e.g. 'oauth' vs '/api/auth/oauth'). Move to varchar + path strings.
        s.execute(
            text(
                """
                DO $issuer_migrate$
                BEGIN
                  IF EXISTS (
                    SELECT 1
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_type t ON t.oid = a.atttypid
                    WHERE n.nspname = 'public'
                      AND c.relname = 'identity_providers'
                      AND a.attname = 'issuer'
                      AND NOT a.attisdropped
                      AND t.typtype = 'e'
                  ) THEN
                    ALTER TABLE identity_providers
                      ALTER COLUMN issuer TYPE varchar(128)
                      USING (
                        CASE (issuer::text)
                          WHEN 'password' THEN '/api/auth/password'
                          WHEN 'totp' THEN '/api/auth/totp'
                          WHEN 'oauth' THEN '/api/auth/oauth'
                          WHEN 'passkey' THEN '/api/auth/passkey'
                          ELSE (issuer::text)
                        END
                      );
                  END IF;
                END
                $issuer_migrate$;
                """
            )
        )
        s.commit()

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

    # Initialize ARQ Redis pool for background task enqueueing

    try:
        app.state.arq_pool = await create_pool(cfg().redis.to_redis_settings())
    except Exception:
        # Keep the app running so non-upload endpoints stay usable
        # uploads will now fail with 503
        get_logger(__name__).error("Failed to initialize ARQ Redis pool", exc_info=True)
        app.state.arq_pool = None

    from broker import broker

    if not broker.is_worker_process:
        await broker.startup()

    from model import SessionLocal
    from processing.worker import (
        reconcile_indexed_with_zero_document_chunks,
        recover_stuck_processing,
    )
    try:
        n = recover_stuck_processing(SessionLocal)
        if n:
            get_logger(__name__).info("Recovered stuck file rows (orphan processing)", count=n)
    except Exception:
        get_logger(__name__).warning("recover_stuck_processing skipped on startup", exc_info=True)
    try:
        r = reconcile_indexed_with_zero_document_chunks(SessionLocal)
        if r:
            get_logger(__name__).info("Reconciled indexed files with no chunks (legacy rows)", count=r)
    except Exception:
        get_logger(__name__).warning("chunk reconciliation skipped on startup", exc_info=True)

    yield

    if not broker.is_worker_process:
        await broker.startup()


app = FastAPI(title='Talos', lifespan=lifespan)
app.add_middleware(SessionMiddleware)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(drive_router, prefix="/api")
app.include_router(ai_settings_router, prefix="/api")
app.include_router(authorization_router, prefix="/api")
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
