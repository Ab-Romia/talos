import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth.dependencies import UserDep
from auth.model import User
from database import DatabaseDep
from workspace.model import Channel, DMParticipant, Workspace, WorkspaceMember

dms = APIRouter(prefix="/dms", tags=["dms"])


class CreateDMRequest(BaseModel):
    user_id: uuid.UUID


def _dm_key(a: uuid.UUID, b: uuid.UUID) -> str:
    lo, hi = sorted([str(a), str(b)])
    return f"dm:{lo}:{hi}"


def _is_member(db, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    if db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None:
        return True
    ws = db.get(Workspace, workspace_id)
    return ws is not None and ws.owner_id == user_id


def _peer_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name or user.username,
    }


def _serialize_dm(db, channel: Channel, me: uuid.UUID) -> dict:
    peer_id = db.scalar(
        select(DMParticipant.user_id)
        .where(DMParticipant.channel_id == channel.id)
        .where(DMParticipant.user_id != me)
    )
    peer = db.get(User, peer_id) if peer_id else None
    return {
        "id": str(channel.id),
        "is_direct": True,
        "peer": _peer_dict(peer) if peer else None,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


@dms.get("")
async def list_my_dms(workspace_id: uuid.UUID, user: UserDep, db: DatabaseDep):
    """The current user's direct-message conversations in this workspace."""
    channels = db.scalars(
        select(Channel)
        .join(DMParticipant, DMParticipant.channel_id == Channel.id)
        .where(DMParticipant.user_id == user.id)
        .where(Channel.workspace_id == workspace_id)
        .where(Channel.is_direct.is_(True))
        .where(Channel.deleted_at.is_(None))
        .order_by(Channel.created_at)
    ).all()
    return [_serialize_dm(db, c, user.id) for c in channels]


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
        return _serialize_dm(db, existing, user.id)

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
        return _serialize_dm(db, existing, user.id)
    db.refresh(channel)

    # Join both users' LIVE sockets into the new room — rooms are otherwise
    # only joined at connect time, so the peer would miss realtime messages
    # until their next reconnect.
    from chat.realtime import sio
    for uid in (user.id, req.user_id):
        for sid, _ns in sio.manager.get_participants("/", f"user:{uid}"):
            await sio.enter_room(sid, f"channel:{channel.id}")

    return _serialize_dm(db, channel, user.id)
