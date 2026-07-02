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

import asyncio
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import iterate_in_threadpool

from auth.utils.session import SessionDep
from chat.model import Message, MessageRole
from config import global_rag_config
from database import AsyncSessionLocal
from utils.logger import get_logger
from workspace import require_perms as require
from workspace.model import Channel

from .message_text import message_text
from .rag_chain import RAGChain
from .vector_store import WORKSPACE_COLLECTION

logger = get_logger(__name__)

ask = APIRouter(tags=["rag"])

# Matches the citation footer RAGChain.stream_query appends; kept OUT of the
# stored assistant content so the next turn's history isn't polluted.
_CITATION_MARKER = "\n\nSources:"
# When debug is requested, the JSON debug payload is streamed after the answer,
# preceded by this marker so a client can split it off.
_DEBUG_MARKER = "\n\n__ASK_DEBUG__\n"
# Appended to the (already-200) stream when generation fails mid-way, so a
# client can distinguish "model finished" from "backend died".
_ERROR_MARKER = "\n\n[ask:error]"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    file_ids: list[UUID] | None = None
    include_citations: bool = True
    debug: bool = False  # log model + retrieved chunks + exact prompt for this call


async def _load_unindexed_tail(channel_id: UUID, cap: int) -> tuple[list[BaseMessage], set[str]]:
    """The channel's un-indexed tail (tier 1), chronological, capped.

    Returns the history (for the prompt's chat_history slot) and the set of its
    message_ids. The ids let RAGChain drop these from tier-2 recall, so a message
    briefly present in both tiers (its vector is in Milvus before its indexed_at
    commit lands) is still counted exactly once. A full tail (len == cap) means
    the indexer is lagging, so warn. SYSTEM rows (join/leave notices) are
    skipped — they are not conversation.
    """
    if cap <= 0:
        return [], set()
    async with AsyncSessionLocal() as db:
        rows = list(await db.scalars(
            select(Message)
            .where(Message.channel_id == channel_id)
            .where(Message.indexed_at.is_(None))
            .where(Message.role != MessageRole.SYSTEM)
            .order_by(Message.sent_at.desc())
            .limit(cap)
        ))
    if len(rows) >= cap:
        logger.warning("un-indexed chat tail hit cap; indexer may be lagging",
                       channel_id=str(channel_id), cap=cap)
    history: list[BaseMessage] = []
    for m in reversed(rows):  # oldest -> newest
        history.append(
            AIMessage(content=message_text(m)) if m.role == MessageRole.ASSISTANT
            else HumanMessage(content=message_text(m))
        )
    tail_ids = {str(m.id) for m in rows}
    return history, tail_ids


async def _persist_exchange(channel_id: UUID, user_id: UUID, question: str,
                            asked_at, answer: str) -> tuple[UUID, UUID]:
    """Persist the question + answer together, AFTER a successful stream.
    An exchange is only recorded when the answer was actually delivered:
    a mid-stream failure or client disconnect persists nothing, so the tail
    never grows dangling human turns. asked_at (captured at request start)
    keeps the question ordered before the answer. Uses the ORM directly
    because MessageSchema requires a non-null sender_id (assistant rows
    have sender_id NULL)."""
    async with AsyncSessionLocal() as db:
        # Clock-source mix: asked_at is the app server's clock (captured at
        # request start), while the answer's sent_at below defaults to the DB
        # server's now(); ordering relies on generation time exceeding any
        # clock skew between the two (same-host deployment).
        q = Message(channel_id=channel_id, sender_id=user_id,
                    content=question, role=MessageRole.USER, sent_at=asked_at)
        a = Message(channel_id=channel_id, sender_id=None,
                    content=answer, role=MessageRole.ASSISTANT)
        db.add(q)
        db.add(a)
        await db.commit()
        return q.id, a.id


async def _broadcast_ai_message(channel_id: UUID, question_id: UUID, answer_id: UUID,
                                question: str, answer: str) -> None:
    """Fan the finished answer out to everyone in the channel room. The chat
    UI otherwise only shows /ask exchanges to the asker (plain HTTP stream).
    Best-effort: a broadcast failure must never fail the request. NOTE: this
    payload is a custom event, NOT the chat 'message' event — MessageSchema
    requires a non-null sender_id, which assistant rows don't have."""
    try:
        from chat.realtime import sio  # teammate module: import-only, never modified
        await sio.emit(
            "ai_message",
            {
                "channel_id": str(channel_id),
                "question_message_id": str(question_id),
                "message_id": str(answer_id),
                "question": question,
                "content": answer,
                "role": "assistant",
            },
            room=f"channel:{channel_id}",
        )
    except Exception:
        logger.warning("ai_message broadcast failed", channel_id=str(channel_id), exc_info=True)


@ask.post("/ask", dependencies=[require("channel.message:send")])
async def ask_question(channel_id: UUID, body: AskRequest, session: SessionDep):
    """Stream a multi-turn RAG answer over the workspace's indexed documents,
    with the channel's own indexed conversation recalled as memory.

    Retrieval runs eagerly (in a worker thread) so Milvus/rewrite failures
    become a real 502 before any bytes stream; generation is iterated via a
    threadpool so LLM work never blocks the event loop.
    """
    async with AsyncSessionLocal() as db:
        workspace_id = await db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="channel not found")

    history, tail_ids = await _load_unindexed_tail(channel_id, global_rag_config.chat_context_cap)
    asked_at = datetime.now(timezone.utc)
    user_id = cast(UUID, session.sub)

    file_ids = [str(fid) for fid in body.file_ids] if body.file_ids else None
    # TODO: Checking the file ids permissions prior

    def _build_and_prepare():
        # Construction is kept off the event loop together with prepare():
        # on the first request per process it loads the embedding model and
        # cross-encoder (cached afterwards), which would otherwise block the
        # loop for seconds.
        chain = RAGChain(
            collection_name=WORKSPACE_COLLECTION,
            workspace_id=str(workspace_id),
            file_ids=file_ids,
            chatroom_id=str(channel_id),
            chat_history=history,
            exclude_message_ids=tail_ids,
        )
        return chain, chain.prepare(body.question)

    try:
        chain, prepared = await asyncio.to_thread(_build_and_prepare)
    except Exception:
        logger.exception("ask retrieval failed", channel_id=str(channel_id))
        raise HTTPException(status_code=502, detail="retrieval failed")

    async def stream():
        parts: list[str] = []
        gen = chain.stream_answer(prepared, include_citations=body.include_citations)
        try:
            async for chunk in iterate_in_threadpool(gen):
                parts.append(chunk)
                yield chunk
        except Exception:
            logger.exception("ask generation failed", channel_id=str(channel_id))
            yield _ERROR_MARKER
            return
        # Persist only the model answer (strip the citation footer).
        answer = "".join(parts).split(_CITATION_MARKER, 1)[0].strip()
        if answer:
            q_id, a_id = await _persist_exchange(channel_id, user_id, body.question, asked_at, answer)
            await _broadcast_ai_message(channel_id, q_id, a_id, body.question, answer)
        if body.debug:
            import json
            payload = chain.trace.as_dict()
            logger.info("ask.debug", model=payload["model"],
                        chat_candidates=len(payload["chat_candidates"]),
                        injected_tail_size=payload["injected_tail_size"])
            yield _DEBUG_MARKER + json.dumps(payload, default=str)

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
