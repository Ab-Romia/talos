import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from auth.dependencies import UserDep
from auth.model import User
from database import DatabaseDep
from permissions.model import (
    Permission, Role, RolePermission, PermissionScope, system_roles, users_roles,
)
from workspace.model import Workspace, Channel, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# Every permission the app checks anywhere. All must be registered so
# require_perms(...) can *represent* them (otherwise the check raises and 500s),
# even when the permission is only ever held by owners (who bypass the bitfield).
ALL_PERMS = [
    ("workspace", "view"), ("workspace", "edit"), ("workspace", "delete"),
    ("workspace.member", "view"), ("workspace.member", "manage"),
    ("workspace.role", "view"), ("workspace.role", "manage"),
    ("channel", "view"), ("channel", "create"), ("channel", "edit"),
    ("channel", "delete"), ("channel", "manage"),
    ("channel.member", "view_presence"), ("channel.member", "manage"),
    ("channel.message", "send"), ("channel.message", "view_history"),
    ("files", "read"), ("files", "write"), ("files", "create"),
]

# The subset granted to a new workspace's base "everyone" role. Admin
# capabilities (edit/delete/manage) are intentionally NOT here — owners get them
# via the owner bypass, and they can be granted to other roles explicitly.
STANDARD_PERMS = [
    ("workspace", "view"), ("workspace.role", "view"), ("workspace.role", "manage"),
    ("channel", "view"),
    ("channel.message", "send"), ("channel.message", "view_history"),
    ("channel.member", "view_presence"),
    ("files", "read"), ("files", "write"), ("files", "create"),
]
DEFAULT_CHANNELS = ["general", "random"]


def _strip_nonempty(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class CreateWorkspaceRequest(BaseModel):
    name: Annotated[str, AfterValidator(_strip_nonempty)] = Field(min_length=1, max_length=100)
    channels: list[str] | None = Field(default=None, max_length=50)
    members: list[str] | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class CreateChannelRequest(BaseModel):
    name: Annotated[str, AfterValidator(_strip_nonempty)] = Field(min_length=1, max_length=100)


class AddMemberRequest(BaseModel):
    identifier: Annotated[str, AfterValidator(_strip_nonempty)] = Field(min_length=1, max_length=320)


def _serialize(db, ws: Workspace, accessible_channel_ids: set | None = None) -> dict:
    channels = db.scalars(
        select(Channel)
        .where(Channel.workspace_id == ws.id, Channel.deleted_at.is_(None))
        .where(Channel.is_direct.is_(False))
        .order_by(Channel.created_at)
    ).all()
    if accessible_channel_ids is not None:
        channels = [c for c in channels if c.id in accessible_channel_ids]
    return {
        "id": str(ws.id),
        "name": ws.name,
        "description": ws.description,
        "owner_id": str(ws.owner_id),
        "channels": [{"id": str(c.id), "name": c.name} for c in channels],
    }


def _member_dict(user: User, owner_id: uuid.UUID) -> dict:
    from auth.avatars import avatar_url_for
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name or user.username,
        "email": user.primary_email,
        "is_owner": user.id == owner_id,
        "avatar_url": avatar_url_for(user),
    }


def _get_workspace(db, workspace_id: uuid.UUID) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None or ws.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return ws


def _is_member(db, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None


def _require_member(db, ws: Workspace, user: User):
    if ws.owner_id != user.id and not _is_member(db, ws.id, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace")


def _require_owner(ws: Workspace, user: User):
    if ws.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the workspace owner can do this")


def _ensure_standard_perms(db) -> dict:
    """Register every permission the app checks (idempotent). Returns the map."""
    perms = {}
    for resource, action in ALL_PERMS:
        p = db.scalar(select(Permission).where(Permission.resource == resource, Permission.action == action))
        if p is None:
            p = Permission(resource=resource, action=action, allowed_scopes=[PermissionScope.ANY])
            db.add(p)
        perms[(resource, action)] = p
    db.commit()
    return perms


def ensure_permissions_registered():
    """Seed the permission registry at startup so checks never fail to represent."""
    from database import SessionLocal
    with SessionLocal() as db:
        _ensure_standard_perms(db)


def _link_member(db, workspace_id: uuid.UUID, base_role: Role, user: User):
    if not _is_member(db, workspace_id, user.id):
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id))
        db.commit()
    link = db.execute(
        select(users_roles).where(users_roles.c.user_id == user.id, users_roles.c.role_id == base_role.id)
    ).first()
    if not link:
        db.execute(users_roles.insert().values(user_id=user.id, role_id=base_role.id))
        db.commit()


def _default_workspace_description(name: str) -> str:
    return f"{name} — a shared space for your team's channels, conversations and documents."


