from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from uuid import uuid4, UUID

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"  # "Alice joined the channel"


class WSMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel_id: UUID  # act as channel id
    sender_id: UUID
    role: MessageRole = MessageRole.USER  # default is USER as its majority ,only override this if AI response/system notification.
    text: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WSIncoming(BaseModel):  # what client sends to server when creating a message
    event_type: Literal["new_message"] = "new_message"
    channel_id: UUID
    text: str


class ReadReceiptRequest(BaseModel):
        """Client → Server: request to mark a specific message as read."""
        event_type: Literal["read_receipt"] = "read_receipt"
        channel_id: UUID
        message_id: UUID


class ReadReceiptEvent(BaseModel):
        """Server → Sender: notification that a recipient has read a message."""
        event_type: Literal["read_receipt"] = "read_receipt"
        channel_id: UUID
        message_id: UUID
        reader_id: UUID
        read_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



# Message is what the server creates after validation and persistence it has an id, created_at, sender_id etc.
# WSIncoming is the raw thing the client sends, which only has text.
# Keeping them separate means the client can't fake its own id or sender_id by sending them in the payload the server always generates those itself.

class MessageEvent(BaseModel):  # what server push to client
    event_type: Literal["new_message"] = "new_message"
    message: WSMessage


# event field tells the frontend what type of event this is, so one WebSocket connection can carry many different event types
# and the frontend can switch on event to handle each one differently.


class PresenceEvent(BaseModel):
    """Pushed when a user joins or leaves a channel."""
    event_type: Literal["user_joined", "user_left"]  # "user_joined" / "user_left"
    user_id: UUID
    online_users: list[UUID]  # full current list of who's online so the frontend never has to track presence state itself.


Event = Annotated[MessageEvent | PresenceEvent | ReadReceiptEvent, Field(discriminator="event_type")]
