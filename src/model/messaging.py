import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, UUID, ForeignKey, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from files.models import FileAttachment
from model import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    owner_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column()

    channels: Mapped[list[Channel]] = relationship("Channel", back_populates="workspace")
    files: Mapped[list[FileAttachment]] = relationship("FileAttachment", back_populates="workspace")


class Channel(Base):
    __tablename__ = "channels"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(index=True)
    workspace_id = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    messages: Mapped[list[Message]] = relationship("Message", back_populates="channel")
    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="channels")
    files: Mapped[list[FileAttachment]] = relationship("FileAttachment", back_populates="channel")


class Message(Base):
    __tablename__ = "messages"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = mapped_column(ForeignKey(Workspace.id, ondelete="CASCADE"))
    channel_id = mapped_column(ForeignKey(Channel.id, ondelete="CASCADE"))
    sender_id = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    channel: Mapped[Channel] = relationship("Channel", back_populates="messages")
    files: Mapped[list[FileAttachment]] = relationship("FileAttachment", secondary="message_files",
                                                       back_populates="messages")
