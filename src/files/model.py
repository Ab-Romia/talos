import enum
import uuid
from datetime import datetime

import sqlalchemy as sql
from sqlalchemy import DateTime, ForeignKey, String, BigInteger, Index, text, func, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class MessageFile(Base):
    __tablename__ = "message_files"

    message_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("messages.id", ondelete="CASCADE"),
                                                  primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("file_attachments.id", ondelete="CASCADE"),
                                               primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileAttachment(Base):
    __tablename__ = "file_attachments"

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"),
                                                    index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(sql.Uuid, ForeignKey("channels.id", ondelete="SET NULL"),
                                                         index=True)
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(sql.Uuid, ForeignKey("users.id", ondelete="SET NULL"), )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    processing_status: Mapped[ProcessingStatus] = mapped_column(sql.Enum(ProcessingStatus),
                                                                default=ProcessingStatus.UPLOADED)
    processing_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    workspace = relationship("Workspace", back_populates="files")
    channel = relationship("Channel", back_populates="files")
    uploader = relationship("User", back_populates="uploaded_files")
    messages = relationship("Message", secondary="message_files", back_populates="files")

    __table_args__ = (
        Index("ix_file_workspace_created", "workspace_id", "created_at"),
        Index("ix_file_channel_created", "channel_id", "created_at"),
        Index("ix_file_active", "workspace_id", "created_at",
              postgresql_where=text("deleted_at IS NULL")),
    )


@event.listens_for(FileAttachment, "before_insert")
@event.listens_for(FileAttachment, "before_update")
def set_workspace_id(_mapper, _connection, target):
    from workspace.model import Channel

    if target.channel_id is not None:
        session = sql.orm.object_session(target)
        target.workspace_id = session.get(Channel, target.channel_id).workspace_id
