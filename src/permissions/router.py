import uuid
from itertools import chain, repeat
from typing import Annotated

from fastapi import Form, HTTPException, Depends, Body, APIRouter
from pydantic import BaseModel
from sqlalchemy import select, and_
from starlette import status
from starlette.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from auth.dependencies import user_id
from auth.model import User
from auth.utils import errors
from database import DatabaseDep
from permissions import UserPermissionsDep, db_permission
from permissions.model import Role, RolePermission, ChannelRoleOverride, PermissionSet, ScopedPermission
from workspace import is_owner, require_perms, WorkspaceID, RoleID
from workspace.model import Workspace, Channel

workspace = APIRouter(tags=["permissions"])
channel = APIRouter(tags=["permissions"])


class RoleResp(BaseModel):
    id: uuid.UUID
    name: str
    priority: int
    description: str | None = None
    permissions: list[ScopedPermission] | None = None
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
                perms.append(ScopedPermission(
                    resource=perm.resource,
                    action=perm.action,
                    scope=rp.scope,
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
        .where(Role.id == role_id, Role.workspace_id == workspace_id)
    )

    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    return role


@workspace.get(
    "/roles",
    dependencies=[require_perms("workspace.role:view")],
    response_model=list[RoleResp]
)
def list_workspace_roles(workspace_id: WorkspaceID, db: DatabaseDep):
    """List all roles for the workspace."""
    roles = db.scalars(select(Role).where(Role.workspace_id == workspace_id)).all()
    return [RoleResp.from_attributes(r) for r in roles]


@workspace.post(
    "/roles",
    dependencies=[require_perms("workspace.role:manage")],
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

    workspace.roles.insert(priority, role)
    db.commit()

    return RoleResp.from_attributes(role)


@workspace.get(
    "/roles/{role_id}",
    dependencies=[require_perms("workspace.role:view")],
    response_model=RoleResp,
)
def get_workspace_role(workspace_id: WorkspaceID, role_id: RoleID, db: DatabaseDep):
    """Returns the details of the specified role, including its permissions and assigned users."""
    role = get_role(db, workspace_id, role_id)
    return RoleResp.from_attributes(role, include_permissions=True, include_users=True)


@workspace.put(
    "/roles/{role_id}",
    dependencies=[require_perms("workspace.role:manage")],
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
    dependencies=[require_perms("workspace.role:manage")],
    response_model=RoleResp,
)
def update_workspace_role_permissions(
        workspace_id: WorkspaceID,
        role_id: RoleID,
        permissions: Annotated[list[ScopedPermission], Body()],

        user_id: Annotated[uuid.UUID, Depends(user_id)],
        user_permissions: UserPermissionsDep,
        db: DatabaseDep,
):
    """
    Updates the specified role's permissions and user assignments.
    Permissions not included in the request will be revoked.
    Note: Users can only grant permissions they themselves have.
    """
    role = get_role(db, workspace_id, role_id)
    request_permissions = PermissionSet.from_permissions(permissions, db)

    missing = request_permissions - user_permissions.as_owner(
        is_owner(user_id, workspace_id, None, db)
    )

    if not missing.empty():
        raise errors.Forbidden(
            missing.iter(db),
            detail="To grant or revoke a permission, you must have that permission yourself."
        )

    new_permissions = ((db_permission(db, p.resource, p.action, p.scope), p.scope)
                       for p in request_permissions.iter(db))

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
    dependencies=[require_perms("workspace.role:manage")],
    response_model=RoleResp,
)
def update_workspace_role_members(
        workspace_id: WorkspaceID,
        role_id: RoleID,
        member_ids: Annotated[list[uuid.UUID], Form()],
        db: DatabaseDep,
):
    """
    Updates the specified role's user assignments.
    Users not included in the request will be unassigned from the role.

    Warning: Do not remove yourself from the role that grants you the permission to edit roles,
      or you may lose access to edit this role until another user with permissions assigns it back to you.
    """
    role = get_role(db, workspace_id, role_id)
    new_members = (db.get(User, user_id) for user_id in set(member_ids))

    role.users.clear()
    role.users.extend(m for m in new_members if m is not None)

    db.commit()

    return RoleResp.from_attributes(role, include_permissions=True, include_users=True)


@workspace.delete(
    "/roles/{role_id}",
    dependencies=[require_perms("workspace.role:manage")],
    status_code=HTTP_204_NO_CONTENT
)
def delete_workspace_role(workspace_id: WorkspaceID, role_id: RoleID, db: DatabaseDep):
    """
    Deletes the specified role. This action is irreversible and will unassign the role from all users.
    """
    role = get_role(db, workspace_id, role_id)
    if role.id == role.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete workspace base role")

    db.delete(role)
    db.commit()


@workspace.get("/my_permissions")
def workspace_level_permissions(user_permissions: UserPermissionsDep, db: DatabaseDep):
    """
    Get the user's effective permissions for the specified workspace,
    including all global and workspace-level roles.
    """
    return list(user_permissions.iter(db))


@channel.get("/roles", dependencies=[require_perms("workspace.role:view")])
def get_channel_roles_overrides(channel_id: uuid.UUID, db: DatabaseDep):
    overrides = db.scalars(
        select(ChannelRoleOverride)
        .where(ChannelRoleOverride.channel_id == channel_id)
    ).all()
    return overrides


@channel.post(
    "/roles/{role_id}",
    dependencies=[require_perms("workspace.role:manage")],
    status_code=HTTP_201_CREATED
)
def create_channel_roles_override(channel_id: uuid.UUID, role_id: RoleID, db: DatabaseDep):
    """
    Create a new override for a role on a channel.

    - To grant a permission, the user must have that permission.
    - Permissions must have scope <= "channel" (i.e., cannot grant or deny workspace-level permissions at the channel level).
    """
    channel = db.get_one(Channel, channel_id)
    role = get_role(db, channel.workspace_id, role_id)

    # create empty override only
    override = ChannelRoleOverride(role_id=role.id, channel_id=channel_id)
    db.add(override)
    db.commit()

    return override


@channel.get("/roles/{role_id}", dependencies=[require_perms("workspace.role:view")])
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


@channel.put("/roles/{role_id}", dependencies=[require_perms("workspace.role:manage")])
def update_channel_roles_override(
        channel_id: uuid.UUID,
        role_id: RoleID,
        allow_permissions: Annotated[list[ScopedPermission], Form(default_factory=list)],
        deny_permissions: Annotated[list[ScopedPermission], Form(default_factory=list)],

        user_id: Annotated[uuid.UUID, Depends(user_id)],
        user_permissions: UserPermissionsDep,
        db: DatabaseDep,
):
    """
        Updates the specified role's permissions for a specific channel.
        Unspecified permissions will be set to "no override" (i.e., inherit from global role permissions).
        Note: Users can only grant or revoke permissions they themselves have.
    """
    override = db.execute(
        select(ChannelRoleOverride)
        .where(
            ChannelRoleOverride.role_id == role_id,
            ChannelRoleOverride.channel_id == channel_id
        )
    ).scalar()
    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")

    missing_perms = (
            PermissionSet.from_permissions(allow_permissions + deny_permissions, db)
            - user_permissions.as_owner(is_owner(user_id, None, channel_id, db))
    )

    if missing_perms:
        raise errors.Forbidden(missing_perms.iter(db),
                               detail="To grant or revoke a permission, you must have that permission yourself.")

    permissions = chain(zip(allow_permissions, repeat(False)),
                        zip(deny_permissions, repeat(True)))

    new_permissions = (
        (db_permission(db, p.resource, p.action, p.scope), p.scope, is_deny)
        for p, is_deny in permissions
    )

    override.permission_overrides.extend(
        RolePermission(
            permission_id=p.id,
            scope=scope,
            is_deny=is_deny
        ) for p, scope, is_deny in new_permissions
        if p is not None
    )

    db.commit()
    return override


@channel.delete(
    "/roles/{role_id}",
    dependencies=[require_perms("workspace.role:manage")],
    status_code=HTTP_204_NO_CONTENT)
def delete_channel_roles_override(channel_id: uuid.UUID, role_id: RoleID, db: DatabaseDep):
    """Delete channel role override."""
    override = db.scalar(
        select(ChannelRoleOverride)
        .where(
            ChannelRoleOverride.role_id == role_id,
            ChannelRoleOverride.channel_id == channel_id
        )
    )

    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")

    if override.role_id == override.channel.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot delete override for workspace base role")

    db.delete(override)
    db.commit()


@channel.get("/my_permissions")
def channel_level_permissions(user_permissions: UserPermissionsDep, db: DatabaseDep):
    """
    Get the user's effective permissions for the specified channel,
     including all global and channel-level overrides.
    """
    return list(user_permissions.iter(db))
