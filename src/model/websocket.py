import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from model import Base


class WebsocketConnection(Base):
    """
    Tracks every live WebSocket connection in the database.

    Why this table exists
    ─────────────────────
    The in-memory ChannelConnectionManager (manager.py) is the fast path —
    it holds live WebSocket objects and handles real-time delivery.
    This table is the durable record — it lets you:
      • recover presence state after a server restart
      • query which users are online across multiple server processes
      • audit connection history

    Relationship to manager.py
    ──────────────────────────
    manager._channels  =  { channel_id: { user_id: WebSocket } }

    This table mirrors exactly that structure:
      WebsocketConnection.chatroom_id  →  channel_id  (outer key)
      WebsocketConnection.user_id      →  user_id     (inner key)

    Lifecycle
    ─────────
      connect()     → INSERT row,            is_active = True
      disconnect()  → UPDATE row,            is_active = False,  last_used_at = now
      reconnect()   → UPDATE existing row,   is_active = True
    """
    __tablename__ = "websocket_connections"

    id:  Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    user_id   = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),nullable=False,index=True,)

    workspace_id  = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"),nullable=False,index=True,)
    chatroom_id  = mapped_column(ForeignKey("chatrooms.id", ondelete="CASCADE"),nullable=False,index=True,)

    is_active:    Mapped[bool]     = mapped_column(Boolean, default=True,  nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=func.now(),onupdate=func.now(),)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=func.now(),)