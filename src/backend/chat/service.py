"""
Service layer — pure business logic.

Every function here is intentionally framework-agnostic so it can be called
from a REST endpoint *or* from inside a WebSocket handler without duplication.

Hot / cold persistence is handled transparently by the cache layer.
Swap cache._persist() / cache._load_cold() for real DB calls and this
file needs zero changes.
"""

from uuid import UUID

from .cache import cache
from .models import WSMessage, MessageRole


# ── write ─────────────────────────────────────────────────────────────────────

def send_message(channel_id: UUID, user_id: UUID, text: str) -> WSMessage:
    """
    Persist a user message (hot cache + cold store) and return it.
    """

    msg = WSMessage(
        channel_id=channel_id,
        sender_id=user_id,
        role=MessageRole.USER,
        text=text,
    )
    cache.put(msg)
    return msg


# ── read ──────────────────────────────────────────────────────────────────────

def get_messages(
        channel_id: UUID,
        limit: int | None = None,
        offset: int = 0,
) -> list[WSMessage]:
    """
    Paginated message history for a channel.
    Merges hot cache + cold store, deduplicates, sorts by sent_at.
    """
    return cache.get_all(channel_id, limit=limit, offset=offset)


def get_hot_messages(channel_id: UUID) -> list[WSMessage]:
    """
    Return only messages still sitting in the hot (in-memory) cache.
    Useful for a 'recent activity' feed with minimal latency.
    """
    return cache.get_hot(channel_id)


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
