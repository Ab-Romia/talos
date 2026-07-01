"""Streaming RAG endpoint.

`POST /api/workspaces/{workspace_id}/channels/{channel_id}/ask` — authenticated,
workspace-scoped, streamed, multi-turn. Mounted under the channel router so the
workspace:view / channel:view perms already apply; this adds channel.message:send.

Context is delivered in two tiers (the indexed_at partition):
  - tier 1: the channel's UN-INDEXED tail (indexed_at IS NULL, capped) injected
    directly as chat_history;
  - tier 2: the indexed body recalled via RAGChain's per-channel chat retriever.
Every message is in exactly one tier, so nothing is lost and nothing double-counts.
"""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth.utils.session import SessionDep
from chat.model import Message, MessageRole
from chat.service import store_message
from config import global_rag_config
from database import AsyncSessionLocal
from utils.logger import get_logger
from workspace import require_perms as require
from workspace.model import Channel

from .rag_chain import RAGChain
from .vector_store import WORKSPACE_COLLECTION

logger = get_logger(__name__)

ask = APIRouter(tags=["rag"])

# Matches the citation footer RAGChain.stream_query appends; kept OUT of the
# stored assistant content so the next turn's history isn't polluted.
_CITATION_MARKER = "\n\nSources:"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    file_ids: list[UUID] | None = None
    include_citations: bool = True
    debug: bool = False  # log model + retrieved chunks + exact prompt for this call


async def _load_unindexed_tail(channel_id: UUID, cap: int) -> list[BaseMessage]:
    """The channel's un-indexed tail (tier 1), chronological, capped.

    These are exactly the messages not yet embedded into Milvus. A full tail
    (len == cap) means the indexer is lagging, so warn.
    """
    if cap <= 0:
        return []
    async with AsyncSessionLocal() as db:
        rows = list(await db.scalars(
            select(Message)
            .where(Message.channel_id == channel_id)
            .where(Message.indexed_at.is_(None))
            .order_by(Message.sent_at.desc())
            .limit(cap)
        ))
    if len(rows) >= cap:
        logger.warning("un-indexed chat tail hit cap; indexer may be lagging",
                       channel_id=str(channel_id), cap=cap)
    history: list[BaseMessage] = []
    for m in reversed(rows):  # oldest -> newest
        history.append(
            AIMessage(content=m.content) if m.role == MessageRole.ASSISTANT
            else HumanMessage(content=m.content)
        )
    return history


async def _persist_assistant_turn(channel_id: UUID, answer: str) -> None:
    """Persist the assistant answer (sender_id NULL, role ASSISTANT). Uses the
    ORM directly because MessageSchema requires a non-null sender_id."""
    if not answer:
        return
    async with AsyncSessionLocal() as db:
        db.add(Message(channel_id=channel_id, sender_id=None,
                       content=answer, role=MessageRole.ASSISTANT))
        await db.commit()


@ask.post("/ask", dependencies=[require("channel.message:send")])
async def ask_question(channel_id: UUID, body: AskRequest, session: SessionDep):
    """Stream a multi-turn RAG answer over the workspace's indexed documents,
    with the channel's own indexed conversation recalled as memory.

    The channel router carries no workspace_id in its path, so the workspace is
    resolved from the channel for file-retrieval scoping.
    """
    async with AsyncSessionLocal() as db:
        workspace_id = await db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="channel not found")

    # Load the tail BEFORE persisting the current question, so this turn's
    # question isn't duplicated into its own chat_history.
    history = await _load_unindexed_tail(channel_id, global_rag_config.chat_context_cap)
    await store_message(channel_id=channel_id, user_id=cast(UUID, session.sub), content=body.question)

    file_ids = [str(fid) for fid in body.file_ids] if body.file_ids else None
    chain = RAGChain(
        collection_name=WORKSPACE_COLLECTION,
        workspace_id=str(workspace_id),
        file_ids=file_ids,
        chatroom_id=str(channel_id),
        chat_history=history,
    )

    async def stream():
        parts: list[str] = []
        for chunk in chain.stream_query(body.question, include_citations=body.include_citations):
            parts.append(chunk)
            yield chunk
        # Persist only the model answer (strip the citation footer).
        answer = "".join(parts).split(_CITATION_MARKER, 1)[0].strip()
        await _persist_assistant_turn(channel_id, answer)
        if body.debug:
            _log_debug(chain, history, body.question)

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


def _log_debug(chain, history, question: str) -> None:
    """Log what /ask actually used: model, retrieved chunks, and the exact prompt."""
    from config import RAG_PROMPT
    try:
        prompt = "\n\n".join(
            f"[{m.type}] {m.content}"
            for m in RAG_PROMPT.format_messages(
                context=chain.last_context, question=question, chat_history=history)
        )
        logger.info(
            "ask.debug",
            model=global_rag_config.openai_model,
            embedding_provider=global_rag_config.embedding_provider,
            rewritten_query=chain.last_query_info.get("rewritten_query"),
            file_chunks=[d.metadata for d in chain.retrieved_docs],
            chat_chunks=[{"message_id": d.metadata.get("message_id"), "text": d.page_content}
                         for d in chain.last_chat_docs],
            injected_tail_size=len(history),
            prompt=prompt,
        )
    except Exception:
        logger.warning("ask debug logging failed", exc_info=True)
