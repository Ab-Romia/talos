import asyncio
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import StreamingResponse

from auth.dependencies import UserIdDep
from config import global_rag_config
from utils.logger import get_logger
from workspace import require_perms

router = APIRouter(prefix="/workspaces/{workspace_id}/ai", tags=["ai"])


class AiMessage(BaseModel):
    role: str
    content: str


class AiQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[AiMessage] = []
    file_ids: list[uuid.UUID] | None = None
    conversation_id: uuid.UUID | None = None


def _build_chain(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    requested_file_ids: list[uuid.UUID] | None,
    history: list[AiMessage],
):
    from langchain_core.messages import AIMessage, HumanMessage
    from database import SessionLocal
    from rag.access import accessible_file_ids, private_file_ids
    from rag.ai_settings import resolve_ai_config
    from rag.rag_chain import RAGChain
    from rag.vector_store import WORKSPACE_COLLECTION

    # The standalone Talos AI page is a workspace-level assistant: it is grounded
    # in the workspace documents, the caller's own private AI-tab uploads, and
    # this conversation's history — nothing else. It deliberately does NOT recall
    # other channels'/DMs' chat or files.
    with SessionLocal() as db:
        resolved, provenance = resolve_ai_config(workspace_id, None, db)
        allowed_files = accessible_file_ids(db, user_id, workspace_id) | private_file_ids(db, user_id, workspace_id)

    if requested_file_ids:
        allowed_files = allowed_files & set(requested_file_ids)

    def _strip_citations(text: str) -> str:
        return text.split("\n\nSources:", 1)[0].strip()

    chat_history = [
        AIMessage(content=_strip_citations(m.content)) if m.role == "assistant" else HumanMessage(content=m.content)
        for m in history
        if m.content and m.role in ("user", "assistant")
    ]

    return RAGChain(
        WORKSPACE_COLLECTION,
        config=resolved,
        config_provenance=provenance,
        workspace_id=str(workspace_id),
        file_ids=[str(f) for f in allowed_files],
        chat_history=chat_history,
    )


@router.get("/bot", dependencies=[require_perms("files:read")])
async def get_bot_identity(workspace_id: uuid.UUID):
    """The assistant's user identity — used by the mention picker."""
    from database import SessionLocal
    from chat.ai import get_ai_user_id, AI_USERNAME

    def _load():
        with SessionLocal() as db:
            return str(get_ai_user_id(db))

    bot_id = await asyncio.to_thread(_load)
    return {"user_id": bot_id, "username": AI_USERNAME, "name": "Talos AI"}


def _save_message(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
):
    from database import SessionLocal
    from .model import AiChatMessage

    with SessionLocal() as db:
        db.add(
            AiChatMessage(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
        )
        db.commit()


def _conversation_title(rows) -> str:
    """A short label for a conversation — its first user turn, trimmed."""
    for r in rows:
        if r.role == "user" and r.content.strip():
            text = " ".join(r.content.split())
            return text[:80] + ("…" if len(text) > 80 else "")
    return "New chat"


@router.get("/conversations", dependencies=[require_perms("files:read")])
async def list_conversations(workspace_id: uuid.UUID, user_id: UserIdDep):
    """The current user's saved AI conversations in this workspace, newest first."""
    from itertools import groupby
    from sqlalchemy import select
    from database import SessionLocal
    from .model import AiChatMessage

    def _load():
        with SessionLocal() as db:
            rows = db.scalars(
                select(AiChatMessage)
                .where(
                    AiChatMessage.workspace_id == workspace_id,
                    AiChatMessage.user_id == user_id,
                    AiChatMessage.conversation_id.is_not(None),
                )
                .order_by(AiChatMessage.conversation_id, AiChatMessage.created_at, AiChatMessage.id)
            ).all()

            convos = []
            for cid, group in groupby(rows, key=lambda r: r.conversation_id):
                msgs = list(group)
                convos.append(
                    {
                        "id": str(cid),
                        "title": _conversation_title(msgs),
                        "message_count": len(msgs),
                        "created_at": msgs[0].created_at.isoformat(),
                        "updated_at": msgs[-1].created_at.isoformat(),
                    }
                )
            convos.sort(key=lambda c: c["updated_at"], reverse=True)
            return convos

    return await asyncio.to_thread(_load)


@router.get("/conversations/{conversation_id}/messages", dependencies=[require_perms("files:read")])
async def get_conversation_messages(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID, user_id: UserIdDep
):
    """Messages of one saved conversation for the current user."""
    from sqlalchemy import select
    from database import SessionLocal
    from .model import AiChatMessage

    def _load():
        with SessionLocal() as db:
            rows = db.scalars(
                select(AiChatMessage)
                .where(
                    AiChatMessage.workspace_id == workspace_id,
                    AiChatMessage.user_id == user_id,
                    AiChatMessage.conversation_id == conversation_id,
                )
                .order_by(AiChatMessage.created_at, AiChatMessage.id)
            ).all()
            return [
                {"id": str(r.id), "role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
                for r in rows
            ]

    return await asyncio.to_thread(_load)


@router.delete(
    "/conversations/{conversation_id}", dependencies=[require_perms("files:read")], status_code=204
)
async def delete_conversation(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID, user_id: UserIdDep
):
    """Delete one saved conversation belonging to the current user."""
    from sqlalchemy import delete
    from database import SessionLocal
    from .model import AiChatMessage

    def _clear():
        with SessionLocal() as db:
            db.execute(
                delete(AiChatMessage).where(
                    AiChatMessage.workspace_id == workspace_id,
                    AiChatMessage.user_id == user_id,
                    AiChatMessage.conversation_id == conversation_id,
                )
            )
            db.commit()

    await asyncio.to_thread(_clear)


@router.post("/query", dependencies=[require_perms("files:read")])
async def query(workspace_id: uuid.UUID, req: AiQueryRequest, user_id: UserIdDep):
    """Stream a RAG answer grounded in the workspace's documents and chat history."""
    conversation_id = req.conversation_id or uuid.uuid7()
    rag = await asyncio.to_thread(_build_chain, workspace_id, user_id, req.file_ids, req.history)

    await asyncio.to_thread(_save_message, workspace_id, user_id, conversation_id, "user", req.question)

    def sync_gen():
        answer_parts: list[str] = []
        try:
            for chunk in rag.stream_query(req.question):
                answer_parts.append(chunk)
                yield chunk
        except Exception as exc:
            get_logger(__name__).exception("AI stream failed", exc_info=exc)
            failure = "\n\n[The assistant could not complete the request. Please try again.]"
            answer_parts.append(failure)
            yield failure
        finally:
            from rag.ingestion import dedupe_sources
            answer = dedupe_sources("".join(answer_parts))
            if answer.strip():
                try:
                    _save_message(workspace_id, user_id, conversation_id, "assistant", answer)
                except Exception:
                    pass

    return StreamingResponse(
        iterate_in_threadpool(sync_gen()),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "X-Conversation-Id": str(conversation_id),
            "Access-Control-Expose-Headers": "X-Conversation-Id",
        },
    )
