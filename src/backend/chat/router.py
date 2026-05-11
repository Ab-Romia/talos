"""
Chat router
───────────
REST endpoints and WebSocket endpoint share the *same* service layer,
so the frontend can choose its transport freely.

REST endpoints
──────────────
  POST   /chat/channels/{channel_id}/messages          → send a message
  GET    /chat/channels/{channel_id}/messages           → paginated history
  GET    /chat/channels/{channel_id}/messages/hot       → only hot-cached msgs
  GET    /chat/channels/{channel_id}/messages/{msg_id}  → single message

WebSocket endpoint
──────────────────
  WS     /chat/ws

  Client → Server payload:
      { "channel_id": "...", "text": "..." }

  Server → Client events:
      { "event": "new_message",  "message": {...}, "delivered": true, "offline_recipients": [...] }
      { "event": "error", "detail": "..." }

  Flow when Alice sends a message to channel:
    1.  Server receives { "channel_id": "…", "text": "…" }
    2.  Calls send_message()  ← same function the REST POST uses
    3.  Message hits hot cache + cold store
    4.  Query database to get all channel members
    5.  Send to online users via WebSocket
    6.  Return offline users list for "to do" delivery handling
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.auth.utils.helpers import UserDep
from .manager import manager
from .models import MessageEvent, WSIncoming
from .service import (
    get_message_by_id,
    get_messages,
    send_message,
)

# TODO: permission and authenticate checks for all endpoints,
#  both REST and WebSocket.
router = APIRouter(prefix="/chat", tags=["chat"])


# ── Helper: query channel members from database ────────────────────────────────

def get_channel_members(channel_id: UUID) -> list[UUID]:
    """
    Query the database to get all user_ids in a channel.
    
    For now, returns all workspace users for this channel.
    Adapt this based on your actual user-channel relationship in the DB.
    """

    # You'll need to pass a DB session here; for now this is a placeholder
    # that shows the pattern. In a real app, inject the session via dependency.
    return []


# TODO: implement this function to return actual channel members based on your DB schema.


# ── REST: send ────────────────────────────────────────────────────────────────

# TODO: support rich text, attachments, replies, etc. (See Requirements)
class SendRequest(BaseModel):
    text: str


@router.post(
    "/channels/{channel_id}/messages",
    summary="Send a message (REST)",
)
def post_message(channel_id: UUID, req: SendRequest, user: UserDep):
    """
    Send a message to a channel over plain HTTP.
    Returns the persisted Message object.
    Does NOT push a real-time notification — use the WebSocket endpoint for that.
    """
    return send_message(channel_id=channel_id, user_id=user.id, text=req.text)


# ── REST: read ────────────────────────────────────────────────────────────────

@router.get(
    "/channels/{channel_id}/messages",
    summary="Get paginated message history",
)
def get_channel_messages(
        channel_id: UUID,
        limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
        offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Merged hot-cache + cold-store message history, sorted oldest-first.
    Supports cursor-style pagination via `offset`.
    """
    return get_messages(channel_id, limit=limit, offset=offset)


# @router.get(
#     "/channels/{channel_id}/messages/hot",
#     summary="Get only hot-cached (recent) messages",
# )
# def get_hot_channel_messages(channel_id: UUID):
#     """
#     Returns only messages currently living in the in-memory hot cache.
#     Extremely fast — no cold-store I/O.
#     Use this for 'recent activity' widgets or initial channel render.
#     """
#     return get_hot_messages(channel_id)
# TODO : implement permission checks for accessing hot messages.


@router.get(
    "/channels/{channel_id}/messages/{message_id}",
    summary="Get a single message by ID",
)
def get_single_message(channel_id: UUID, message_id: UUID):
    msg = get_message_by_id(channel_id, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


# ── REST: presence (convenience) ─────────────────────────────────────────────

@router.get(
    "/channels/{channel_id}/online",
    summary="List users currently online in a channel",
)
def get_online_users(channel_id: UUID):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    all_members = get_channel_members(channel_id)
    online = manager.get_online_users(all_members)
    return {"channel_id": channel_id, "online_users": online}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_channel(
        websocket: WebSocket,
        user: UserDep,
):
    """
    Persistent WebSocket connection for a user.

    On message → send to all channel members (online via WebSocket, offline marked as "to do").
    On disconnect → close the connection.
    """

    await manager.connect(websocket, user_id=user.id)

    # ── Message loop ──────────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_json()

            # Validate incoming payload
            try:
                incoming = WSIncoming(**raw)
            except Exception as exc:
                await websocket.send_json({"event": "error", "detail": str(exc)})
                continue

            # ── Core business logic (identical to REST POST) ──────────────────
            msg = send_message(
                channel_id=incoming.channel_id,
                user_id=user.id,
                text=incoming.text,
            )
            # ─────────────────────────────────────────────────────────────────

            # Get all channel members from database
            channel_members = get_channel_members(incoming.channel_id)

            # Filter to exclude sender and get online/offline split
            other_members = [uid for uid in channel_members if uid != user.id]

            # Broadcast to all other members
            event_payload = MessageEvent(message=msg).model_dump(mode="json")
            delivered_users, offline_users = await manager.broadcast(
                user_ids=other_members,
                payload=event_payload,
            )

            # ACK to sender with delivery info
            await websocket.send_json({
                **event_payload,
                "delivered": True,
                "delivered_to": delivered_users,
                "offline_users": offline_users,  # TODO : for later delivery
            })
            # TODO : read receipt - el sa7 wel sa7en (sent w received)

    except WebSocketDisconnect:
        manager.disconnect(user.id)
