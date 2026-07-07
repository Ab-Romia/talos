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
from database import SessionLocal
from utils.logger import get_logger
from workspace.model import WorkspaceMember, Channel
from .model import MessageCreateSchema

mgr = socketio.AsyncRedisManager(cfg().redis.url, channel="sio#")
sio = socketio.AsyncServer(
    client_manager=mgr,
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
    from permissions import require_perms as require_perms_dep, user_perms
    from auth.utils import errors

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
            return {"error": "Something went wrong. Please try again."}

    return wrapper


@sio.event
@sio_exc
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> bool:
    from auth import active_user
    from auth.utils.session import unverified_session

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
@require_perms("channel.message:send", "channel:view")
async def message(sid: str, data: dict[str, Any]):
    from chat import store_message

    # MessageCreateSchema coerces plain-string content into a ProseMirror doc
    # and validates rich content against chat_schema (rich-msg contract).
    incoming = MessageCreateSchema(**data)
    sess = await sio.get_session(sid)

    message = await store_message(
        channel_id=incoming.channel_id,
        user_id=sess["user_id"],
        content=incoming.content,
        reply_to_id=incoming.reply_to_id,
        attachment_ids=incoming.attachment_ids,
    )

    await sio.send(
        message.model_dump(mode="json"),
        room=f"channel:{message.channel_id}",
        skip_sid=sid,
    )

    from chat.ai import maybe_ai_reply
    await maybe_ai_reply(message.channel_id, message.content, sess["user_id"])

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

    from rag.message_text import doc_text
    from chat.model import extract_mentioned_user_ids_from_raw
    asyncio.create_task(_notify_channel_members(
        channel_id=message.channel_id,
        sender_id=sess["user_id"],
        content=doc_text(message.content),
        mentioned_user_ids=extract_mentioned_user_ids_from_raw(message.content),
        message_id=message.id,
    ))

    return "OK", {  # ack
        "delivered_to": delivered_to,
    },


async def _notify_channel_members(channel_id: UUID, sender_id: UUID, content: str,
                                  mentioned_user_ids: list[UUID] | None = None,
                                  message_id: UUID | None = None):
    log = get_logger(__name__)
    try:
        with SessionLocal() as db:
            from auth.model import User
            from notifications.service import push_notification
            from notifications.model import NotificationTag

            channel = db.get(Channel, channel_id)
            if not channel:
                log.warning("_notify: channel %s not found", channel_id)
                return

            members = _get_channel_members(db, channel_id)
            log.info(f"_notify: channel={channel_id} sender={sender_id} members={members}")
            mentioned = {uid for uid in (mentioned_user_ids or []) if uid in members and uid != sender_id}
            recipients = [uid for uid in members if uid != sender_id and uid not in mentioned]
            body = content[:200] if content else ""

            sender = db.get(User, sender_id)
            sender_name = (sender.name or sender.username) if sender else "Someone"

            group_name = channel.description or "Group"
            if mentioned:
                if channel.is_group:
                    where = f"{sender_name} mentioned you in {group_name}"
                elif channel.is_direct:
                    where = sender_name
                else:
                    where = f"{sender_name} mentioned you in #{channel.name}"
                await push_notification(
                    db=db,
                    user_ids=list(mentioned),
                    title=where,
                    body=body,
                    data={
                        "channel_id": str(channel_id),
                        "workspace_id": str(channel.workspace_id),
                        "mention": True,
                        "direct": channel.is_direct,
                        **({"message_id": str(message_id)} if message_id else {}),
                    },
                    tags=[NotificationTag.SOCIAL],
                )

            if recipients:
                if channel.is_group:
                    title = f"{sender_name} · {group_name}"
                elif channel.is_direct:
                    title = sender_name
                else:
                    title = f"#{channel.name}"
                await push_notification(
                    db=db,
                    user_ids=recipients,
                    title=title,
                    body=body,
                    data={
                        "channel_id": str(channel_id),
                        "workspace_id": str(channel.workspace_id),
                        "direct": channel.is_direct,
                        **({"message_id": str(message_id)} if message_id else {}),
                    },
                    tags=[NotificationTag.SOCIAL],
                )
                log.info(f"_notify: push_notification sent to {len(recipients)} users")
            else:
                log.info("_notify: no recipients, skipping")
    except Exception:
        log.exception("Failed to send channel notifications")


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
    from permissions import PermissionSet, ScopedPermission
    with SessionLocal() as db:
        return PermissionSet.from_permissions(ScopedPermission.from_str("channel:view"), db).bitstring


def _get_accessible_channels(db: orm.Session, user_id: UUID) -> set[UUID]:
    """ Channels visible to a user"""
    from permissions.model import Role, ChannelRoleOverride
    from workspace.model import Workspace, DMParticipant

    # Owners can see all channels in their workspaces (bypass bitfield check) —
    # EXCEPT direct messages, which only their two participants may see.
    owned = set(db.scalars(
        select(Channel.id)
        .join(Workspace, Workspace.id == Channel.workspace_id)
        .where(Workspace.owner_id == user_id)
        .where(Channel.deleted_at.is_(None))
        .where(Channel.is_direct.is_(False))
    ))

    zero = BitString.from_int(0, cfg().auth.permission_bitstring_length)
    override_deny = func.coalesce(ChannelRoleOverride.deny_mask, zero)
    override_allow = func.coalesce(ChannelRoleOverride.allow_mask, zero)

    # Select channel ids where the user has channel:view permission through any of their roles, accounting for overrides.
    # TODO: make into a view (wsid, chid, uid) -> perms
    rows = db.scalars(
        select(Channel.id)
        .join(Role, Role.workspace_id == Channel.workspace_id)
        .join(ChannelRoleOverride, (ChannelRoleOverride.role_id == Role.id) & (ChannelRoleOverride.channel_id == Channel.id), isouter=True)
        .where(Role.users.any(id=user_id))
        .where(Channel.deleted_at.is_(None))
        .where(Channel.is_direct.is_(False))
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

    # Direct messages: membership only.
    dms = set(db.scalars(
        select(DMParticipant.channel_id)
        .join(Channel, Channel.id == DMParticipant.channel_id)
        .where(DMParticipant.user_id == user_id)
        .where(Channel.deleted_at.is_(None))
    ))

    return owned | set(rows) | dms


def _get_channel_members(db: Session, channel_id: UUID) -> set[UUID]:
    """All workspace members who can view this channel (owners always included).
    For direct messages: exactly the two participants."""
    from workspace.model import Workspace, DMParticipant

    channel = db.get(Channel, channel_id)
    if not channel:
        return set()

    if channel.is_direct:
        return set(db.scalars(
            select(DMParticipant.user_id).where(DMParticipant.channel_id == channel_id)
        ))

    owner_id = db.scalar(
        select(Workspace.owner_id).where(Workspace.id == channel.workspace_id)
    )

    members = db.scalars(
        select(WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == channel.workspace_id)
    )

    def has_access(user_id: UUID) -> bool:
        if user_id == owner_id:
            return True
        from permissions import user_perms, ScopedPermission
        return ScopedPermission.from_str("channel:view") in user_perms(
            workspace_id=None,
            channel_id=channel_id,
            user_id=user_id,
            db=db,
        ).iter(db)

    return set(filter(has_access, members))
