import asyncio
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import StreamingResponse

from auth.dependencies import UserIdDep
from config import global_rag_config
from workspace import require_perms

router = APIRouter(prefix="/workspaces/{workspace_id}/ai", tags=["ai"])


class AiMessage(BaseModel):
    role: str
    content: str


class AiQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[AiMessage] = []
    file_ids: list[uuid.UUID] | None = None


def _build_chain(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    requested_file_ids: list[uuid.UUID] | None,
    history: list["AiMessage"],
):
    from langchain_core.messages import AIMessage, HumanMessage
    from rag.rag_chain import RAGChain
    from rag.access import accessible_file_ids, accessible_channel_ids
    from database import SessionLocal

    with SessionLocal() as db:
        allowed_files = accessible_file_ids(db, user_id, workspace_id)
        allowed_channels = accessible_channel_ids(db, user_id, workspace_id)

    if requested_file_ids:
        allowed_files = allowed_files & set(requested_file_ids)
        allowed_channels = set()

    def _strip_citations(text: str) -> str:
        return text.split("\n\nSources:", 1)[0].strip()

    chat_history = [
        AIMessage(content=_strip_citations(m.content)) if m.role == "assistant" else HumanMessage(content=m.content)
        for m in history
        if m.content
    ]

    return RAGChain(
        global_rag_config.milvus_collection_name,
        workspace_id=str(workspace_id),
        file_ids=[str(f) for f in allowed_files],
        channel_ids=[str(c) for c in allowed_channels],
        chat_history=chat_history,
    )


def _save_message(workspace_id: uuid.UUID, user_id: uuid.UUID, role: str, content: str):
    from database import SessionLocal
    from .model import AiChatMessage

    with SessionLocal() as db:
        db.add(AiChatMessage(workspace_id=workspace_id, user_id=user_id, role=role, content=content))
        db.commit()


@router.get("/messages", dependencies=[require_perms("files:read")])
async def get_ai_messages(workspace_id: uuid.UUID, user_id: UserIdDep):
    """The current user's saved AI conversation in this workspace."""
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
                )
                .order_by(AiChatMessage.created_at, AiChatMessage.id)
            ).all()
            return [
                {"id": str(r.id), "role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
                for r in rows
            ]

    return await asyncio.to_thread(_load)


@router.delete("/messages", dependencies=[require_perms("files:read")], status_code=204)
async def clear_ai_messages(workspace_id: uuid.UUID, user_id: UserIdDep):
    """Delete the current user's AI conversation in this workspace (New chat)."""
    from sqlalchemy import delete
    from database import SessionLocal
    from .model import AiChatMessage

    def _clear():
        with SessionLocal() as db:
            db.execute(
                delete(AiChatMessage).where(
                    AiChatMessage.workspace_id == workspace_id,
                    AiChatMessage.user_id == user_id,
                )
            )
            db.commit()

    await asyncio.to_thread(_clear)


@router.post("/query", dependencies=[require_perms("files:read")])
async def query(workspace_id: uuid.UUID, req: AiQueryRequest, user_id: UserIdDep):
    """Stream a RAG answer grounded in the workspace's documents and chat history."""
    rag = await asyncio.to_thread(_build_chain, workspace_id, user_id, req.file_ids, req.history)

    await asyncio.to_thread(_save_message, workspace_id, user_id, "user", req.question)

    def sync_gen():
        answer_parts: list[str] = []
        try:
            for chunk in rag.stream_query(req.question):
                answer_parts.append(chunk)
                yield chunk
        except Exception as exc:
            failure = f"\n\n[The assistant could not complete the request: {type(exc).__name__}: {exc}]"
            answer_parts.append(failure)
            yield failure
        finally:
            answer = "".join(answer_parts)
            if answer.strip():
                try:
                    _save_message(workspace_id, user_id, "assistant", answer)
                except Exception:
                    pass

    return StreamingResponse(
        iterate_in_threadpool(sync_gen()),
        media_type="text/plain; charset=utf-8",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
