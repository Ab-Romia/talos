import uuid
from typing import Annotated, Callable

from cachetools import cached, LRUCache
from fastapi import Path, Depends
from sqlalchemy import select, and_, func

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep
from .model import Role, ChannelRoleOverride, PermissionScope, DEFAULT_BITS
from .registry import PermissionRegistry, PermissionSet, ScopedPermission

# TODO: use reddis
permission_cache = LRUCache(maxsize=2 ** 16)


@cached({}, key=lambda *args: None)
def permission_registry(db: DatabaseDep):
    return PermissionRegistry(db)


def user_perms(
        session: SessionDep,
        db: DatabaseDep,
        workspace_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
        channel_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
):
    @cached(permission_cache)
    def helper(workspace_id, channel_id, user_id):
        permissions = PermissionSet()
        deny_overrides = PermissionSet()
        allow_overrides = PermissionSet()

        roles_and_overrides = db.execute(
            select(
                Role.allow_mask,
                func.coalesce(ChannelRoleOverride.allow_mask, DEFAULT_BITS),
                func.coalesce(ChannelRoleOverride.deny_mask, DEFAULT_BITS),
            )
            .join(ChannelRoleOverride,
                  and_(Role.id == ChannelRoleOverride.role_id,
                       ChannelRoleOverride.channel_id == channel_id),
                  isouter=True
                  )
            .where(Role.users.any(id=user_id))
            .where(Role.workspace_id == workspace_id)
            .order_by(Role.priority.desc())
        ).all()

        for role_allow, override_allow, override_deny in roles_and_overrides:
            permissions |= PermissionSet.from_mask(role_allow)
            deny_overrides |= PermissionSet.from_mask(override_deny)
            allow_overrides |= PermissionSet.from_mask(override_allow)

        permissions -= deny_overrides
        permissions |= allow_overrides

        return permissions

    return helper(workspace_id, channel_id, session.sub)


UserPermissionsDep = Annotated[PermissionSet, Depends(user_perms)]


def require_perms(*required_permissions: str, is_owner: Callable[..., bool] = lambda: False):
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

    # TODO: assert permissions exist at startup, (or register them?)
    required_perms = PermissionSet.from_permission_list(ScopedPermission.from_str(p) for p in required_permissions)
    own_scope_mask = PermissionSet.from_mask(permission_registry().scope_mask(PermissionScope.OWN))

    # TODO: implement caching for user permissions
    # TODO: special case for `permission:edit`: user must have the permission to grant/revoke it

    def helper(user_permissions: UserPermissionsDep, is_owner: Annotated[bool, Depends(is_owner)]):
        if not is_owner:
            # Clear OWN scope permissions if the user is not the owner
            user_permissions -= own_scope_mask

        user_permissions = user_permissions.set_any_bit()
        missing = required_perms - user_permissions
        if not missing.empty():
            raise errors.Forbidden(missing)

    return helper
