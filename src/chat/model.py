import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, TYPE_CHECKING
from uuid import UUID

from prosemirror.model import Node
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import mapped_column, Mapped, relationship

from database import Base
from .schema import chat_schema

if TYPE_CHECKING:
    from filesystem.model import File
    from workspace.model import Channel


# =============================================================================
# Enums
# =============================================================================

class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"   # e.g. "Alice joined the channel"


class RefType(str, Enum):
    """
    Valid ref_type values for a `reference` node.
    Confirmed: user, channel, file.
    [OPEN]: message, workspace, external_url — add to editor when ready.
    """
    USER         = "user"
    CHANNEL      = "channel"
    FILE         = "file"
    MESSAGE      = "message"
    WORKSPACE    = "workspace"
    EXTERNAL_URL = "external_url"


# =============================================================================
# Content helpers  (prosemirror-py backed)
# =============================================================================

# [OPEN] Max content size — app-layer cap; add a PG CHECK as a secondary net.
MAX_CONTENT_BYTES = 100_000


def parse_doc(raw: dict[str, Any]) -> Node:
    """
    Parse and schema-validate a raw JSON dict into a prosemirror-py Node.
    Raises ValueError on unknown node types, missing required attrs, or
    content-rule violations (e.g. inline node inside doc root).
    Also enforces the MAX_CONTENT_BYTES cap.
    """
    size = len(json.dumps(raw))
    if size > MAX_CONTENT_BYTES:
        raise ValueError(
            f"Message content exceeds {MAX_CONTENT_BYTES} byte limit (got {size} bytes)"
        )
    # Node.from_json raises ValueError for any schema violation
    return Node.from_json(chat_schema, raw)


def wrap_plain_text(text: str) -> Node:
    """
    Wraps a plain string into a minimal doc Node.
    Use server-side when a bot / API consumer posts a plain string.
    """
    return chat_schema.node(
        "doc", {},
        [chat_schema.node("paragraph", {}, [chat_schema.text(text)])]
    )


def extract_mentioned_user_ids(doc: Node) -> list[UUID]:
    """
    Walk the AST and return deduplicated UUIDs from all `mention` nodes.
    Called before every insert/update to keep Message.mentioned_user_ids in sync.
    """
    ids: list[str] = []

    def _visit(node: Node, _pos: int, _parent, _idx: int) -> bool:
        if node.type.name == "mention":
            ids.append(node.attrs["user_id"])
        return True  # keep descending

    doc.descendants(_visit)
    # deduplicate preserving order, then cast to UUID
    return [UUID(uid) for uid in dict.fromkeys(ids)]


# =============================================================================
# Pydantic schemas  (API boundary)
# =============================================================================

class MessageSchema(BaseModel):
    """
    Serialisable representation of a Message — used for API responses and
    as the in-memory record passed between service / storage layers.

    `content` is stored as a plain dict (the JSON form of the ProseMirror doc)
    so Pydantic can serialise it without custom encoders.
    Use `parse_doc(msg.content)` anywhere you need a live Node object.

    `mentioned_user_ids` is populated from the DB column on read (via
    model_validate) and from the frontend-supplied list on write.  The
    authoritative copy for persistence is always the AST-derived value written
    by set_content(); this field is used for in-process fanout only.

    `is_mentioned` is ephemeral — never stored, never read from the DB.
    It is set to True immediately before emitting to a mentioned user's
    personal room so the client can apply per-user notification preferences
    without a separate event type.
    """
    id: UUID = Field(default_factory=uuid.uuid7)
    channel_id: UUID
    sender_id: UUID
    role: MessageRole = MessageRole.USER
    content: dict[str, Any]   # validated ProseMirror JSON (from Node.to_json())
    mentioned_user_ids: list[UUID] = Field(default_factory=list)
    is_mentioned: bool = False  # ephemeral, per-recipient; set True before emitting to a mentioned user
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def validate_content(self) -> "MessageSchema":
        # Runs parse_doc for schema validation + size check on every construction.
        # No-op cost on the happy path; raises ValueError on bad content.
        parse_doc(self.content)
        return self


