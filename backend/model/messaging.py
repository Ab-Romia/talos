import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, UUID, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from backend.model.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    owner_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column()

    chatrooms: Mapped[list["Chatroom"]] = relationship("Chatroom", back_populates="workspace")


class Chatroom(Base):
    __tablename__ = "chatrooms"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(index=True)
    workspace_id = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column()

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="chatroom")
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="chatrooms")


class Message(Base):
    __tablename__ = "messages"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    chatroom_id = mapped_column(ForeignKey("chatrooms.id", ondelete="CASCADE"))
    sender_id = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)

    chatroom: Mapped["Chatroom"] = relationship("Chatroom", back_populates="messages")
