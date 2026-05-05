import uuid
from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer
from sqlalchemy import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class PydanticModelType(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def __init__(self, pydantic_model):
        super().__init__()
        self.pydantic_model = pydantic_model

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.pydantic_model):
            return value.model_dump()
        return value  # already a dict

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.pydantic_model.model_validate(value)


UUID = Annotated[uuid.UUID, PlainSerializer(lambda v: v.hex if v else None)]
DATETIME = Annotated[datetime, PlainSerializer(lambda v: v.timestamp())]
