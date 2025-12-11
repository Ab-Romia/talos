from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()
Base.registry.type_annotation_map[dict[str, Any]] = JSONB
