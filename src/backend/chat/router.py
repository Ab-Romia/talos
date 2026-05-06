"""Chat-related endpoints: workspaces, channels, messages"""
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from backend.auth.model import User
from backend.auth.utils.helpers import active_user
from files.dependencies import get_workspace_member
from model import DatabaseDep
from model.messaging import Workspace, Channel, Message
from utils.logger import get_logger

logger = get_logger(__name__)

# Hard ceiling on how long an SSE stream may run before the server closes it.
# Prevents zombie streams if the upstream LLM or retriever hangs.
MAX_STREAM_SECONDS = 300

router = APIRouter()


# ── Schemas ──

class WorkspaceCreate(BaseModel):
    name: str


class ChannelCreate(BaseModel):
    name: str


class MessageCreate(BaseModel):
    content: str
    file_ids: list[uuid.UUID] | None = None


# ── Workspaces ──

@router.get("/workspaces")
def list_workspaces(
        user: User = Depends(active_user),
        db: DatabaseDep = None,
):
    workspaces = db.scalars(
        select(Workspace).where(
            Workspace.owner_id == user.id,
            Workspace.deleted_at.is_(None),
        ).order_by(Workspace.created_at.desc())
    ).all()
    return [
        {"id": str(w.id), "name": w.name, "created_at": w.created_at.isoformat() if w.created_at else None}
        for w in workspaces
    ]


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(
        body: WorkspaceCreate,
        user: User = Depends(active_user),
        db: DatabaseDep = None,
):
    ws = Workspace(name=body.name, owner_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return {"id": str(ws.id), "name": ws.name}


@router.get("/workspaces/{workspace_id}")
def get_workspace(
        workspace_id: uuid.UUID,
        workspace: Workspace = Depends(get_workspace_member),
):
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
    }


@router.get("/workspaces/{workspace_id}/channels")
def list_channels(
        workspace_id: uuid.UUID,
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
):
    channels = db.scalars(
        select(Channel).where(
            Channel.workspace_id == workspace_id,
            Channel.deleted_at.is_(None),
        ).order_by(Channel.created_at)
    ).all()
    return [
        {"id": str(c.id), "name": c.name, "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in channels
    ]


@router.post("/workspaces/{workspace_id}/channels", status_code=status.HTTP_201_CREATED)
def create_channel(
        workspace_id: uuid.UUID,
        body: ChannelCreate,
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
):
    cr = Channel(name=body.name, workspace_id=workspace_id)
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return {"id": str(cr.id), "name": cr.name}


# ── Messages ──

@router.get("/workspaces/{workspace_id}/channels/{channel_id}/messages")
def list_messages(
        workspace_id: uuid.UUID,
        channel_id: uuid.UUID,
        limit: int = Query(50, ge=1, le=200),
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
):
    messages = db.scalars(
        select(Message).where(
            Message.workspace_id == workspace_id,
            Message.channel_id == channel_id,
        ).order_by(Message.created_at.asc()).limit(limit)
    ).all()
    return [
        {
            "id": str(m.id),
            "sender_id": str(m.sender_id) if m.sender_id else None,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "role": "user" if m.sender_id else "ai",
        }
        for m in messages
    ]


@router.post("/workspaces/{workspace_id}/channels/{channel_id}/messages")
def send_message(
        workspace_id: uuid.UUID,
        channel_id: uuid.UUID,
        body: MessageCreate,
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
):
    # Verify channel exists in workspace
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.workspace_id == workspace_id,
            Channel.deleted_at.is_(None),
        )
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")

    # Save user message
    user_msg = Message(
        workspace_id=workspace_id,
        channel_id=channel_id,
        sender_id=user.id,
        content=body.content,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Attach any referenced files to the message so retrieval can scope
    # to them. Silently skip ids that don't belong to this workspace.
    attached_file_ids: list[str] = []
    if body.file_ids:
        from files.service import FileService
        svc = FileService(db, storage=None)
        for fid in body.file_ids:
            if svc.attach_to_message(fid, user_msg.id, workspace_id):
                attached_file_ids.append(str(fid))

    # Stream AI response via SSE — uses its own DB session since the
    # outer `db` may close once FastAPI's dependency scope ends.
    def generate_sse():
        from model import SessionLocal
        ai_response = ""
        started = time.monotonic()
        try:
            from rag.rag_chain import RAGChain
            rag = RAGChain(
                collection_name="talos_documents",
                workspace_id=str(workspace_id),
                file_ids=attached_file_ids or None,
            )

            # Load recent chat history into RAG memory
            with SessionLocal() as gen_db:
                recent = gen_db.scalars(
                    select(Message).where(
                        Message.channel_id == channel_id,
                    ).order_by(Message.created_at.desc()).limit(10)
                ).all()
                for msg in reversed(recent[1:]):
                    if msg.sender_id:
                        rag.memory.add_user_message(msg.content)
                    else:
                        rag.memory.add_ai_message(msg.content)

            timed_out = False
            for chunk in rag.stream_query(body.content):
                if time.monotonic() - started > MAX_STREAM_SECONDS:
                    timed_out = True
                    break
                ai_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            if timed_out:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Stream exceeded maximum duration'})}\n\n"
                return

            # Send metadata (citations, docs count)
            info = rag.last_query_info
            sources = []
            for doc in info.get("retrieved_docs", []):
                meta = doc.metadata
                if "filename" in meta:
                    sources.append({
                        "filename": meta["filename"],
                        "file_id": meta.get("file_id"),
                        "page_number": meta.get("page_number"),
                    })
            yield f"data: {json.dumps({'type': 'done', 'sources': sources})}\n\n"

        except Exception as e:
            logger.exception("RAG query failed")
            error_msg = f"Sorry, I couldn't process your query. Error: {str(e)}"
            ai_response = error_msg
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"

        # Save AI response to DB with its own session
        if ai_response:
            with SessionLocal() as gen_db:
                ai_msg = Message(
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    sender_id=None,
                    content=ai_response,
                )
                gen_db.add(ai_msg)
                gen_db.commit()

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-User-Message-Id": str(user_msg.id),
        },
    )
