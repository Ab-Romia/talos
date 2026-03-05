from typing import Any, Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, Session, sessionmaker

from config import config

Base = declarative_base()
Base.registry.type_annotation_map[dict[str, Any]] = JSONB

engine = create_engine(
    config().database_url,
    echo=True,
    connect_args={},
    future=True,
)

# Use a sessionmaker factory for SQLAlchemy 2.0 style sessions
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    # Provide a transaction-scoped session for FastAPI dependencies
    with SessionLocal() as session:
        yield session


DatabaseDep = Annotated[Session, Depends(get_db)]
