import asyncio
import secrets
import threading
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


def _mentions_bot(content) -> bool:
    """True when a rich doc carries a mention node pointing at the bot user."""
    if not isinstance(content, dict):
        return False
    from chat.model import extract_mentioned_user_ids_from_raw
    mentioned = extract_mentioned_user_ids_from_raw(content)
    if not mentioned:
        return False
    with SessionLocal() as db:
        bot_id = get_ai_user_id(db)
    return bot_id in mentioned


def is_ai_trigger(content) -> bool:
    """Mention-style trigger: a real @-mention of the bot, or '@talos'/'/talos'
    appearing anywhere in the text — mirroring how platform mentions behave."""
    from rag.message_text import doc_text
    text = doc_text(content).strip().lower()
    return any(t in text for t in _TRIGGERS) or _mentions_bot(content)


def _strip_trigger(content: str) -> str:
    stripped = content.strip()
    lowered = stripped.lower()
    for t in ("@talos ai", *_TRIGGERS):
        idx = lowered.find(t)
        if idx != -1:
            stripped = (stripped[:idx] + stripped[idx + len(t):]).strip()
            break
    return stripped


# Strong references to in-flight reply tasks: a bare create_task result is only
# weakly held by the loop, so a long generation can be garbage-collected mid-run
# and vanish without a reply OR an error.
_reply_tasks: set = set()


async def maybe_ai_reply(channel_id: UUID, content, user_id: UUID) -> None:
    """If the message addresses the AI, generate and broadcast an assistant reply out-of-band.

    `content` may be a plain string or a ProseMirror doc dict (rich-msg).
    """
    from rag.message_text import doc_text
    if not is_ai_trigger(content):
        return
    question = _strip_trigger(doc_text(content))
    if not question:
        return
    logger.info("AI trigger fired", channel_id=str(channel_id), question=question[:80])
    task = asyncio.create_task(_run_ai_reply(channel_id, question, user_id))
    _reply_tasks.add(task)
    task.add_done_callback(_reply_tasks.discard)


async def _run_ai_reply(channel_id: UUID, question: str, user_id: UUID) -> None:
    from chat.realtime import sio
    from chat.service import store_assistant_message
    from workspace.model import Channel

    room = f"channel:{channel_id}"
    stream_id = secrets.token_hex(8)
    # `ai_typing` covers the retrieval phase (before any token exists); the
    # `ai_stream` events then carry the live token-by-token answer bubble.
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

        # Bridge the sync token generator (runs in a worker thread) to this event
        # loop via a queue, emitting each chunk to the room as it is produced.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _produce():
            try:
                for chunk in _stream_generate(
                    str(workspace_id), channel_id, question, history, tail_ids, user_id
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, ("delta", chunk))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        threading.Thread(target=_produce, daemon=True).start()

        await sio.emit(
            "ai_stream",
            {"channel_id": str(channel_id), "stream_id": stream_id,
             "status": "start", "sender_id": str(ai_user_id)},
            room=room,
        )

        parts: list[str] = []
        errored = False
        while True:
            kind, payload = await queue.get()
            if kind == "delta":
                parts.append(payload)
                await sio.emit(
                    "ai_stream",
                    {"channel_id": str(channel_id), "stream_id": stream_id, "delta": payload},
                    room=room,
                )
            elif kind == "error":
                errored = True
                logger.error("In-channel AI streaming errored", channel_id=str(channel_id),
                             error=str(payload)[:300])
            elif kind == "done":
                break

        from rag.ingestion import dedupe_sources
        answer = dedupe_sources("".join(parts).strip())
        if not answer:
            answer = ("Sorry — I ran into an error generating a response."
                      if errored else "I don't have anything to add.")
        message = await store_assistant_message(channel_id, ai_user_id, answer)
        # Final authoritative message replaces the streamed placeholder client-side.
        await sio.emit(
            "ai_stream",
            {"channel_id": str(channel_id), "stream_id": stream_id, "status": "end",
             "message": message.model_dump(mode="json")},
            room=room,
        )
    except Exception:
        logger.exception("In-channel AI reply failed", channel_id=str(channel_id))
        await sio.emit(
            "ai_stream",
            {"channel_id": str(channel_id), "stream_id": stream_id, "status": "end", "error": True},
            room=room,
        )
    finally:
        await sio.emit("ai_typing", {"channel_id": str(channel_id), "status": "stop"}, room=room)


def _stream_generate(workspace_id: str, channel_id: UUID, question: str,
                     history: list, tail_ids: set[str], user_id: UUID):
    """Yield the answer token-by-token (retrieval + LLM streaming)."""
    from rag.access import accessible_file_ids
    from rag.ai_settings import resolve_ai_config
    from rag.rag_chain import RAGChain
    from rag.vector_store import WORKSPACE_COLLECTION
    from uuid import UUID as _UUID

    with SessionLocal() as db:
        resolved, provenance = resolve_ai_config(_UUID(workspace_id), channel_id, db)
        allowed_files = accessible_file_ids(db, user_id, _UUID(workspace_id), channel_id=channel_id)
    rag = RAGChain(
        WORKSPACE_COLLECTION,
        config=resolved,
        config_provenance=provenance,
        workspace_id=workspace_id,
        file_ids=[str(f) for f in allowed_files],
        chatroom_id=str(channel_id),
        chat_history=history,
        exclude_message_ids=tail_ids,
    )
    yield from rag.stream_query(question)
