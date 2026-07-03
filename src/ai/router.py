import asyncio
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import StreamingResponse

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


def _build_chain(workspace_id: uuid.UUID, file_ids: list[uuid.UUID] | None):
    from rag.rag_chain import RAGChain

    ids = [str(f) for f in file_ids] if file_ids else None
    return RAGChain(
        global_rag_config.milvus_collection_name,
        workspace_id=str(workspace_id),
        file_ids=ids,
    )


@router.post("/query", dependencies=[require_perms("files:read")])
async def query(workspace_id: uuid.UUID, req: AiQueryRequest):
    """Stream a RAG answer grounded in the workspace's documents and chat history."""
    rag = await asyncio.to_thread(_build_chain, workspace_id, req.file_ids)

    for m in req.history:
        if m.role == "user":
            rag.memory.add_user_message(m.content)
        elif m.role == "assistant":
            rag.memory.add_ai_message(m.content)

    def sync_gen():
        try:
            yield from rag.stream_query(req.question)
        except Exception as exc:
            yield f"\n\n[The assistant could not complete the request: {type(exc).__name__}: {exc}]"

    return StreamingResponse(
        iterate_in_threadpool(sync_gen()),
        media_type="text/plain; charset=utf-8",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
