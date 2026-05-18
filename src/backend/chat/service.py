from uuid import UUID

from .cache import cache
from .models import WSMessage, MessageRole


def store_message(channel_id: UUID, user_id: UUID, text: str) -> WSMessage:
    """Persist a user message"""

    msg = WSMessage(
        channel_id=channel_id,
        sender_id=user_id,
        role=MessageRole.USER,
        text=text,
    )
    cache.put(msg)
    return msg


def get_messages(
        channel_id: UUID,
        limit: int | None = None,
        offset: int = 0,
) -> list[WSMessage]:
    """ Paginated message history for a channel. """
    return cache.get_all(channel_id, limit=limit, offset=offset)


def get_message_by_id(channel_id: UUID, message_id: UUID) -> WSMessage | None:
    """Fetch a single message; hot cache checked first, then cold store."""
    return cache.get_by_id(channel_id, message_id)


def decode(payload: dict) -> str:
    """
    Pull the text field out of a raw incoming payload dict.
    Kept for backwards compatibility with any code that imports it.
    """
    if "text" not in payload:
        raise ValueError("Payload must contain a 'text' field")
    return str(payload["text"])
