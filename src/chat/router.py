from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from auth.utils.session import SessionDep
from database import DatabaseDep
from workspace import require_perms as require
from .realtime import get_channel_online
from .service import (
    get_message_by_id,
    get_messages,
    store_message,
)

channel = APIRouter(tags=["chat"])


# TODO: support message editing, deletion, reactions, threads, etc. (See Requirements)
#  support same facilities as websocket?

# TODO: support rich text, attachments, replies, etc. (See Requirements)
class SendRequest(BaseModel):
    text: str


@channel.post("/messages", dependencies=[require("channel.message:send")])
async def post_message(channel_id: UUID, req: SendRequest, session: SessionDep):
    """
    Send a message to a channel over plain HTTP.
    Returns the persisted Message object.
    TODO: push a real-time notification via taskiq
    Does NOT push a real-time notification — use the WebSocket endpoint for that.
    """
    from chat.realtime import sio
    message = await store_message(channel_id=channel_id, user_id=cast(UUID, session.sub), content=req.text)

    # Broadcast to everyone in the channel room. NOTE: this MUST be awaited — sio.send on
    # an AsyncServer returns a coroutine, and a bare (un-awaited) call silently no-ops.
    # Payload shape is kept identical to the WebSocket `message` handler so clients have a
    # single shape to parse: the serialized MessageSchema dict.
    await sio.send(
        message.model_dump(mode="json"),
        room=f"channel:{channel_id}",
    )

    import asyncio
    from chat.realtime import _notify_channel_members
    asyncio.create_task(_notify_channel_members(
        channel_id=channel_id,
        sender_id=cast(UUID, session.sub),
        content=req.text,
    ))

    return {
        "id": message.id,
        "sent_at": message.sent_at,
    }


@channel.get(
    "/messages",
    summary="Get paginated message history",
    dependencies=[require("channel:view")]
)
async def get_channel_messages(
        channel_id: UUID,
        limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
        offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Get a paginated list of messages for a channel.
    Messages are returned in reverse chronological order (newest first)
    """
    return await get_messages(channel_id, limit=limit, offset=offset)


@channel.get(
    "/messages/{message_id}",
    summary="Get a single message by ID",
    dependencies=[require("channel:view")]
)
async def get_single_message(channel_id: UUID, message_id: UUID):
    msg = await get_message_by_id(message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@channel.get(
    "/online",
    summary="List users currently online in a channel",
    dependencies=[require("channel:view", "channel.member:view_presence")]
)
def get_online_users(channel_id: UUID, db: DatabaseDep):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    online = get_channel_online(channel_id, db)
    return {"channel_id": channel_id, "online_users": online}
