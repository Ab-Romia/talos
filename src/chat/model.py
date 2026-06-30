import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import ForeignKey, Uuid, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from database import Base

if TYPE_CHECKING:
    from filesystem.model import File
    from workspace.model import Channel


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"  # "Alice joined the channel"


class MessageSchema(BaseModel):
    id: UUID = Field(default_factory=uuid.uuid7)
    channel_id: UUID
    sender_id: UUID
    role: MessageRole = MessageRole.USER  # default is USER as its majority, only override this if AI response/system notification.
    content: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class ReadReceiptRequest(BaseModel):
    """Client → Server: request to mark a specific message as read."""
    event_type: Literal["read_receipt"] = "read_receipt"
    channel_id: UUID
    message_id: UUID


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column()
    role: Mapped[MessageRole] = mapped_column(default=MessageRole.USER)

    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    channel: Mapped[Channel] = relationship("Channel", back_populates="messages")
    files: Mapped[list[File]] = relationship("File", secondary="message_files", back_populates="message")
