"""Chat and workspace endpoints — connects frontend to RAG pipeline."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from backend.auth.utils.helpers import active_user, UserDep
from files.dependencies import get_workspace_member
from model import DatabaseDep
from model.identity import User
from model.messaging import Workspace, Chatroom, Message
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ── Schemas ──

class WorkspaceCreate(BaseModel):
    name: str


class ChatroomCreate(BaseModel):
    name: str


class MessageCreate(BaseModel):
    content: str


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


# ── Chatrooms ──

@router.get("/workspaces/{workspace_id}/chatrooms")
def list_chatrooms(
    workspace_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    chatrooms = db.scalars(
        select(Chatroom).where(
            Chatroom.workspace_id == workspace_id,
            Chatroom.deleted_at.is_(None),
        ).order_by(Chatroom.created_at)
    ).all()
    return [
        {"id": str(c.id), "name": c.name, "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in chatrooms
    ]


@router.post("/workspaces/{workspace_id}/chatrooms", status_code=status.HTTP_201_CREATED)
def create_chatroom(
    workspace_id: uuid.UUID,
    body: ChatroomCreate,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    cr = Chatroom(name=body.name, workspace_id=workspace_id)
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return {"id": str(cr.id), "name": cr.name}


# ── Messages ──

@router.get("/workspaces/{workspace_id}/chatrooms/{chatroom_id}/messages")
def list_messages(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    messages = db.scalars(
        select(Message).where(
            Message.workspace_id == workspace_id,
            Message.chatroom_id == chatroom_id,
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


@router.post("/workspaces/{workspace_id}/chatrooms/{chatroom_id}/messages")
def send_message(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    # Verify chatroom exists in workspace
    chatroom = db.scalar(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.workspace_id == workspace_id,
            Chatroom.deleted_at.is_(None),
        )
    )
    if chatroom is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chatroom not found")

    # Save user message
    user_msg = Message(
        workspace_id=workspace_id,
        chatroom_id=chatroom_id,
        sender_id=user.id,
        content=body.content,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Stream AI response via SSE — uses its own DB session since the
    # outer `db` may close once FastAPI's dependency scope ends.
    def generate_sse():
        from model import SessionLocal
        ai_response = ""
        try:
            from rag.rag_chain import RAGChain
            rag = RAGChain(
                collection_name="talos_documents",
                workspace_id=str(workspace_id),
            )

            # Load recent chat history into RAG memory
            with SessionLocal() as gen_db:
                recent = gen_db.scalars(
                    select(Message).where(
                        Message.chatroom_id == chatroom_id,
                    ).order_by(Message.created_at.desc()).limit(10)
                ).all()
                for msg in reversed(recent[1:]):
                    if msg.sender_id:
                        rag.memory.add_user_message(msg.content)
                    else:
                        rag.memory.add_ai_message(msg.content)

            for chunk in rag.stream_query(body.content):
                ai_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

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
                    chatroom_id=chatroom_id,
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