class MessageCreateSchema(BaseModel):
    """
    Accepted by the REST API (POST /messages) and the WebSocket `message` event.

    `content` accepts:
      - a full ProseMirror JSON dict  (rich-text clients, TipTap frontend)
      - a plain string                (bots, legacy API consumers)

    Plain strings are auto-wrapped into a minimal paragraph doc.

    `mentioned_user_ids` is provided by the frontend as a denormalised UUID[]
    extracted from the editor's mention nodes.  The backend trusts this list
    for real-time fanout; the authoritative DB copy is always re-derived from
    the AST by set_content() at persist time.
    """
    channel_id: UUID
    content: dict[str, Any] | str
    mentioned_user_ids: list[UUID] = Field(default_factory=list)
    role: MessageRole = MessageRole.USER

    @model_validator(mode="after")
    def coerce_and_validate(self) -> "MessageCreateSchema":
        if isinstance(self.content, str):
            # Bot / plain-text path: wrap then serialise back to dict
            self.content = wrap_plain_text(self.content).to_json()
        else:
            # Rich-text path: validate against chat_schema (raises on bad input)
            parse_doc(self.content)
        return self


class ReadReceiptRequest(BaseModel):
    """Client → Server: request to mark a specific message as read."""
    event_type: Literal["read_receipt"] = "read_receipt"
    channel_id: UUID
    message_id: UUID


# =============================================================================
# SQLAlchemy ORM model
# =============================================================================

class Message(Base):
    __tablename__ = "messages"

    # --- identity ------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7
    )

    # --- ownership -----------------------------------------------------------
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE")
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- rich-text content ---------------------------------------------------
    # Stores a validated ProseMirror doc as JSONB.
    # Never write directly — always use set_content().
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Denormalised UUID[] extracted from `mention` nodes.
    # GIN-indexed for fast "notify all mentioned users" queries:
    #   WHERE mentioned_user_ids @> ARRAY['{user_id}'::uuid]
    mentioned_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )

    # Serialised byte-length — stored for O(1) size queries.
    content_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- metadata ------------------------------------------------------------
    role: Mapped[MessageRole] = mapped_column(default=MessageRole.USER)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )

    # [OPEN] Edit history — Option A (edited_at only) ships now.
    # Option B (message_versions table) is additive whenever needed.
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Soft delete — preserves thread shape ("This message was deleted").
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)

    # --- relationships -------------------------------------------------------
    channel: Mapped["Channel"] = relationship("Channel", back_populates="messages")
    files: Mapped[list["File"]] = relationship(
        "File", secondary="message_files", back_populates="message"
    )

    # --- indexes -------------------------------------------------------------
    __table_args__ = (
        Index("ix_messages_channel_sent_at", "channel_id", "sent_at"),
        Index(
            "ix_messages_mentioned_user_ids_gin",
            "mentioned_user_ids",
            postgresql_using="gin",
        ),
        Index(
            "ix_messages_content_gin",
            "content",
            postgresql_using="gin",
        ),
    )

    # --- helpers -------------------------------------------------------------

    def set_content(self, doc: Node) -> None:
        """
        The only sanctioned way to write content.
        Accepts a live prosemirror-py Node, serialises it to JSON,
        and keeps content_size_bytes + mentioned_user_ids in sync.
        """
        raw = doc.to_json()
        self.content = raw
        self.content_size_bytes = len(json.dumps(raw))
        self.mentioned_user_ids = extract_mentioned_user_ids(doc)

    def to_doc(self) -> Node:
        """Deserialise the stored JSONB back into a validated prosemirror-py Node."""
        return parse_doc(self.content)

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} channel={self.channel_id} "
            f"role={self.role} sent_at={self.sent_at}>"
        )