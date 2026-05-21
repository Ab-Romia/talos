from typing import Any, Annotated, Generator

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, Session, sessionmaker

from config import cfg

Base = declarative_base()
Base.registry.type_annotation_map[dict[str, Any]] = JSONB

engine = create_engine(
    cfg().database_url,
    connect_args={},
    future=True,
)


def get_db() -> Generator[Session]:
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


DatabaseDep = Annotated[Session, Depends(get_db)]
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
