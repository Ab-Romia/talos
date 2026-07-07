"""Talos capabilities exposed as tools, reusing the existing service layer in-process.

These let the embedded Slack agent and external MCP hosts do "what Talos does"
without re-implementing anything — including chat writes and RAG execution, not just
reads. The bot acts as a single configured service-user (``cfg().bot``) pinned to one
workspace/channel — workspace/channel ids are never taken from tool arguments or other
untrusted input.
"""
import asyncio
import uuid

from chat.model import MessageRole, MessageSchema
from chat.service import get_messages
from chat.storage import get_storage
from config import cfg
from filesystem.service import file_info, list_files
from model import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)


def _bot():
    bot = cfg().bot
    if bot is None:
        raise RuntimeError("Bot identity is not configured (set BOT__* env vars).")
    return bot


async def rag_ask(question: str, file_ids: list[str] | None = None) -> str:
    """Answer a question using Talos's RAG pipeline over the workspace's documents.

    Args:
        question: The natural-language question.
        file_ids: Optional list of file ids to restrict retrieval to specific documents.

    Returns the generated answer with a Sources section.
    """
    from rag.rag_chain import RAGChain  # deferred: pulls in heavy RAG deps lazily

    bot = _bot()

    def _run() -> str:
        chain = RAGChain(
            collection_name=bot.rag_collection,
            workspace_id=bot.default_workspace_id,
            file_ids=file_ids,
        )
        return chain.query(question)

    return await asyncio.to_thread(_run)


async def talos_post_message(content: str) -> dict:
    """Post a message as the Talos bot into its configured channel.

    Args:
        content: The message text.
    """
    bot = _bot()
    msg = MessageSchema(
        channel_id=uuid.UUID(bot.default_channel_id),
        sender_id=uuid.UUID(bot.bot_user_id),
        role=MessageRole.ASSISTANT,
        content=content,
    )
    await get_storage().put(msg)
    return {"ok": True, "message_id": str(msg.id)}


async def talos_read_messages(limit: int = 20) -> list[dict]:
    """Read recent messages from the Talos bot's configured channel (newest first).

    Args:
        limit: Maximum number of messages to return (default 20).
    """
    bot = _bot()
    messages = await get_messages(uuid.UUID(bot.default_channel_id), limit=limit)
    return [
        {"role": m.role.value, "content": m.content, "sent_at": m.sent_at.isoformat()}
        for m in messages
    ]


def talos_list_files(content_type: str | None = None, limit: int = 50) -> list[dict]:
    """List files uploaded in the Talos bot's configured workspace.

    Args:
        content_type: Optional MIME filter; a trailing "/" matches a prefix (e.g. "image/").
        limit: Maximum number of files to return (default 50).
    """
    bot = _bot()
    with SessionLocal() as db:
        files, _ = list_files(
            db,
            workspace_id=uuid.UUID(bot.default_workspace_id),
            channel_id=None,
            content_type=content_type,
            cursor=None,
            limit=limit,
        )
        return [
            {
                "id": str(f.id),
                "filename": f.filename,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "status": f.processing_status.value,
                "uri": f.uri,
            }
            for f in files
        ]


async def talos_get_file(file_id: str) -> dict:
    """Get metadata for a single file in the bot's configured workspace.

    Args:
        file_id: The file's uuid.
    """
    bot = _bot()
    with SessionLocal() as db:
        meta = await file_info(
            db,
            filesystem=None,  # DB-known files don't touch storage
            workspace_id=uuid.UUID(bot.default_workspace_id),
            file_id=uuid.UUID(file_id),
        )
    return meta.model_dump(mode="json")
