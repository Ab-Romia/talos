import enum
import uuid
from datetime import datetime

import sqlalchemy as sql
from sqlalchemy import (
    DateTime, UUID, ForeignKey, String, BigInteger,
    Index, Table, Column, text, func, event, DDL,
)
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


# --- Database trigger to populate workspace_id from channel_id on insert ---
# We create a PL/pgSQL function and a trigger so the logic runs inside the DB.
# Attach function creation to the table before_create and trigger creation to after_create
# so it is available when the trigger is defined.

# Ensure the function exists before we attempt to create the trigger
event.listen(FileAttachment.__table__, "before_create", DDL(
    """
    CREATE OR REPLACE FUNCTION set_file_workspace_from_channel()
        RETURNS trigger AS
    $$
    BEGIN
        SELECT workspace_id
        INTO STRICT NEW.workspace_id
        FROM channels
        WHERE id = NEW.channel_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    """
))
event.listen(FileAttachment.__table__, "after_create", DDL(
    """
    CREATE TRIGGER trg_set_file_workspace_from_channel
        BEFORE INSERT
        ON file_attachments
        FOR EACH ROW
        WHEN (NEW.channel_id IS NOT NULL)
    EXECUTE FUNCTION set_file_workspace_from_channel();
    """
))
