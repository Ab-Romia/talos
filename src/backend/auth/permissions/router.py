import uuid
from itertools import chain, repeat
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status, Depends, Body
from psycopg import IntegrityError
from pydantic import BaseModel
from sqlalchemy import select, exc, and_
from starlette.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from backend.auth.model import User
from backend.auth.permissions.core import require_perms, UserPermissionsDep, PermissionRegistryDep
from backend.auth.permissions.model import Role, RolePermission, ChannelRoleOverride, PermissionScope
from backend.auth.permissions.registry import PermissionSet, ScopedPermission
from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from model.messaging import Channel, Workspace

workspace = APIRouter(prefix="/workspaces/{workspace_id}", tags=["permissions"])
channel = APIRouter(prefix="/channels/{channel_id}", tags=["permissions"])

WorkspaceID = uuid.UUID  # TODO: move to common types
RoleID = uuid.UUID  # TODO: move to common types


# TODO: add special role handling (everyone, admin, workspace_owner)


class PermissionResp(BaseModel):
    resource: str
    action: str
    scope: str
    is_deny: bool


class RoleResp(BaseModel):
    id: uuid.UUID
    name: str
    priority: int
    description: str | None = None
    permissions: list[PermissionResp] | None = None
    users: list[uuid.UUID] | None = None

    @classmethod
    def from_attributes(cls, role: Role, include_permissions: bool = False, include_users: bool = False) -> "RoleResp":
        perms = None
        if include_permissions:
            perms = []
            for rp in getattr(role, "permissions", []) or []:
                perm = rp.permission
                # permission may be None if invalid relation
                if perm is None:
                    continue
                perms.append(PermissionResp(
                    resource=perm.resource,
                    action=perm.action,
                    scope=str(rp.scope),
                    is_deny=bool(rp.is_deny),
                ))

        users = None
        if include_users:
            users = [u.id for u in getattr(role, "users", []) or []]

        return cls(
            id=role.id,
            name=role.name,
            priority=role.priority,
            description=role.description,
            permissions=perms,
            users=users,
        )


def get_role(db: DatabaseDep, workspace_id: WorkspaceID, role_id: RoleID) -> Role:
    role = db.scalar(
        select(Role)
        .where(Role.id == role_id,
               Role.workspace_id == workspace_id)
    )

    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    return role


@workspace.get(
    "/roles",
    dependencies=[Depends(require_perms("role:view"))],
    response_model=list[RoleResp]
)
def list_workspace_roles(workspace_id: WorkspaceID, db: DatabaseDep):
    """List all roles for the workspace."""
    roles = db.scalars(select(Role).where(Role.workspace_id == workspace_id)).all()
    return [RoleResp.from_attributes(r) for r in roles]


