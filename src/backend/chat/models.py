from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4, UUID

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"  # "Alice joined the channel"


class WSMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel_id: UUID
    sender_id: UUID
    role: MessageRole = MessageRole.USER  # default is USER as its majority, only override this if AI response/system notification.
    text: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReadReceiptRequest(BaseModel):
    """Client → Server: request to mark a specific message as read."""
    event_type: Literal["read_receipt"] = "read_receipt"
    channel_id: UUID
    message_id: UUID
