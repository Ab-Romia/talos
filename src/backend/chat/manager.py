"""
ChannelConnectionManager
────────────────────────
Tracks every live WebSocket connection per user.

Internal structure
──────────────────
    _connections: { user_id: WebSocket }

Key guarantees
──────────────
  • One connection per user — reconnecting replaces the old socket.
  • Delivery is stateless: caller provides list of recipient user_ids.
  • Database queries (not subscriptions) determine channel membership.
  • All public coroutines are safe to call from any async context.
"""

from typing import Optional
from uuid import UUID

from fastapi import WebSocket


class ChannelConnectionManager:

    def __init__(self) -> None:
        # user_id → WebSocket
        self._connections: dict[UUID, WebSocket] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, user_id: UUID) -> None:
        """Accept the socket and register it under user_id."""
        await websocket.accept()
        # Disconnect any existing connection for this user
        if user_id in self._connections:
            # Close old connection
            try:
                await self._connections[user_id].close()
            except:
                pass
        self._connections[user_id] = websocket

    def disconnect(self, user_id: UUID) -> None:
        """Remove the connection."""
        if user_id in self._connections:
            del self._connections[user_id]
            # TODO: session id instead if user_id

    # ── presence ──────────────────────────────────────────────────────────────

    def get_online_users(self, user_ids: list[UUID]) -> list[UUID]:
        """Filter a list of user_ids to only those with active connections."""
        return [uid for uid in user_ids if uid in self._connections]

    # ── delivery ──────────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: UUID, payload: dict) -> bool:
        """
        Push a JSON payload directly to one user.
        Returns True if the socket was alive, False otherwise.
        """
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            self.disconnect(user_id)
            return False

    async def broadcast(
            self,
            user_ids: list[UUID],
            payload: dict,
            exclude_user: Optional[UUID] = None,
    ) -> tuple[list[UUID], list[UUID]]:
        """
        Push a JSON payload to specified users.

        Args:
            user_ids:     List of user_ids to send to.
            payload:      JSON-serialisable dict.
            exclude_user: Optional user_id to skip (usually the sender).

        Returns:
            Tuple of (delivered_users, offline_users).
        """
        delivered: list[UUID] = []
        offline: list[UUID] = []

        for uid in user_ids:
            if uid == exclude_user:
                continue
            if await self.send_to_user(uid, payload):
                delivered.append(uid)
            else:
                offline.append(uid)

        return delivered, offline


# Module-level singleton
manager = ChannelConnectionManager()
