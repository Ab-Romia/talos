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


def is_ai_trigger(content: str) -> bool:
    stripped = content.strip().lower()
    return any(stripped.startswith(t) for t in _TRIGGERS)


def _strip_trigger(content: str) -> str:
    stripped = content.strip()
    for t in _TRIGGERS:
        if stripped.lower().startswith(t):
            return stripped[len(t):].strip()
    return stripped


async def maybe_ai_reply(channel_id: UUID, content: str) -> None:
    """If the message addresses the AI, generate and broadcast an assistant reply out-of-band."""
    if not is_ai_trigger(content):
        return
    question = _strip_trigger(content)
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

        answer = await asyncio.to_thread(_generate, str(workspace_id), question)
        message = await store_assistant_message(channel_id, ai_user_id, answer)
        await sio.send(message.model_dump(mode="json"), room=room)
    except Exception:
        logger.exception("In-channel AI reply failed", channel_id=str(channel_id))
    finally:
        await sio.emit("ai_typing", {"channel_id": str(channel_id), "status": "stop"}, room=room)


def _generate(workspace_id: str, question: str) -> str:
    from config import global_rag_config
    from rag.rag_chain import RAGChain

    rag = RAGChain(global_rag_config.milvus_collection_name, workspace_id=workspace_id)
    return rag.query(question)
