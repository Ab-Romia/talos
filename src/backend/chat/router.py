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

from typing import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select

from backend.auth.utils.helpers import UserDep
from model import DatabaseDep
from model.identity import User
from model.messaging import Chatroom, users_workspace
from .manager import manager
from .models import MessageEvent, ReadReceiptEvent, ReadReceiptRequest, WSIncoming
from .service import (
    get_message_by_id,
    get_messages,
    send_message,
)

# TODO: permission and authenticate checks for all endpoints,
#  both REST and WebSocket.
router = APIRouter(prefix="/chat", tags=["chat"])


# ── Helper: query channel members from database ────────────────────────────────

def get_channel_members(channel_id: UUID, db: DatabaseDep) -> Sequence[UUID]:
    """
    Query the database to return all user IDs that belong to the chatroom's workspace.

    The current schema does not track chatroom-specific memberships,
    so channel membership is derived from workspace membership.
    """
    stmt = (
        select(User.id)
        .select_from(Chatroom)
        .join(users_workspace, users_workspace.c.workspace_id == Chatroom.workspace_id)
        .join(User, users_workspace.c.user_id == User.id)
        .where(Chatroom.id == channel_id)
        .where(User.deleted_at.is_(None))
    )
    return db.scalars(stmt).all()
##doneeee

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
def get_online_users(channel_id: UUID, db: DatabaseDep):
    """Returns the list of user_ids that have an active WebSocket connection and are channel members."""
    all_members = get_channel_members(channel_id, db)
    online = manager.get_online_users(all_members)
    return {"channel_id": channel_id, "online_users": online}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_channel(
        websocket: WebSocket,
        user: UserDep,
        db: DatabaseDep,
):
    """
    Persistent WebSocket connection for a user.

    On message → send to all channel members (online via WebSocket, offline marked as "to do").
    On read receipt → forward a receipt event back to the original sender.
    On disconnect → close the connection.
    """

    async def handle_send_message(raw: dict) -> None:
        try:
            incoming = WSIncoming(**raw)
        except Exception as exc:
            await websocket.send_json({"event": "error", "detail": str(exc)})
            return

        msg = send_message(
            channel_id=incoming.channel_id,
            user_id=user.id,
            text=incoming.text,
        )

        channel_members = get_channel_members(incoming.channel_id, db)
        other_members = [uid for uid in channel_members if uid != user.id]

        event_payload = MessageEvent(message=msg).model_dump(mode="json")
        delivered_users, offline_users = await manager.broadcast(
            user_ids=other_members,
            payload=event_payload,
        )

        #ack the sender with delivery results so the frontend can show "delivered" status and optionally handle offline users (e.g. show "X users offline, will deliver when they're back online").
        await websocket.send_json({
            **event_payload,
            "delivered": True,
            "delivered_to": delivered_users,
            "offline_users": offline_users,# TODO: implement "to do" delivery for offline users (e.g. push notifications, or store undelivered events in cache for next time they come online).
        })

    async def handle_read_receipt(raw: dict) -> None:
        try:
            receipt = ReadReceiptRequest(**raw)
        except Exception as exc:
            await websocket.send_json({"event": "error", "detail": str(exc)})
            return

        msg = get_message_by_id(receipt.channel_id, receipt.message_id)
        if msg is None:
            await websocket.send_json({"event": "error", "detail": "Message not found"})
            return

        channel_members = get_channel_members(receipt.channel_id, db)
        if user.id not in channel_members:
            await websocket.send_json({"event": "error", "detail": "User is not a member of this channel"})
            return

        # Read receipts are only forwarded to the original sender.
        if msg.sender_id == user.id:
            await websocket.send_json({
                "event_type": "read_receipt_ack",
                "channel_id": str(receipt.channel_id),
                "message_id": str(receipt.message_id),
                "sender_online": True,
                "acknowledged": True,
                "note": "self read receipts are ignored",
            })
            return

        receipt_payload = ReadReceiptEvent(
            channel_id=receipt.channel_id,
            message_id=receipt.message_id,
            reader_id=user.id,
        ).model_dump(mode="json")

        sender_online = await manager.send_to_user(msg.sender_id, receipt_payload)
        await websocket.send_json({
            "event_type": "read_receipt_ack",
            "channel_id": str(receipt.channel_id),
            "message_id": str(receipt.message_id),
            "sender_online": sender_online,
            "acknowledged": True,
        })

    await manager.connect(websocket, user_id=user.id)

    # ── Message loop ──────────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_json()
            event_type = raw.get("event_type", "new_message")

            if event_type == "new_message":
                await handle_send_message(raw)
            elif event_type == "read_receipt":
                await handle_read_receipt(raw)
            else:
                await websocket.send_json({"event": "error", "detail": f"Unsupported event_type: {event_type}"})

    except WebSocketDisconnect:
        manager.disconnect(user.id)
