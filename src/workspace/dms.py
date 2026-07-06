import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth.dependencies import UserDep
from auth.model import User
from database import DatabaseDep
from workspace.model import Channel, DMParticipant, Workspace, WorkspaceMember

dms = APIRouter(prefix="/dms", tags=["dms"])


class CreateDMRequest(BaseModel):
    user_id: uuid.UUID


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class AddGroupMembersRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1)


def _dm_key(a: uuid.UUID, b: uuid.UUID) -> str:
    lo, hi = sorted([str(a), str(b)])
    return f"dm:{lo}:{hi}"


def _clean_group_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Please enter a name for the group.")
    return name[:80]


def _is_member(db, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    if db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None:
        return True
    ws = db.get(Workspace, workspace_id)
    return ws is not None and ws.owner_id == user_id


def _participants(db, channel_id: uuid.UUID) -> list[User]:
    return list(db.scalars(
        select(User)
        .join(DMParticipant, DMParticipant.user_id == User.id)
        .where(DMParticipant.channel_id == channel_id)
        .order_by(User.name, User.username)
    ))


def _peer_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name or user.username,
    }


def _serialize_conversation(db, channel: Channel, me: uuid.UUID) -> dict:
    """A DM or group conversation, shaped for the sidebar. Groups carry a member
    list and a display name; DMs carry the single other participant as `peer`."""
    members = _participants(db, channel.id)
    base = {
        "id": str(channel.id),
        "is_direct": True,
        "is_group": bool(channel.is_group),
        "members": [_peer_dict(u) for u in members],
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }
    if channel.is_group:
        base["name"] = channel.description or "Group"
        base["peer"] = None
    else:
        peer = next((u for u in members if u.id != me), None)
        base["peer"] = _peer_dict(peer) if peer else None
    return base


async def _wire_new_channel(db, channel_id: uuid.UUID, workspace_id: uuid.UUID,
                            member_ids: list[uuid.UUID]) -> None:
    """Join every member's live sockets into the new room and tell them to
    refresh their conversation list — rooms are otherwise only joined at
    connect time, so members would miss realtime messages until reconnecting."""
    from chat.realtime import sio
    for uid in member_ids:
        for sid, _ns in sio.manager.get_participants("/", f"user:{uid}"):
            await sio.enter_room(sid, f"channel:{channel_id}")
        await sio.emit("workspace_sync",
                       {"resource": "dms", "workspace_id": str(workspace_id)},
                       room=f"user:{uid}")


@dms.get("")
async def list_my_dms(workspace_id: uuid.UUID, user: UserDep, db: DatabaseDep):
    """The current user's direct-message and group conversations in this workspace."""
    channels = db.scalars(
        select(Channel)
        .join(DMParticipant, DMParticipant.channel_id == Channel.id)
        .where(DMParticipant.user_id == user.id)
        .where(Channel.workspace_id == workspace_id)
        .where(Channel.is_direct.is_(True))
        .where(Channel.deleted_at.is_(None))
        .order_by(Channel.created_at)
    ).all()
    return [_serialize_conversation(db, c, user.id) for c in channels]


