"""Chat-related endpoints: workspaces, channels, messages"""
import json
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload
from starlette import status as starlette_status

from backend.auth.model import User
from backend.auth.utils.helpers import active_user
from files.dependencies import get_workspace_member
from model import DatabaseDep, SessionLocal
from model.messaging import Workspace, Channel, Chatroom, Message
from config import get_effective_rag_config
from utils.logger import get_logger

from .hub import message_hub
from .ws_auth import get_ws_user

logger = get_logger(__name__)
MAX_STREAM_SECONDS = 300

router = APIRouter()


class WorkspaceCreate(BaseModel):
    name: str


class ChannelCreate(BaseModel):
    name: str


class MessageCreate(BaseModel):
    content: str = ""
    file_ids: list[uuid.UUID] | None = None
    metadata: dict = Field(default_factory=dict)
    regenerate_for_ai_message_id: uuid.UUID | None = None


def _message_to_dict(m: Message) -> dict:
    d = {
        "id": str(m.id),
        "sender_id": str(m.sender_id) if m.sender_id else None,
        "content": m.content,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "role": "user" if m.sender_id else "ai",
    }
    files = getattr(m, "files", None) or []
    if files:
        d["attachments"] = [
            {"file_id": str(f.id), "filename": f.original_filename}
            for f in files
        ]
    extra = getattr(m, "message_extra", None) or {}
    if extra:
        d["metadata"] = extra
    return d


