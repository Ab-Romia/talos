from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


def _key(workspace_id: str, chatroom_id: str) -> str:
    return f"{workspace_id}:{chatroom_id}"


class MessageEventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {}

    async def add(self, workspace_id: str, chatroom_id: str, socket: WebSocket) -> None:
        k = _key(workspace_id, chatroom_id)
        if k not in self._subscribers:
            self._subscribers[k] = set()
        self._subscribers[k].add(socket)

    def remove(self, workspace_id: str, chatroom_id: str, socket: WebSocket) -> None:
        k = _key(workspace_id, chatroom_id)
        s = self._subscribers.get(k)
        if not s:
            return
        s.discard(socket)
        if not s:
            del self._subscribers[k]

    async def broadcast(
        self,
        workspace_id: str,
        chatroom_id: str,
        event: dict[str, Any],
    ) -> None:
        k = _key(workspace_id, chatroom_id)
        conns = list(self._subscribers.get(k, ()))
        if not conns:
            return
        raw = json.dumps(event, default=str)
        for ws in conns:
            try:
                await ws.send_text(raw)
            except (RuntimeError, OSError) as e:
                log.debug("dropping dead websocket: %s", e)
                self._subscribers.get(k, set()).discard(ws)


message_hub = MessageEventHub()
