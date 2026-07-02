from datetime import datetime
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
from .search import search_messages

channel = APIRouter(tags=["chat"])


# TODO: support message editing, deletion, reactions, threads, etc. (See Requirements)
#  support same facilities as websocket?

# TODO: support rich text, attachments, replies, etc. (See Requirements)
class SendRequest(BaseModel):
    text: str


class ChatMessageResponse(BaseModel):
    """Response model for a single chat message."""
    id: UUID
    channel_id: UUID
    sender_id: UUID | None
    role: str
    content: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class ChatSearchResponse(BaseModel):
    """Response model for chat search results."""
    messages: list[ChatMessageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


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
    "/online",
    summary="List users currently online in a channel",
    dependencies=[require("channel:view", "channel.member:view_presence")]
)
def get_online_users(channel_id: UUID, db: DatabaseDep):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    online = get_channel_online(channel_id, db)
    return {"channel_id": channel_id, "online_users": online}


@channel.get(
    "/messages/search",
    summary="Search messages in a channel",
    dependencies=[require("channel:view", "channel.message:view_history")]
)
async def search_channel_messages(
    channel_id: UUID,
    text: str | None = Query(None, description="Search in message content"),
    author_id: UUID | None = Query(None, description="Filter by sender/author ID"),
    start_date: datetime | None = Query(None, description="Filter messages from this date onwards"),
    end_date: datetime | None = Query(None, description="Filter messages up to this date"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> ChatSearchResponse:
    """
    Search chat messages within a channel.

    Supports filtering by:
    - text: Full-text search in message content
    - author_id: Sender/author of the message
    - start_date/end_date: Date range filter
    - Pagination via page and page_size
    """
    offset = (page - 1) * page_size
    messages, total = await search_messages(
        channel_id=channel_id,
        text=text,
        author_id=author_id,
        start_date=start_date,
        end_date=end_date,
        limit=page_size,
        offset=offset,
    )

    # Convert messages to response format
    message_responses = [
        ChatMessageResponse(
            id=msg.id,
            channel_id=msg.channel_id,
            sender_id=msg.sender_id,
            role=msg.role,
            content=msg.content,
            sent_at=msg.sent_at,
        )
        for msg in messages
    ]

    total_pages = (total + page_size - 1) // page_size
    has_next = page < total_pages
    has_previous = page > 1

    return ChatSearchResponse(
        messages=message_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous,
    )