@router.get("/workspaces")
def list_workspaces(
        user: User = Depends(active_user),
        db: DatabaseDep = None,
):
    workspaces = db.scalars(
        select(Workspace)
        .where(
            Workspace.owner_id == user.id,
            Workspace.deleted_at.is_(None),
        )
        .order_by(Workspace.created_at.desc())
    ).all()
    return [
        {
            "id": str(w.id),
            "name": w.name,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
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


@router.get("/workspaces/{workspace_id}/chatrooms")
def list_chatrooms(
    workspace_id: uuid.UUID,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    chatrooms = db.scalars(
        select(Chatroom)
        .where(
            Chatroom.workspace_id == workspace_id,
            Chatroom.deleted_at.is_(None),
        )
        .order_by(Chatroom.created_at)
    ).all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in chatrooms
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
def list_channel_messages(
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


@router.get("/workspaces/{workspace_id}/chatrooms/{chatroom_id}/messages")
def list_messages(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100_000),
    before_id: uuid.UUID | None = None,
    after_id: uuid.UUID | None = None,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    q = select(Message).where(
        Message.workspace_id == workspace_id,
        Message.chatroom_id == chatroom_id,
    )

    if before_id is not None:
        ref = db.scalar(
            select(Message.created_at).where(
                Message.id == before_id,
                Message.workspace_id == workspace_id,
                Message.chatroom_id == chatroom_id,
            )
        )
        if ref is not None:
            q = q.where(Message.created_at < ref)

    if after_id is not None:
        ref = db.scalar(
            select(Message.created_at).where(
                Message.id == after_id,
                Message.workspace_id == workspace_id,
                Message.chatroom_id == chatroom_id,
            )
        )
        if ref is not None:
            q = q.where(Message.created_at > ref)

    q = q.order_by(Message.created_at.asc())
    q = q.options(selectinload(Message.files))

    rows = list(db.scalars(q.offset(offset).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    out = [_message_to_dict(m) for m in rows]
    return {
        "messages": out,
        "count": len(out),
        "has_more": has_more,
        "offset": offset,
        "before_id": str(before_id) if before_id else None,
        "after_id": str(after_id) if after_id else None,
    }


def _add_memory_for_regenerate(rag, gen_db, chatroom_id: uuid.UUID, user_msg: Message) -> None:
    q = select(Message).where(
        Message.chatroom_id == chatroom_id,
        or_(
            Message.created_at < user_msg.created_at,
            and_(
                Message.created_at == user_msg.created_at,
                Message.id < user_msg.id,
            ),
        ),
    )
    prior = gen_db.scalars(q.order_by(Message.created_at.desc()).limit(9)).all()
    for m in reversed(prior):
        if m.sender_id:
            rag.memory.add_user_message(m.content)
        else:
            rag.memory.add_ai_message(m.content)


@router.post("/workspaces/{workspace_id}/chatrooms/{chatroom_id}/messages")
async def send_message(
    workspace_id: uuid.UUID,
    chatroom_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(active_user),
    workspace: Workspace = Depends(get_workspace_member),
    db: DatabaseDep = None,
):
    chatroom = db.scalar(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.workspace_id == workspace_id,
            Chatroom.deleted_at.is_(None),
        )
    )
    if chatroom is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")

    is_regen = body.regenerate_for_ai_message_id is not None
    if is_regen:
        aid = body.regenerate_for_ai_message_id
        ai_msg = db.scalars(
            select(Message)
            .where(
                Message.id == aid,
                Message.workspace_id == workspace_id,
                Message.chatroom_id == chatroom_id,
            )
        ).one_or_none()
        if ai_msg is None or ai_msg.sender_id is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Not an assistant message in this room",
            )
        user_msg = db.scalars(
            select(Message)
            .options(selectinload(Message.files))
            .where(
                Message.chatroom_id == chatroom_id,
                Message.sender_id.isnot(None),
                Message.created_at < ai_msg.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        if user_msg is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No user message to regenerate from",
            )
        if user_msg.sender_id != user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Can only regenerate your own prompts",
            )
        db.delete(ai_msg)
        db.commit()
        user_msg = db.scalars(
            select(Message)
            .options(selectinload(Message.files))
            .where(Message.id == user_msg.id)
        ).one()
        attached_file_ids = [str(f.id) for f in (user_msg.files or [])]
        query_text = user_msg.content
        if not (query_text or "").strip() and not attached_file_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot regenerate: original message has no text or attachments",
            )
    else:
        if not (body.content or "").strip() and not (body.file_ids or []):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Message content or file_ids required",
            )
        extra: dict = dict(body.metadata) if body.metadata else {}
        user_msg = Message(
            workspace_id=workspace_id,
            chatroom_id=chatroom_id,
            sender_id=user.id,
            content=body.content,
            message_extra=extra,
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)

        attached_file_ids: list[str] = []
        if body.file_ids:
            from files.service import FileService

            svc = FileService(db, storage=None)
            for fid in body.file_ids:
                if svc.attach_to_message(fid, user_msg.id, workspace_id):
                    attached_file_ids.append(str(fid))

        user_msg = db.scalars(
            select(Message)
            .options(selectinload(Message.files))
            .where(Message.id == user_msg.id)
        ).one()
        if not (user_msg.content or "").strip() and not attached_file_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Message content or file_ids required",
            )
        query_text = user_msg.content

        wid_s, cid_s = str(workspace_id), str(chatroom_id)
        await message_hub.broadcast(
            wid_s,
            cid_s,
            {"type": "message.created", "message": _message_to_dict(user_msg)},
        )

    eff = get_effective_rag_config()

    async def generate_sse() -> AsyncGenerator[str, None]:
        from rag.rag_chain import RAGChain

        ai_response = ""
        started = time.monotonic()
        try:
            rag = RAGChain(
                collection_name="talos_documents",
                config=eff,
                workspace_id=str(workspace_id),
                file_ids=attached_file_ids or None,
            )

            with SessionLocal() as gen_db:
                if is_regen:
                    _add_memory_for_regenerate(rag, gen_db, chatroom_id, user_msg)
                else:
                    recent = gen_db.scalars(
                        select(Message)
                        .where(Message.chatroom_id == chatroom_id)
                        .order_by(Message.created_at.desc())
                        .limit(10)
                    ).all()
                    for m in reversed(recent[1:]):
                        if m.sender_id:
                            rag.memory.add_user_message(m.content)
                        else:
                            rag.memory.add_ai_message(m.content)

            timed_out = False
            for chunk in rag.stream_query(query_text):
                if time.monotonic() - started > MAX_STREAM_SECONDS:
                    timed_out = True
                    break
                ai_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            if timed_out:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Stream exceeded maximum duration'})}\n\n"
                return

            info = rag.last_query_info
            sources = []
            for doc in info.get("retrieved_docs", []):
                meta = doc.metadata
                if "filename" in meta:
                    sources.append(
                        {
                            "filename": meta["filename"],
                            "file_id": meta.get("file_id"),
                            "page_number": meta.get("page_number"),
                        }
                    )
            new_ai_id: str | None = None
            if ai_response:
                with SessionLocal() as s2:
                    nai = Message(
                        workspace_id=workspace_id,
                        chatroom_id=chatroom_id,
                        sender_id=None,
                        content=ai_response,
                        message_extra={},
                    )
                    s2.add(nai)
                    s2.commit()
                    s2.refresh(nai)
                    new_ai_id = str(nai.id)
            done_payload: dict = {"type": "done", "sources": sources}
            if new_ai_id:
                done_payload["ai_message_id"] = new_ai_id
            yield f"data: {json.dumps(done_payload)}\n\n"

        except Exception as e:
            logger.exception("RAG query failed")
            error_msg = f"Sorry, I couldn't process your query. Error: {str(e)}"
            ai_response = error_msg
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            if ai_response:
                with SessionLocal() as gen_db:
                    ai_m = Message(
                        workspace_id=workspace_id,
                        chatroom_id=chatroom_id,
                        sender_id=None,
                        content=ai_response,
                        message_extra={},
                    )
                    gen_db.add(ai_m)
                    gen_db.commit()
                    gen_db.refresh(ai_m)

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-User-Message-Id": str(user_msg.id),
        },
    )


@router.websocket("/workspaces/{workspace_id}/chatrooms/{chatroom_id}/events")
async def chatroom_events(websocket: WebSocket, workspace_id: uuid.UUID, chatroom_id: uuid.UUID):
    await websocket.accept()
    with SessionLocal() as db:
        u = await get_ws_user(websocket, db)
        if u is None:
            return
        ws = db.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.owner_id == u.id,
                Workspace.deleted_at.is_(None),
            )
        )
        if ws is None:
            await websocket.close(code=starlette_status.WS_1008_POLICY_VIOLATION)
            return
        cr = db.scalar(
            select(Chatroom).where(
                Chatroom.id == chatroom_id,
                Chatroom.workspace_id == workspace_id,
                Chatroom.deleted_at.is_(None),
            )
        )
        if cr is None:
            await websocket.close(code=starlette_status.WS_1008_POLICY_VIOLATION)
            return

    w_s, c_s = str(workspace_id), str(chatroom_id)
    await message_hub.add(w_s, c_s, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        message_hub.remove(w_s, c_s, websocket)
