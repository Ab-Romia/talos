from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from .service import (
    get_message_by_id,
    get_messages,
    store_message,
)
from ..auth.permissions.core import require_perms

router = APIRouter(prefix="/chat", tags=["chat"])


# TODO: support rich text, attachments, replies, etc. (See Requirements)
class SendRequest(BaseModel):
    text: str


@router.post(
    "/channels/{channel_id}/messages",
    summary="Send a message (REST)",
    dependencies=[Depends(require_perms("channel:send", "message:send"))]
)
def post_message(channel_id: UUID, req: SendRequest, session: SessionDep):
    """
    Send a message to a channel over plain HTTP.
    Returns the persisted Message object.
    Does NOT push a real-time notification — use the WebSocket endpoint for that.
    """
    from backend.chat.realtime import sio
    message = store_message(channel_id=channel_id, user_id=session.sub, text=req.text)

    sio.send(
        {"message": message.model_dump_json()},
        room=f"channel:{channel_id}"
    )


@router.get(
    "/channels/{channel_id}/messages",
    summary="Get paginated message history",
    dependencies=[Depends(require_perms("channel:view", "message:view_history"))]
)
def get_channel_messages(
        channel_id: UUID,
        limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
        offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Get a paginated list of messages for a channel.
    Messages are returned in reverse chronological order (newest first)
    """
    return get_messages(channel_id, limit=limit, offset=offset)


@router.get(
    "/channels/{channel_id}/messages/{message_id}",
    summary="Get a single message by ID",
    dependencies=[Depends(require_perms("channel:view", "message:view_history"))]
)
def get_single_message(channel_id: UUID, message_id: UUID):
    msg = get_message_by_id(channel_id, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.get(
    "/channels/{channel_id}/online",
    summary="List users currently online in a channel",
    dependencies=[Depends(require_perms("channel:view", "member:view_presence"))]
)
def get_online_users(channel_id: UUID, db: DatabaseDep):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    online = get_online_users(channel_id, db)
    return {"channel_id": channel_id, "online_users": online}
