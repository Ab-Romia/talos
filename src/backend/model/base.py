import os
from typing import Any, Annotated

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, Session

load_dotenv()

Base = declarative_base()
Base.registry.type_annotation_map[dict[str, Any]] = JSONB

engine = create_engine(
    os.environ.get('DATABASE_URL'),
    echo=True,
    connect_args={}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DepDB = Annotated[Session, Depends(get_db)]
