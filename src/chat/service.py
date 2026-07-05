from uuid import UUID

from .model import MessageSchema, MessageRole, wrap_plain_text
from .storage import get_storage


async def store_message(
    channel_id: UUID,
    user_id: UUID,
    content: dict | str,
    mentioned_user_ids: list[UUID] | None = None,
) -> MessageSchema:
    """
    Persist a user message to storage.

    `content` accepts:
      - dict  — already-validated ProseMirror JSON from MessageCreateSchema
      - str   — plain text from a bot; auto-wrapped into a paragraph doc

    `mentioned_user_ids` is the frontend-supplied list of mentioned user UUIDs.
    It is stored on MessageSchema for in-process fanout (realtime.py).
    The authoritative DB copy is always re-derived from the AST by
    set_content() inside DatabaseStorageBackend.put(), so passing None here
    is safe for callers that don't have a mention list (e.g. bots, HTTP path).
    """
    if isinstance(content, str):
        raw = wrap_plain_text(content).to_json()
    else:
        raw = content  # already validated by MessageCreateSchema upstream

    msg = MessageSchema(
        channel_id=channel_id,
        sender_id=user_id,
        role=MessageRole.USER,
        content=raw,
        mentioned_user_ids=mentioned_user_ids or [],
    )
    await get_storage().put(msg)
    return msg


async def get_messages(
        channel_id: UUID,
        limit: int | None = None,
        offset: int = 0,
) -> list[MessageSchema]:
    """Paginated message history for a channel."""
    return await get_storage().get(channel_id=channel_id, limit=limit, offset=offset)


async def get_message_by_id(message_id: UUID) -> MessageSchema | None:
    """Fetch a single message; storage checked (hot cache first if configured)."""
    return await get_storage().get_by_id(message_id)