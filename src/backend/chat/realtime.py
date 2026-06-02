import asyncio
import functools
from http.cookies import SimpleCookie
from typing import Any
from uuid import UUID

import socketio
from sqlalchemy import select, orm, func
from sqlalchemy.dialects.postgresql import BitString
from sqlalchemy.orm import Session

from config import cfg
from model import SessionLocal
from utils.logger import get_logger
from .model import MessageSchema
from ..workspace.model import WorkspaceMember, Channel

sio = socketio.AsyncServer(
    async_mode="asgi",
    logger=False,
    engineio_logger=False,
)


# TODO: track online status in redis
def is_user_online(user_id: UUID) -> bool:
    participants = sio.manager.get_participants("/", f"user:{user_id}")
    return any(True for _ in participants)


def get_channel_online(channel_id: UUID, db: Session) -> list[UUID]:
    """
    Online members of a channel: DB membership intersected with Socket.IO room state.
    Used by both presence events and the REST /online endpoint.
    """
    members = _get_channel_members(db, channel_id)
    return [uid for uid in members if is_user_online(uid)]


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
    from ..auth.permissions import require_perms as require_perms_dep, user_perms
    from ..auth.utils import errors

    checker = require_perms_dep(*required_permissions)

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(sid: str, data: dict[str, Any]):
            try:
                workspace_id = data.get("workspace_id")
                if not isinstance(workspace_id, UUID) and workspace_id is not None:
                    workspace_id = UUID(str(workspace_id))

                channel_id = data.get("channel_id")
                if not isinstance(channel_id, UUID) and channel_id is not None:
                    channel_id = UUID(str(channel_id))

                with SessionLocal() as db:
                    user_permissions = user_perms(
                        user_id=(await sio.get_session(sid)).get("user_id"),
                        channel_id=channel_id,
                        workspace_id=workspace_id,
                        db=db,
                    )
                checker(user_permissions, False, db)
                return await handler(sid, data)
            except errors.Forbidden as e:
                return {"error": e.detail}

        return wrapper

    return decorator


