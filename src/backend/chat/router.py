import uuid

from backend.auth.model import User
from fastapi import APIRouter, Depends, Query
from files.dependencies import get_workspace_member
from pydantic import BaseModel
from sqlalchemy import select

from backend.auth.utils.helpers import active_user
from model import DatabaseDep
from model.messaging import Workspace, Channel, Message
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/send")
def send_message(req: SendRequest):
    msg = send(req.conversation_id, req.text)
    return msg


@router.get("/{conversation_id}")
def get_messages(conversation_id: str):
    return receive(conversation_id)


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


class SendRequest(BaseModel):
    conversation_id: str
    text: str


@router.post("/workspaces/{workspace_id}/channels/{channel_id}/messages")
def send_message(
        workspace_id: uuid.UUID,
        channel_id: uuid.UUID,
        body: MessageCreate,
        user: User = Depends(active_user),
        workspace: Workspace = Depends(get_workspace_member),
        db: DatabaseDep = None,
):
    pass