@dms.post("", status_code=status.HTTP_201_CREATED)
async def open_dm(workspace_id: uuid.UUID, req: CreateDMRequest, user: UserDep, db: DatabaseDep):
    """Create (or return the existing) DM between the caller and another member."""
    if req.user_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot message yourself.")

    target = db.get(User, req.user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not _is_member(db, workspace_id, req.user_id):
        raise HTTPException(status_code=400, detail="That user is not a member of this workspace.")

    key = _dm_key(user.id, req.user_id)
    existing = db.scalar(
        select(Channel).where(
            Channel.workspace_id == workspace_id,
            Channel.name == key,
            Channel.is_direct.is_(True),
            Channel.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return _serialize_conversation(db, existing, user.id)

    channel = Channel(
        name=key,
        workspace_id=workspace_id,
        is_public=False,
        is_direct=True,
        dm_key=key,
    )
    db.add(channel)
    try:
        db.flush()
        db.add(DMParticipant(channel_id=channel.id, user_id=user.id))
        db.add(DMParticipant(channel_id=channel.id, user_id=req.user_id))
        db.commit()
    except IntegrityError:
        # Lost a create race — the unique (name, workspace_id) caught it.
        db.rollback()
        existing = db.scalar(
            select(Channel).where(
                Channel.workspace_id == workspace_id,
                Channel.name == key,
                Channel.is_direct.is_(True),
            )
        )
        if existing is None:
            raise
        return _serialize_conversation(db, existing, user.id)
    db.refresh(channel)

    await _wire_new_channel(db, channel.id, workspace_id, [user.id, req.user_id])

    return _serialize_conversation(db, channel, user.id)


@dms.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(workspace_id: uuid.UUID, req: CreateGroupRequest, user: UserDep, db: DatabaseDep):
    """Create a group conversation. The caller plus every listed member becomes a
    participant; all participants can read and send. Access is participant-only."""
    name = _clean_group_name(req.name)

    member_ids = {user.id}
    for uid in req.user_ids:
        if uid == user.id:
            continue
        target = db.get(User, uid)
        if target is None or target.deleted_at is not None:
            raise HTTPException(status_code=404, detail="One of the selected people could not be found.")
        if not _is_member(db, workspace_id, uid):
            raise HTTPException(status_code=400, detail="You can only add members of this workspace.")
        member_ids.add(uid)

    if len(member_ids) < 2:
        raise HTTPException(status_code=400, detail="Add at least one other person to start a group.")

    channel = Channel(
        name=f"group:{uuid.uuid7().hex}",
        description=name,
        workspace_id=workspace_id,
        is_public=False,
        is_direct=True,
        is_group=True,
    )
    db.add(channel)
    db.flush()
    for uid in member_ids:
        db.add(DMParticipant(channel_id=channel.id, user_id=uid))
    db.commit()
    db.refresh(channel)

    await _wire_new_channel(db, channel.id, workspace_id, list(member_ids))

    return _serialize_conversation(db, channel, user.id)


def _load_group(db, workspace_id: uuid.UUID, channel_id: uuid.UUID, user_id: uuid.UUID) -> Channel:
    channel = db.get(Channel, channel_id)
    if (channel is None or channel.deleted_at is not None
            or channel.workspace_id != workspace_id or not channel.is_group):
        raise HTTPException(status_code=404, detail="Group not found.")
    if db.get(DMParticipant, {"channel_id": channel_id, "user_id": user_id}) is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group.")
    return channel


@dms.post("/groups/{channel_id}/members")
async def add_group_members(workspace_id: uuid.UUID, channel_id: uuid.UUID,
                            req: AddGroupMembersRequest, user: UserDep, db: DatabaseDep):
    """Add one or more workspace members to a group the caller belongs to."""
    channel = _load_group(db, workspace_id, channel_id, user.id)

    added: list[uuid.UUID] = []
    for uid in req.user_ids:
        target = db.get(User, uid)
        if target is None or target.deleted_at is not None:
            raise HTTPException(status_code=404, detail="One of the selected people could not be found.")
        if not _is_member(db, workspace_id, uid):
            raise HTTPException(status_code=400, detail="You can only add members of this workspace.")
        if db.get(DMParticipant, {"channel_id": channel_id, "user_id": uid}) is not None:
            continue
        db.add(DMParticipant(channel_id=channel_id, user_id=uid))
        added.append(uid)
    db.commit()

    if added:
        # Existing members refresh too so the new roster shows up everywhere.
        everyone = [p.id for p in _participants(db, channel_id)]
        await _wire_new_channel(db, channel_id, workspace_id, everyone)

    return _serialize_conversation(db, channel, user.id)


@dms.delete("/groups/{channel_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(workspace_id: uuid.UUID, channel_id: uuid.UUID, user: UserDep, db: DatabaseDep):
    """Leave a group. When the last member leaves, the group is soft-deleted."""
    channel = _load_group(db, workspace_id, channel_id, user.id)

    db.delete(db.get(DMParticipant, {"channel_id": channel_id, "user_id": user.id}))
    db.commit()

    remaining = [p.id for p in _participants(db, channel_id)]
    if not remaining:
        from utils.datetime import utcnow
        channel.deleted_at = utcnow()
        db.commit()

    from chat.realtime import sio
    for sid, _ns in sio.manager.get_participants("/", f"user:{user.id}"):
        await sio.leave_room(sid, f"channel:{channel_id}")
    for uid in remaining + [user.id]:
        await sio.emit("workspace_sync",
                       {"resource": "dms", "workspace_id": str(workspace_id)},
                       room=f"user:{uid}")
