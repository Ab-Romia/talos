from uuid import UUID

from utils.logger import get_logger
from .model import MessageSchema, MessageRole
from .storage import get_storage

logger = get_logger(__name__)


async def store_message(channel_id: UUID, user_id: UUID, content: str) -> MessageSchema:
    """Persist a user message to both hot and cold storage."""
    msg = MessageSchema(
        channel_id=channel_id,
        sender_id=user_id,
        role=MessageRole.USER,
        content=content,
    )
    await get_storage().put(msg)

    return msg


async def store_assistant_message(channel_id: UUID, sender_id: UUID, content: str) -> MessageSchema:
    """Persist an AI assistant message. Not indexed to avoid retrieval feedback loops."""
    msg = MessageSchema(
        channel_id=channel_id,
        sender_id=sender_id,
        role=MessageRole.ASSISTANT,
        content=content,
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
    """Fetch a single message; hot cache checked first, then cold store."""
    return await get_storage().get_by_id(message_id)
