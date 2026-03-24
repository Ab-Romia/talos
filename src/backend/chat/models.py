from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    id:              str         = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    role:            MessageRole
    text:            str
    created_at:      datetime    = Field(default_factory=lambda: datetime.now(timezone.utc))