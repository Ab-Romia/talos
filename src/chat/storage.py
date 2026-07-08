from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import AsyncSessionLocal
from utils.exceptions import handle_exceptions
from .model import Message, MessageSchema, parse_doc

DATETIME_MIN = datetime.fromtimestamp(0, timezone.utc)
DATETIME_MAX = datetime.fromtimestamp(2 ** 33 - 1, timezone.utc)  # ~ year 2286


class ChatStorageBackend(Protocol):
    """Abstract chat storage backend interface."""

    async def put(self, message: MessageSchema) -> None: ...

    async def get(
        self,
        channel_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newer_than: datetime = DATETIME_MIN,
        older_than: datetime = DATETIME_MAX,
        except_ids: set[UUID] | None = None,
    ) -> list[MessageSchema]: ...

    async def get_by_id(self, message_id: UUID) -> MessageSchema | None: ...


class DatabaseStorageBackend(ChatStorageBackend):
    """Cold storage layer using PostgreSQL."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or AsyncSessionLocal

    @handle_exceptions("Failed to load messages for channel {channel_id}", default_return=[])
    async def get(
        self,
        channel_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newer_than=DATETIME_MIN,
        older_than=DATETIME_MAX,
        except_ids=None,
    ) -> list[MessageSchema]:
        """Retrieve messages from PostgreSQL cold storage."""
        async with self._session_factory() as db:
            rows = await db.scalars(
                select(Message)
                .options(selectinload(Message.files))
                .where(Message.channel_id == channel_id)
                .where(Message.id.not_in(except_ids or {}))
                .where(Message.sent_at > newer_than, Message.sent_at < older_than)
                .limit(limit)
                .offset(offset)
                .order_by(Message.sent_at.desc())
                .execution_options(synchronize_session=False)
            )

            return [MessageSchema.model_validate(row) for row in rows]

    @handle_exceptions("Failed to load message {message_id}", default_return=None)
    async def get_by_id(self, message_id: UUID) -> MessageSchema | None:
        """Retrieve a specific message from PostgreSQL cold storage."""
        async with self._session_factory() as db:
            row = await db.scalar(
                select(Message)
                .options(selectinload(Message.files))
                .where(Message.id == message_id)
            )
            if row is not None:
                return MessageSchema.model_validate(row)
        return None

    @handle_exceptions("Failed to persist message {message_id}", raise_on_error=True)
    async def put(self, message: MessageSchema) -> None:
        """Persist a message to PostgreSQL cold storage."""
        from filesystem.model import MessageFile

        async with self._session_factory() as db:
            row = Message(
                id=message.id,
                channel_id=message.channel_id,
                sender_id=message.sender_id,
                role=message.role,
                reply_to_id=message.reply_to_id,
                sent_at=message.sent_at,
            )
            # parse_doc gives us a live Node so set_content can walk it
            # for mentioned_user_ids extraction and byte-length tracking
            row.set_content(parse_doc(message.content))
            db.add(row)
            for att in message.attachments or []:
                db.add(MessageFile(message_id=row.id, file_id=UUID(str(att["id"]))))
            await db.commit()


def bind_chat_storage(storage: ChatStorageBackend) -> None:
    """Bind the storage backend singleton (call on app startup)."""
    global _storage
    _storage = storage


def get_storage() -> ChatStorageBackend:
    """Return the bound storage singleton."""
    if _storage is None:
        raise RuntimeError("Storage not initialized. Call bind_chat_storage() on startup.")
    return _storage


_storage: ChatStorageBackend | None = None