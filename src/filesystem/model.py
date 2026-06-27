import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sql
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, BigInteger, Index, text, func, event, select, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from workspace.model import Channel


# TODO:
class FileStatus(str, enum.Enum):
    # Record created but file not yet uploaded to storage
    PENDING = "pending"
    # File exists in storage (i.e., can be downloaded)
    UPLOADED = "uploaded"
    # File has been processed (e.g., text extracted)
    PROCESSED = "processed"
    # File has been indexed in vector database
    INDEXED = "indexed"

    # File processing attempted but failed (e.g., unsupported format or error during processing)
    PROCESSING_FAILED = "processing_failed"


class MessageFile(Base):
    __tablename__ = "message_files"

    message_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("messages.id", ondelete="CASCADE"),
                                                  primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("files.id", ondelete="CASCADE"),
                                               primary_key=True)

    message = relationship("Message", overlaps="files")
    file = relationship("File", overlaps="files")


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"),
                                                    index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(sql.Uuid, ForeignKey("channels.id", ondelete="SET NULL"),
                                                         index=True)

    uploader_id: Mapped[uuid.UUID | None] = mapped_column(sql.Uuid, ForeignKey("users.id", ondelete="SET NULL"), )

    uri: Mapped[str] = mapped_column(String(2048), nullable=False)

    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256checksum: Mapped[str] = mapped_column(String(64))

    processing_status: Mapped[FileStatus] = mapped_column(sql.Enum(FileStatus),
                                                          default=FileStatus.PENDING)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    workspace = relationship("Workspace", back_populates="files")
    channel = relationship("Channel", back_populates="files", foreign_keys="File.channel_id", passive_deletes="all")
    uploader = relationship("User", back_populates="uploaded_files")
    message = relationship("Message", secondary="message_files", back_populates="files", overlaps="message")

    @staticmethod
    def set_workspace_id(_mapper, connection, target):
        if target.channel_id and not target.workspace_id:
            result = connection.execute(
                select(Channel.workspace_id).where(Channel.id == target.channel_id)
            )
            target.workspace_id = result.scalar_one()

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "channel_id"],
            ["channels.workspace_id", "channels.id"],
            ondelete="CASCADE"
        ),
        Index("ix_file_workspace_created", "workspace_id", "created_at"),
        Index("ix_file_channel_created", "channel_id", "created_at"),
        Index("ix_file_active", "workspace_id", "created_at",
              postgresql_where=text("deleted_at IS NULL")),
    )


event.listen(File, "before_insert", File.set_workspace_id)
event.listen(File, "before_update", File.set_workspace_id)


class FileMetadata(BaseModel):
    id: uuid.UUID | str
    workspace_id: uuid.UUID
    channel_id: uuid.UUID | None

    uploader_id: uuid.UUID

    file_path: str
    original_filename: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    is_dir: bool = False
    sha256checksum: str
    status: FileStatus
    thumbnail_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
