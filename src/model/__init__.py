from typing import Any, Annotated, AsyncGenerator, Generator

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Session, sessionmaker

from config import cfg

Base = declarative_base()
Base.registry.type_annotation_map[dict[str, Any]] = JSONB

engine = create_engine(
    cfg().database_url.get_secret_value(),
    connect_args={},
    future=True,
)

async_engine = create_async_engine(
    cfg().database_url.get_secret_value(),
    echo=False,
    future=True,
)


def _get_db() -> Generator[Session]:
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


async def _get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DatabaseDep = Annotated[Session, Depends(_get_db)]
AsyncDatabaseDep = Annotated[AsyncSession, Depends(_get_async_db)]
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
