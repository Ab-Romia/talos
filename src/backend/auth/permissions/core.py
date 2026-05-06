import uuid
from typing import Annotated, Callable

from cachetools import cached
from fastapi import Path, Depends
from sqlalchemy import select, or_

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from model.messaging import Workspace
from .model import PermissionRegistry, PermissionSet, default_perm_cache, EVERYONE_ID, \
    perm_cache, Role, ChannelRoleOverride, Permission, PermissionScope

registry = PermissionRegistry()


def default_base_permissions(db: DatabaseDep) -> PermissionSet:
    @cached(default_perm_cache)
    def helper():
        allow = db.scalar(
            select(Role.allow_mask)
            .where(Role.id == EVERYONE_ID)
        )
        assert allow is not None

        return PermissionSet.from_mask(allow)

    return helper()


def base_permissions(workspace_id: uuid.UUID, db: DatabaseDep) -> PermissionSet:
    @cached(perm_cache)
    def helper(wsid):
        default = default_base_permissions(db)
        if wsid is None:
            return default

        allow = db.scalar(
            select(Role.allow_mask)
            .where(Role.workspace_id == wsid)
            .where(Role.id == wsid)
        )

        if allow is None:
            return default

        return PermissionSet.from_mask(allow)

    return helper(workspace_id)


def user_perms(
        workspace_id: Annotated[uuid.UUID | None, Path(default=None)],
        channel_id: Annotated[uuid.UUID | None, Path(default=None)],
        session: SessionDep,
        db: DatabaseDep):
    @cached(perm_cache)
    def helper(wid, cid, uid):
        # Validate that the user is a member of the workspace (if workspace_id is provided)
        wid = db.scalar(select(Workspace.id)
                        .where(Workspace.id == wid)
                        .where(Workspace.members.any(id=uid))
                        )
        permissions = base_permissions(wid, db)
        deny_overrides = PermissionSet()
        allow_overrides = PermissionSet()

        roles_and_overrides = db.scalars(
            select(Role, ChannelRoleOverride)
            .join(ChannelRoleOverride, Role.id == ChannelRoleOverride.role_id, isouter=True)
            .where(Role.users.any(id=uid))
            .where(Role.workspace_id == wid)
            .where(or_(ChannelRoleOverride.channel_id.is_(None), ChannelRoleOverride.channel_id == channel_id))
        ).all()

        for r, o in roles_and_overrides:
            permissions |= r.allow_mask
            if o is not None:
                deny_overrides |= o.deny_mask
                allow_overrides |= o.allow_mask

        permissions -= deny_overrides
        permissions |= allow_overrides

        return permissions

    return helper(workspace_id, channel_id, session.sub)


def require_perms(*required_permissions: str,
                  is_owner: Callable[..., bool] = lambda: False):
    """
    Processes permission requirements for a specific context to validate that the user has the
    necessary permissions. This function defines a permission validation system by combining
    a set of required permissions, a context getter, and a context validator, ensuring that
    the user satisfies permission prerequisites based on the given scope context.

    :param required_permissions: A variable list of permission strings that are required.
    :param is_owner: A function that checks if the user is the owner of the resource in question,
                     which can be used to grant permissions based on ownership.

    :return: A function that validates user permissions by asserting that the required
        permissions are present within the user’s permissions based on the context.
    """

    required_perms = PermissionSet.from_permission_list((Permission.from_str(p) for p in required_permissions))

    # TODO: implement caching for user permissions
    # TODO: special case for `permission:edit`: user must have the permission to grant/revoke it

    def helper(user_permissions: Annotated[PermissionSet, Depends(user_perms)],
               is_owner: Annotated[bool, Depends(is_owner)]):
        if not is_owner:
            # Clear OWN scope permissions if the user is not the owner
            user_permissions -= PermissionSet.from_mask(registry.scope_mask(PermissionScope.OWN))

        user_permissions = user_permissions.collapse_scope()
        missing = required_perms - user_permissions
        if len(missing) > 0:
            raise errors.Forbidden(missing)

    return helper
