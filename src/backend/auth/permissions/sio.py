import functools
from typing import Any
from uuid import UUID

from backend.auth.permissions import user_perms
from backend.auth.permissions.model import PermissionSet
from model import SessionLocal


def require_perms(*required_permissions: str):
    """
    Decorator for Socket.IO handlers.

    Resolves workspace_id and channel_id from the event data dict,
    checks permissions, and short-circuits with an error if denied.

    Usage:
        @sio.on("new_message")
        @require_perms("message:send")
        async def new_message(sid, data): ...
    """
    required = None

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(sid: str, data: dict[str, Any]):
            from backend.chat.realtime import sio
            nonlocal required
            if required is None:
                required = PermissionSet.from_permissions(
                    ScopedPermission(p) for p in required_permissions
                )

            user_id = sio.get_session(sid).get("user_id")
            if user_id is None:
                return {"error": "unauthenticated"}

            channel_id = data.get("channel_id")
            workspace_id = data.get("workspace_id")

            with SessionLocal() as db:
                user_permissions = user_perms(
                    workspace_id=UUID(workspace_id) if workspace_id else None,
                    channel_id=UUID(channel_id) if channel_id else None,
                    user_id=user_id,
                    db=db,
                )

            user_permissions = user_permissions.collapse_scope()
            missing = required - user_permissions
            if missing:
                return {"error": f"permission denied: missing {', '.join(str(p) for p in missing)}"}

            return await handler(sid, data)

        return wrapper

    return decorator
