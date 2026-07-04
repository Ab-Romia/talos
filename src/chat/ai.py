import asyncio
from uuid import UUID

from sqlalchemy import select

from database import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)

AI_USERNAME = "talos-ai"
_TRIGGERS = ("@talos", "/talos")
_ai_user_id: UUID | None = None


def get_ai_user_id(db) -> UUID:
    """Fetch (or create) the dedicated assistant user used as the sender of AI replies."""
    global _ai_user_id
    if _ai_user_id is not None:
        return _ai_user_id

    from auth.model import User

    user = db.scalar(select(User).where(User.username == AI_USERNAME))
    if user is None:
        user = User(
            username=AI_USERNAME,
            primary_email="ai@talos.local",
            name="Talos AI",
            signup_complete=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    _ai_user_id = user.id
    return _ai_user_id


def is_ai_trigger(content) -> bool:
    from rag.message_text import doc_text
    stripped = doc_text(content).strip().lower()
    return any(stripped.startswith(t) for t in _TRIGGERS)


def _strip_trigger(content: str) -> str:
    stripped = content.strip()
    for t in _TRIGGERS:
        if stripped.lower().startswith(t):
            return stripped[len(t):].strip()
    return stripped


async def maybe_ai_reply(channel_id: UUID, content) -> None:
    """If the message addresses the AI, generate and broadcast an assistant reply out-of-band.

    `content` may be a plain string or a ProseMirror doc dict (rich-msg).
    """
    from rag.message_text import doc_text
    if not is_ai_trigger(content):
        return
    question = _strip_trigger(doc_text(content))
    if not question:
        return
    asyncio.create_task(_run_ai_reply(channel_id, question))


async def _run_ai_reply(channel_id: UUID, question: str) -> None:
    from chat.realtime import sio
    from chat.service import store_assistant_message
    from workspace.model import Channel

    room = f"channel:{channel_id}"
    await sio.emit("ai_typing", {"channel_id": str(channel_id), "status": "start"}, room=room)
    try:
        with SessionLocal() as db:
            workspace_id = db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
            if workspace_id is None:
                return
            ai_user_id = get_ai_user_id(db)

        # Same retrieval stack as /ask: per-channel ai_settings, chat-memory
        # recall (chatroom_id), and the channel's un-indexed tail as history.
        from config import global_rag_config
        from rag.router import _load_unindexed_tail
        history, tail_ids = await _load_unindexed_tail(
            channel_id,
            global_rag_config.chat_context_cap,
            global_rag_config.chat_context_char_budget,
        )
        answer = await asyncio.to_thread(
            _generate, str(workspace_id), channel_id, question, history, tail_ids
        )
        message = await store_assistant_message(channel_id, ai_user_id, answer)
        await sio.send(message.model_dump(mode="json"), room=room)
    except Exception:
        logger.exception("In-channel AI reply failed", channel_id=str(channel_id))
    finally:
        await sio.emit("ai_typing", {"channel_id": str(channel_id), "status": "stop"}, room=room)


def _generate(workspace_id: str, channel_id: UUID, question: str,
              history: list, tail_ids: set[str]) -> str:
    from rag.ai_settings import resolve_ai_config
    from rag.rag_chain import RAGChain
    from rag.vector_store import WORKSPACE_COLLECTION
    from uuid import UUID as _UUID

    with SessionLocal() as db:
        resolved, provenance = resolve_ai_config(_UUID(workspace_id), channel_id, db)
    rag = RAGChain(
        WORKSPACE_COLLECTION,
        config=resolved,
        config_provenance=provenance,
        workspace_id=workspace_id,
        chatroom_id=str(channel_id),
        chat_history=history,
        exclude_message_ids=tail_ids,
    )
    return rag.query(question)
