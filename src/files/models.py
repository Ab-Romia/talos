import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, UUID, ForeignKey, String, BigInteger,
    Index, Table, Column, text, func,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


message_files = Table(
    "message_files", Base.metadata,
    Column("message_id", UUID(as_uuid=True),
           ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
    Column("file_id", UUID(as_uuid=True),
           ForeignKey("file_attachments.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(), nullable=False, server_default=text("now()")),
)


class FileAttachment(Base):
    __tablename__ = "file_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        ENUM(ProcessingStatus, name="processing_status_enum", create_type=True),
        nullable=False, default=ProcessingStatus.UPLOADED,
    )
    processing_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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
