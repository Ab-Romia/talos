from uuid import uuid4
from .models import Message, MessageRole

# simple in-memory store  →  replace with DB later
# { conversation_id: [Message, ...] } { "conv-1": [msg1, msg2, ...] }
_store: dict[str, list[Message]] = {}


def send(conversation_id: str, text: str) -> Message:
    """Save a user message and return it."""
    msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        text=text,
    )
    _store.setdefault(conversation_id, []).append(msg)
    return msg


def receive(conversation_id: str) -> list[Message]:
    """Return all messages in a conversation."""
    return _store.get(conversation_id, [])


def decode(payload: dict) -> str:
    """Pull the text out of a raw incoming payload."""
    if "text" not in payload:
        raise ValueError("Payload must have a 'text' field")
    return str(payload["text"])