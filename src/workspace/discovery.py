import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
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

STANDARD_PERMS = [
    ("workspace", "view"), ("workspace.role", "view"), ("workspace.role", "manage"),
    ("channel", "view"),
    ("channel.message", "view_history"), ("channel.message", "send"),
    ("channel.member", "view_presence"),
    ("files", "read"), ("files", "write"), ("files", "create"),
]
DEFAULT_CHANNELS = ["general", "random"]


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CreateChannelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class AddMemberRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)


def _serialize(db, ws: Workspace) -> dict:
    channels = db.scalars(
        select(Channel)
        .where(Channel.workspace_id == ws.id, Channel.deleted_at.is_(None))
        .order_by(Channel.created_at)
    ).all()
    return {
        "id": str(ws.id),
        "name": ws.name,
        "owner_id": str(ws.owner_id),
        "channels": [{"id": str(c.id), "name": c.name} for c in channels],
    }


def _member_dict(user: User, owner_id: uuid.UUID) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name or user.username,
        "email": user.primary_email,
        "is_owner": user.id == owner_id,
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
    perms = {}
    for resource, action in STANDARD_PERMS:
        p = db.scalar(select(Permission).where(Permission.resource == resource, Permission.action == action))
        if p is None:
            p = Permission(resource=resource, action=action, allowed_scopes=[PermissionScope.ANY])
            db.add(p)
        perms[(resource, action)] = p
    db.commit()
    return perms


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


def provision_workspace(db, owner: User, name: str) -> Workspace:
    """Create a workspace with its base role, permissions, owner membership and default channels."""
    perms = _ensure_standard_perms(db)

    for role in system_roles():
        if db.get(Role, role.id) is None:
            db.add(role)
    db.commit()

    ws = Workspace(name=name, owner_id=owner.id)
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

    for permission in perms.values():
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

    for channel_name in DEFAULT_CHANNELS:
        db.add(Channel(name=channel_name, workspace_id=ws.id))
    db.commit()

    db.refresh(ws)
    return ws


@router.get("")
@router.get("/")
def list_my_workspaces(user: UserDep, db: DatabaseDep):
    """List workspaces the current user owns or is a member of, with their channels."""
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
    return [_serialize(db, ws) for ws in workspaces]


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: CreateWorkspaceRequest, user: UserDep, db: DatabaseDep):
    """Create a new workspace owned by the current user."""
    ws = provision_workspace(db, user, payload.name.strip())
    return _serialize(db, ws)


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
            users_roles.c.user_id == member_id, users_roles.c.role_id == ws.id
        )
    )
    db.commit()