@workspace.post(
    "/roles",
    dependencies=[Depends(require_perms("role:create:workspace"))],
    response_model=RoleResp,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_role(
        workspace_id: WorkspaceID,
        name: Annotated[str, Form()],
        priority: Annotated[int, Form(ge=0)],
        db: DatabaseDep,
        description: Annotated[str | None, Form()] = None,
):
    """
    Creates a new empty role with the specified name and priority.
    The role will have no permissions and no users assigned by default.

    :param workspace_id: The ID of the workspace to create the role in.
    :param name: The name of the role.
    :param priority: The priority of the role, which determines its order in the UI and its precedence.
     The priority given is not guaranteed to be the final stored priority.
    :param description: An optional description of the role.
    :param db:
     """

    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    role = Role(
        name=name,
        description=description,
    )

    try:
        workspace.roles.insert(priority, role)
        db.commit()
    except exc.DBAPIError as e:
        db.rollback()
        if isinstance(e.orig, IntegrityError):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Role name must be unique within the workspace")

        # TODO: More specific error handling
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create role")

    return RoleResp.from_attributes(role)


@workspace.get(
    "/roles/{role_id}",
    dependencies=[Depends(require_perms("role:view:workspace"))],
    response_model=RoleResp,
)
def get_workspace_role(workspace_id: WorkspaceID, role_id: RoleID, db: DatabaseDep):
    """Returns the details of the specified role, including its permissions and assigned users."""
    role = get_role(db, workspace_id, role_id)
    return RoleResp.from_attributes(role, include_permissions=True, include_users=True)


@workspace.put(
    "/roles/{role_id}",
    dependencies=[Depends(require_perms("role:edit:workspace"))],
    response_model=RoleResp,
)
def update_workspace_role_metadata(
        workspace_id: WorkspaceID,
        role_id: RoleID,
        db: DatabaseDep,
        name: Annotated[str | None, Form()] = None,
        priority: Annotated[int | None, Form(ge=0)] = None,
        description: Annotated[str | None, Form()] = None,
):
    """
    Updates the specified role's metadata (name, priority, description).
    This endpoint does not modify permissions and user assignments.
    """
    role = get_role(db, workspace_id, role_id)

    if name is not None:
        role.name = name

    if description is not None:
        role.description = description

    if priority is not None and priority != role.priority:
        # Update priority and reorder roles accordingly
        workspace = db.get(Workspace, workspace_id)
        workspace.roles.remove(role)
        workspace.roles.insert(priority, role)

    db.commit()
    db.refresh(role)
    return RoleResp.from_attributes(role)


@workspace.put(
    "/roles/{role_id}/permissions",
    dependencies=[Depends(require_perms("role:edit:workspace"))],
    response_model=RoleResp,
)
def update_workspace_role_permissions(
        workspace_id: WorkspaceID,
        role_id: RoleID,
        permissions: Annotated[list[ScopedPermission], Body()],
        user_permissions: UserPermissionsDep,  # noqa
        session: SessionDep,  # noqa
        permission_registry: PermissionRegistryDep,  # noqa
        db: DatabaseDep,  # noqa
):
    """
    Updates the specified role's permissions and user assignments.
    Permissions not included in the request will be revoked.

    :param workspace_id: The ID of the workspace the role belongs to.
    :param role_id: The ID of the role to update.
    :param permissions: List of permissions to grant with this role (as strings "resource:action:scope").
         Unspecified permissions will be revoked.
         Note: Users can only grant permissions they themselves have.
    """
    role = get_role(db, workspace_id, role_id)
    request_permissions = PermissionSet.from_permissions(permissions)

    missing = request_permissions - user_permissions

    if not missing.empty():
        raise errors.Forbidden(
            missing,
            detail="To grant or revoke a permission, you must have that permission yourself."
        )

    new_permissions = (
        (permission_registry.db_permission(p.resource, p.action, p.scope), p.scope)
        for p in request_permissions
    )

    role.permissions.clear()
    role.permissions.extend([
        RolePermission(
            permission_id=p.id,
            scope=scope,
        ) for p, scope in new_permissions
        if p is not None  # silently ignore invalid permissions
    ])
    db.commit()

    return RoleResp.from_attributes(role, include_permissions=True)


@workspace.put(
    "/roles/{role_id}/members",
    dependencies=[Depends(require_perms("role:edit:workspace"))],
    response_model=RoleResp,
)
def update_workspace_role_members(
        workspace_id: WorkspaceID,
        role_id: RoleID,
        member_ids: Annotated[list[uuid.UUID], Form()],
        user_permissions: UserPermissionsDep,  # noqa
        session: SessionDep,  # noqa
        db: DatabaseDep,  # noqa
):
    """
    Updates the specified role's user assignments.
    Users not included in the request will be unassigned from the role.

    :param workspace_id: The ID of the workspace the role belongs to.
    :param role_id: The ID of the role to update.
    :param member_ids: List of user IDs to assign this role to.
         Users not included in the request will be unassigned from the role.
         Warning: Do not remove yourself from the role that grants you the permission to edit roles,
          or you may lose access to edit this role until another user with permissions assigns it back to you.
    :return:
    """
    role = get_role(db, workspace_id, role_id)
    new_members = (db.get(User, user_id) for user_id in set(member_ids))

    role.users.clear()
    role.users.extend(m for m in new_members if m is not None)

    db.commit()

    return RoleResp.from_attributes(role, include_permissions=True, include_users=True)


@workspace.delete(
    "/roles/{role_id}",
    dependencies=[Depends(require_perms("role:delete:workspace"))],
    status_code=HTTP_204_NO_CONTENT
)
def delete_workspace_role(workspace_id: WorkspaceID, role_id: RoleID, db: DatabaseDep):
    """
    Deletes the specified role. This action is irreversible and will unassign the role from all users.
    """
    role = get_role(db, workspace_id, role_id)

    db.delete(role)
    db.commit()


@workspace.get("/my_permissions", dependencies=[Depends(require_perms("workspace:view"))])
def workspace_level_permissions(user_permissions: UserPermissionsDep):
    """
    Get the user's effective permissions for the specified workspace,
    including all global and workspace-level roles.
    """
    return list(user_permissions)


@channel.get("/roles", dependencies=[Depends(require_perms("channel:view"))])
def get_channel_roles_overrides(channel_id: uuid.UUID, db: DatabaseDep):
    overrides = db.scalars(
        select(ChannelRoleOverride)
        .where(ChannelRoleOverride.channel_id == channel_id)
    ).all()
    return overrides


def get_channel(db, channel_id):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    return channel


@channel.post(
    "/roles/{role_id}",
    dependencies=[Depends(require_perms("role:create:workspace"))],
    status_code=HTTP_201_CREATED
)
def create_channel_roles_override(
        channel_id: uuid.UUID,
        role_id: RoleID,
        db: DatabaseDep,
):
    """
    Create a new override for a role on a channel.

    - To grant a permission, the user must have that permission.
    - Permissions must have scope <= "channel" (i.e., cannot grant or deny workspace-level permissions at the channel level).
    """
    # create empty override only
    channel = get_channel(db, channel_id)
    role = get_role(db, channel.workspace_id, role_id)

    override = ChannelRoleOverride(role_id=role.id, channel_id=channel_id)
    try:
        db.add(override)
        db.commit()
    except exc.IntegrityError:
        db.rollback()
        # TODO:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Override already exists")

    return override


@channel.get("/roles/{role_id}", dependencies=[Depends(require_perms("role:view:workspace"))])
def get_channel_role_override(channel_id: uuid.UUID, role_id: RoleID, db: DatabaseDep):
    """Get specific channel role override."""
    override = db.execute(
        select(ChannelRoleOverride).where(
            and_(ChannelRoleOverride.role_id == role_id, ChannelRoleOverride.channel_id == channel_id)
        )
    ).scalar()

    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")

    return override


@channel.put("/roles/{role_id}", dependencies=[Depends(require_perms("role:edit:workspace"))])
def update_channel_roles_override(
        channel_id: uuid.UUID,
        role_id: RoleID,
        allow_permissions: Annotated[list[ScopedPermission], Form(default_factory=list)],
        deny_permissions: Annotated[list[ScopedPermission], Form(default_factory=list)],
        user_permissions: UserPermissionsDep,
        db: DatabaseDep,
        permission_registry: PermissionRegistryDep,
):
    """
        Updates the specified role's permissions for a specific channel.
        Unspecified permissions will be set to "no override" (i.e., inherit from global role permissions).
        Permissions with scope > "channel" will be ignored.
        Note: Users can only grant or revoke permissions they themselves have.
    """
    override = get_override(db, channel_id, role_id)

    missing_perms = PermissionSet.from_permissions(allow_permissions + deny_permissions) - user_permissions
    if missing_perms:
        raise errors.Forbidden(missing_perms,
                               detail="To grant or revoke a permission, you must have that permission yourself.")

    permissions = chain(zip(allow_permissions, repeat(False)),
                        zip(deny_permissions, repeat(True)))

    new_permissions = (
        (permission_registry.db_permission(p.resource, p.action, p.scope), p.scope, is_deny)
        for p, is_deny in permissions
    )

    override.permission_overrides.extend(
        RolePermission(
            permission_id=p.id,
            scope=scope,
            is_deny=is_deny
        ) for p, scope, is_deny in new_permissions
        if p is not None
        if scope <= PermissionScope.CHANNEL  # silently ignore invalid permissions
    )

    db.commit()
    return override


def get_override(db, channel_id, role_id):
    override = db.execute(
        select(ChannelRoleOverride)
        .where(
            ChannelRoleOverride.role_id == role_id,
            ChannelRoleOverride.channel_id == channel_id
        )
    ).scalar()

    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")

    return override


@channel.delete(
    "/roles/{role_id}",
    dependencies=[Depends(require_perms("role:delete"))],
    status_code=HTTP_204_NO_CONTENT)
def delete_channel_roles_override(channel_id: uuid.UUID, role_id: RoleID, db: DatabaseDep):
    """Delete channel role override."""
    override = get_override(db, channel_id, role_id)

    db.delete(override)
    db.commit()


@channel.get("/my_permissions", dependencies=[Depends(require_perms("channel:view"))])
def channel_level_permissions(user_permissions: UserPermissionsDep):
    """
    Get the user's effective permissions for the specified channel,
     including all global and channel-level overrides.
    """
    return list(user_permissions)
