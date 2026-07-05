from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text as sa_text

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

    async def get_thread(self, root_id: UUID) -> dict | None: ...
    """
    Returns the full subtree rooted at root_id as a nested dict:
        {"message": MessageSchema, "children": [<same shape>, ...]}
    Returns None if root_id is not found.
    Children at every level are ordered by sent_at ASC.
    """


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
            row = await db.scalar(select(Message).where(Message.id == message_id))
            if row is not None:
                return MessageSchema.model_validate(row)
        return None

    @handle_exceptions("Failed to persist message {message_id}", raise_on_error=True)
    async def put(self, message: MessageSchema) -> None:
        """Persist a message to PostgreSQL cold storage."""
        async with self._session_factory() as db:
            row = Message(
                id=message.id,
                channel_id=message.channel_id,
                sender_id=message.sender_id,
                role=message.role,
                sent_at=message.sent_at,
                # NULL is the explicit signal for a root message — never omit.
                parent_id=message.parent_id,
            )
            # parse_doc gives us a live Node so set_content can walk it
            # for mentioned_user_ids extraction and byte-length tracking
            row.set_content(parse_doc(message.content))
            db.add(row)
            await db.commit()

    @handle_exceptions("Failed to load thread for message {root_id}", default_return=None)
    async def get_thread(self, root_id: UUID) -> dict | None:
        """
        Return the full subtree rooted at root_id as nested dicts:
            {"message": MessageSchema, "children": [<same shape>, ...]}

        Built with a single recursive CTE so we make exactly one round-trip
        regardless of tree depth.  Children at every level are ordered by
        sent_at ASC.
        """
        async with self._session_factory() as db:
            # Recursive CTE: anchor on root_id, recurse through parent_id links.
            cte = (
                select(Message)
                .where(Message.id == root_id)
                .cte(name="thread", recursive=True)
            )
            cte = cte.union_all(
                select(Message).join(cte, Message.parent_id == cte.c.id)
            )
            rows = (await db.scalars(
                select(Message)
                .where(Message.id.in_(select(cte.c.id)))
                .order_by(Message.sent_at.asc())
            )).all()

        if not rows:
            return None

        # Index every row and verify the root exists.
        by_id: dict[UUID, MessageSchema] = {
            row.id: MessageSchema.model_validate(row) for row in rows
        }
        if root_id not in by_id:
            return None

        # Build the tree in a single O(n) pass.
        tree: dict[UUID, dict] = {
            msg_id: {"message": msg, "children": []}
            for msg_id, msg in by_id.items()
        }
        root_node = None
        for msg_id, node in tree.items():
            parent_id = node["message"].parent_id
            if parent_id is None or parent_id not in tree:
                # This is the root (or an orphan whose parent wasn't fetched).
                if msg_id == root_id:
                    root_node = node
            else:
                tree[parent_id]["children"].append(node)

        return root_node


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