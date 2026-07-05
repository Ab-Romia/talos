from typing import Any, cast
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
    get_thread,
    store_message,
)

channel = APIRouter(tags=["chat"])


# TODO: support message editing, deletion, reactions (See Requirements)
class SendRequest(BaseModel):
    """
    REST body for POST /messages.

    `content` accepts a full ProseMirror JSON dict or a plain string (auto-wrapped).
    `parent_id` is optional — omit or pass null for a root message, provide a UUID to reply.
    """
    content: dict[str, Any] | str
    parent_id: UUID | None = None
    mentioned_user_ids: list[UUID] = []


@channel.post("/messages", dependencies=[require("channel.message:send")])
async def post_message(channel_id: UUID, req: SendRequest, session: SessionDep):
    """
    Send a message to a channel over plain HTTP.
    Returns the persisted message id and sent_at.
    TODO: push a real-time notification via taskiq
    Does NOT push a real-time notification — use the WebSocket endpoint for that.
    """
    from chat.realtime import sio
    message = await store_message(
        channel_id=channel_id,
        user_id=cast(UUID, session.sub),
        content=req.content,
        mentioned_user_ids=req.mentioned_user_ids or [],
        parent_id=req.parent_id,  # None → root, UUID → reply
    )

    sio.send(
        {"message": message.model_dump_json()},
        room=f"channel:{channel_id}"
    )
    return {
        "id": message.id,
        "sent_at": message.sent_at,
    }


@channel.get(
    "/messages",
    summary="Get paginated message history",
    dependencies=[require("channel:view", "channel.message:view_history")]
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
    dependencies=[require("channel:view", "channel.message:view_history")]
)
async def get_single_message(channel_id: UUID, message_id: UUID):
    msg = await get_message_by_id(message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@channel.get(
    "/messages/{message_id}/thread",
    summary="Get the full reply tree rooted at a message",
    dependencies=[require("channel:view", "channel.message:view_history")]
)
async def get_message_thread(channel_id: UUID, message_id: UUID):
    """
    Returns the complete reply subtree rooted at `message_id` as nested JSON.

    Shape:
        {
          "message": { ...MessageSchema fields... },
          "children": [
            {
              "message": { ... },
              "children": [ ... ]   // unlimited depth
            },
            ...
          ]
        }

    Children at every level are ordered by sent_at ASC.
    The root message itself must belong to `channel_id` — the recursive CTE
    fetches all descendants so only one DB round-trip is made regardless of depth.

    404 when the root message does not exist.
    """
    tree = await get_thread(message_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Message not found")

    # Verify the root belongs to the channel declared in the path.
    if tree["message"].channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Message not found")

    def _serialise(node: dict) -> dict:
        return {
            "message": node["message"].model_dump(mode="json", exclude={"is_mentioned"}),
            "children": [_serialise(child) for child in node["children"]],
        }

    return _serialise(tree)


@channel.get(
    "/online",
    summary="List users currently online in a channel",
    dependencies=[require("channel:view", "channel.member:view_presence")]
)
def get_online_users(channel_id: UUID, db: DatabaseDep):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    online = get_channel_online(channel_id, db)
    return {"channel_id": channel_id, "online_users": online}