def sio_exc(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            get_logger(__name__).exception("Error in Socket.IO handler", exc_info=exc)
            return {"error": str(exc)}

    return wrapper


@sio.event
@sio_exc
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> bool:
    from ..auth import active_user
    from ..auth.utils.session import unverified_session

    token = _extract_token(environ, auth)
    if not token:
        return False

    with SessionLocal() as db:
        session = next(unverified_session(auth_token=token))
        user = active_user(session=session, db=db)
        channel_ids = _get_accessible_channels(db, user.id)

    # Check first_connection before entering the user room
    first_connection = is_user_online(user.id) is False

    await sio.save_session(sid, {"session_id": session.jti, "user_id": user.id})
    await sio.enter_room(sid, f"user:{user.id}")  # personal room for tracking online status
    for channel_id in channel_ids:
        await sio.enter_room(sid, f"channel:{channel_id}")

    if first_connection and len(channel_ids) > 0:
        await sio.emit(
            "user_presence",
            {
                "status": "user_online",
                "user_id": str(user.id),
            },
            room=[f"channel:{channel_id}" for channel_id in channel_ids]
        )

    return True


@sio.event
async def disconnect(sid: str, _) -> None:
    sess = await sio.get_session(sid)
    user_id = sess.get("user_id")

    # The socket is still registered in rooms during this event, so
    # a count of 1 means this is the last connection.
    last_connection = len(list(sio.manager.get_participants("/", f"user:{user_id}"))) == 1
    rooms = [room for room in sio.rooms(sid) if room.startswith("channel:")]

    if last_connection and len(rooms) > 0:
        await sio.emit(
            "user_presence",
            {
                "status": "user_offline",
                "user_id": str(user_id),
            },
            room=rooms,  # crashes if room is empty
        )


@sio.event
@sio_exc
@require_perms("message:send", "channel:view")
async def message(sid: str, data: dict[str, Any]):
    from backend.chat import store_message

    incoming = MessageSchema(**data)
    sess = await sio.get_session(sid)

    message = await store_message(
        channel_id=incoming.channel_id,
        user_id=sess["user_id"],
        content=incoming.content,
    )

    await sio.send(
        message.model_dump(mode="json"),
        room=f"channel:{message.channel_id}",
        skip_sid=sid,
    )

    # Concurrently fetch sessions of all participants to get their user_ids for the ack response.
    participants = sio.manager.get_participants("/", f"channel:{message.channel_id}")
    sessions = await asyncio.gather(
        *(sio.get_session(sid, ns) for sid, ns in participants),
        return_exceptions=True,  # Session may have been disconnected, ignore those errors
    )

    delivered_to = [
        sess.get("user_id", None)  # type: ignore
        for sess in sessions
        if not isinstance(sess, Exception)
    ]

    return "OK", {  # ack
        "delivered_to": delivered_to,
    },


@sio.event
@sio_exc
@require_perms("channel:view")
async def read_receipt(sid: str, data: dict[str, Any]):
    from .storage import get_storage

    message = await get_storage().get_by_id(data["message_id"])
    if message is None:
        return {"error": "Message not found"}

    await sio.emit(
        "read_receipt",
        {
            "channel_id": str(data["channel_id"]),
            "message_id": str(data["message_id"]),
            "reader_id": str((await sio.get_session(sid)).get("user_id")),
        },
        room=f"channel:{data['channel_id']}",
        skip_sid=sid,
    )
    return True


def _extract_token(environ: dict[str, Any], auth: Any) -> str | None:
    if isinstance(auth, dict):
        for key in ("token", "access_token", "session_token"):
            value = auth.get(key)
            if value:
                return str(value)
    elif isinstance(auth, str) and auth:
        return auth

    auth_header = environ.get("HTTP_AUTHORIZATION")
    if isinstance(auth_header, str) and auth_header:
        return auth_header.removeprefix("Bearer").removeprefix("bearer").strip() or None

    raw_cookie = environ.get("HTTP_COOKIE")
    if not raw_cookie:
        return None

    cookie = SimpleCookie()
    cookie.load(str(raw_cookie))
    morsel = cookie.get(cfg().auth.session_cookie_key)
    if morsel is None:
        return None
    return morsel.value or None


@functools.cache
def _channel_perms():
    from ..auth.permissions import PermissionSet, ScopedPermission
    with SessionLocal() as db:
        return PermissionSet.from_permissions(ScopedPermission.from_str("channel:view"), db).bitstring


def _get_accessible_channels(db: orm.Session, user_id: UUID) -> set[UUID]:
    """ Channels visible to a user"""
    from ..auth.permissions.model import Role, ChannelRoleOverride

    zero = BitString.from_int(0, cfg().auth.permission_bitstring_length)
    override_deny = func.coalesce(ChannelRoleOverride.deny_mask, zero)
    override_allow = func.coalesce(ChannelRoleOverride.allow_mask, zero)

    # Select channel ids where the user has channel:view permission through any of their roles, accounting for overrides.
    # TODO: make into a view (wsid, chid, uid) -> perms
    rows = db.scalars(
        select(Channel.id)
        .join(Role, Role.workspace_id == Channel.workspace_id)
        .join(ChannelRoleOverride, ChannelRoleOverride.role_id == Role.id, isouter=True)
        .where(Role.users.any(id=user_id))
        .where(Channel.deleted_at.is_(None))
        .having(  # = (role & ~override.deny | override.allow) & channel_view_perm_mask > 0
            func.bit_or(
                Role.allow_mask
                .bitwise_and(override_deny.bitwise_not())
                .bitwise_or(override_allow)
            ).bitwise_and(_channel_perms())
            != zero
        )
        .group_by(Channel.id)
    )
    return set(rows)


# TODO:
def _get_channel_members(db: Session, channel_id: UUID) -> set[UUID]:
    """All workspace members who share the workspace this channel belongs to."""

    members = db.scalars(
        select(WorkspaceMember.user_id)
        .join(Channel, Channel.workspace_id == WorkspaceMember.workspace_id)
        .where(Channel.id == channel_id)
        .where(Channel.deleted_at.is_(None))
    )

    def has_access(user_id: UUID) -> bool:
        # noinspection PyUnresolvedReferences
        from backend.auth.permissions import user_perms, ScopedPermission

        return ScopedPermission.from_str("channel:view") in user_perms(
            workspace_id=None,
            channel_id=channel_id,
            user_id=user_id,
            db=db,
        ).iter(db)

    return set(filter(has_access, members))