def provision_workspace(
    db, owner: User, name: str, channels: list[str] | None = None, description: str | None = None
) -> Workspace:
    """Create a workspace with its base role, permissions, owner membership and channels.

    ``channels`` defaults to DEFAULT_CHANNELS; blank names and duplicates are dropped.
    ``description`` falls back to a sensible default so every workspace has one.
    """
    channel_names, seen = [], set()
    for raw in channels or DEFAULT_CHANNELS:
        cleaned = raw.strip().lstrip("#")[:100]
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            channel_names.append(cleaned)
    if not channel_names:
        channel_names = list(DEFAULT_CHANNELS)

    perms = _ensure_standard_perms(db)

    for role in system_roles():
        if db.get(Role, role.id) is None:
            db.add(role)
    db.commit()

    description = (description or "").strip() or _default_workspace_description(name)
    ws = Workspace(name=name, owner_id=owner.id, description=description)
    db.add(ws)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A workspace named “{name}” already exists.")
    db.refresh(ws)

    base_role = db.get(Role, ws.id)
    if base_role is None:
        base_role = Role(id=ws.id, name="everyone", workspace_id=ws.id, priority=0)
        db.add(base_role)
        db.commit()

    _link_member(db, ws.id, base_role, owner)

    for key in STANDARD_PERMS:
        permission = perms.get(key)
        if permission is None:
            continue
        exists = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == base_role.id,
                RolePermission.permission_id == permission.id,
                RolePermission.channel_id.is_(None),
                RolePermission.scope == PermissionScope.ANY,
            )
        )
        if exists is None:
            db.add(RolePermission(role_id=base_role.id, permission_id=permission.id, scope=PermissionScope.ANY))
    db.commit()

    for channel_name in channel_names:
        db.add(Channel(name=channel_name, workspace_id=ws.id))
    db.commit()

    db.refresh(ws)
    return ws


@router.get("")
@router.get("/")
def list_my_workspaces(user: UserDep, db: DatabaseDep):
    """List workspaces the current user owns or is a member of, with their channels."""
    from chat.realtime import _get_accessible_channels

    workspaces = db.scalars(
        select(Workspace)
        .where(Workspace.deleted_at.is_(None))
        .where(
            or_(
                Workspace.owner_id == user.id,
                Workspace.id.in_(
                    select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
                ),
            )
        )
        .order_by(Workspace.created_at)
    ).all()
    accessible = _get_accessible_channels(db, user.id)
    return [_serialize(db, ws, accessible) for ws in workspaces]


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: CreateWorkspaceRequest, user: UserDep, db: DatabaseDep):
    """Create a new workspace owned by the current user, with optional channels and members."""
    ws = provision_workspace(db, user, payload.name.strip(), payload.channels, payload.description)

    skipped = []
    if payload.members:
        base_role = db.get(Role, ws.id)
        for raw in payload.members:
            identifier = raw.strip()
            if not identifier:
                continue
            target = db.scalar(
                select(User).where(
                    User.deleted_at.is_(None),
                    or_(User.primary_email == identifier, User.username == identifier),
                )
            )
            if target is None:
                skipped.append(identifier)
            elif target.id != user.id:
                _link_member(db, ws.id, base_role, target)

    return {**_serialize(db, ws), "skipped_members": skipped}


@router.post("/{workspace_id}/channels", status_code=status.HTTP_201_CREATED)
def create_channel(workspace_id: uuid.UUID, payload: CreateChannelRequest, user: UserDep, db: DatabaseDep):
    """Create a channel in a workspace."""
    ws = _get_workspace(db, workspace_id)
    _require_owner(ws, user)

    name = payload.name.strip()
    dup = db.scalar(
        select(Channel).where(
            Channel.workspace_id == ws.id, Channel.name == name, Channel.deleted_at.is_(None)
        )
    )
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A channel named “{name}” already exists.")

    channel = Channel(name=name, workspace_id=ws.id)
    db.add(channel)
    db.commit()
    db.refresh(channel)

    from chat.sync import notify_workspace
    notify_workspace(db, ws.id, "channels", action="created", name=channel.name)

    return {"id": str(channel.id), "name": channel.name}


@router.get("/{workspace_id}/members")
def list_members(workspace_id: uuid.UUID, user: UserDep, db: DatabaseDep):
    """List the members of a workspace."""
    ws = _get_workspace(db, workspace_id)
    _require_member(db, ws, user)

    members = db.scalars(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == ws.id, User.deleted_at.is_(None))
        .order_by(User.created_at)
    ).all()

    if ws.owner_id not in {m.id for m in members}:
        owner = db.get(User, ws.owner_id)
        if owner is not None:
            members = [owner, *members]

    return [_member_dict(m, ws.owner_id) for m in members]


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(workspace_id: uuid.UUID, payload: AddMemberRequest, user: UserDep, db: DatabaseDep):
    """Add a user to a workspace by email or username."""
    ws = _get_workspace(db, workspace_id)
    _require_owner(ws, user)

    identifier = payload.identifier.strip()
    target = db.scalar(
        select(User).where(
            User.deleted_at.is_(None),
            or_(User.primary_email == identifier, User.username == identifier),
        )
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No user found with that email or username.")

    if _is_member(db, ws.id, target.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member.")

    base_role = db.get(Role, ws.id)
    _link_member(db, ws.id, base_role, target)

    from chat.sync import notify_workspace
    notify_workspace(db, ws.id, "workspaces", action="added", name=ws.name, targets=[target.id])
    notify_workspace(db, ws.id, "members")

    return _member_dict(target, ws.owner_id)


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(workspace_id: uuid.UUID, member_id: uuid.UUID, user: UserDep, db: DatabaseDep):
    """Remove a member from a workspace."""
    ws = _get_workspace(db, workspace_id)
    _require_owner(ws, user)

    if member_id == ws.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The owner cannot be removed.")

    membership = db.get(WorkspaceMember, {"workspace_id": ws.id, "user_id": member_id})
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    db.delete(membership)
    db.execute(
        users_roles.delete().where(
            users_roles.c.user_id == member_id,
            users_roles.c.role_id.in_(select(Role.id).where(Role.workspace_id == ws.id)),
        )
    )
    db.commit()

    from chat.sync import notify_workspace
    notify_workspace(db, ws.id, "workspaces", action="removed", name=ws.name, targets=[member_id])
    notify_workspace(db, ws.id, "members")
