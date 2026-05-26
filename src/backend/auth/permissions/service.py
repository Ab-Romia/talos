import uuid
from typing import Annotated, Callable

from bidict import bidict, OnDup, RAISE, DROP_OLD
from cachetools import cached, LRUCache
from fastapi import Path, Depends
from sqlalchemy import select, func, orm
from sqlalchemy.dialects.postgresql import BitString

from backend.auth.utils.session import SessionDep
from config import cfg
from model import DatabaseDep
from model.messaging import Channel
from .model import Role, ChannelRoleOverride as Override, STATIC_ROLE_ID, PermissionScope, Permission, PermissionSet, \
    ScopedPermission

# TODO: use reddis
permission_cache = LRUCache(maxsize=2 ** 16)


def user_perms(
        session: SessionDep,
        db: DatabaseDep,
        workspace_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
        channel_id: Annotated[uuid.UUID | None, Path(default_factory=lambda: None)],
):
    @cached(permission_cache)
    def helper(workspace_id, channel_id, user_id):
        zero_bits = BitString.from_int(0, length=cfg().auth.permission_bitstring_length)
        channel_override_deny = func.coalesce(Override.deny_mask, zero_bits)
        channel_override_allow = func.coalesce(Override.allow_mask, zero_bits)
        static_role_mask = select(Role.allow_mask).where(Role.id == STATIC_ROLE_ID).scalar_subquery()

        # perm |= (role.perms & ~override.allow | override.deny) for all roles
        permissions = db.scalar(
            select(
                static_role_mask.bitwise_or(
                    func.bit_or(
                        Role.allow_mask
                        .bitwise_and(channel_override_deny.bitwise_not())
                        .bitwise_or(channel_override_allow)
                    )
                )
            )
            .select_from(Role)
            .join(Channel, Channel.id == channel_id, isouter=True)
            .join(Override, (Override.role_id == Role.id) & (Override.channel_id == channel_id), isouter=True)
            .where(Role.users.any(id=user_id) | (Role.id == Role.workspace_id))  # Include workspace base permissions
            .where(Role.workspace_id == func.coalesce(workspace_id, Channel.workspace_id))
            .group_by()
        )
        return PermissionSet(permissions or 0)

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

    required_perms = None  # Lazy initialization to avoid import time issues

    def assert_permissions(user_permissions: UserPermissionsDep,
                           is_owner: Annotated[bool, Depends(is_owner)],
                           db: DatabaseDep):
        nonlocal required_perms

        # initialize required_perms
        if required_perms is None:
            required_perms = PermissionSet.from_permissions(required_permissions, db)

        missing = required_perms - user_permissions.as_owner(is_owner)

        if not missing.empty():
            from backend.auth.utils import errors
            raise errors.Forbidden(missing.iter(db))

    return assert_permissions


class Bidict(bidict):
    on_dup = OnDup(key=RAISE, val=DROP_OLD)


_permission_registry = Bidict()


@cached(_permission_registry.inverse, key=lambda db, permission: permission)
def bit_offset(db: orm.Session, permission: ScopedPermission) -> int | None:
    perm = db_permission(db, permission.resource, permission.action, permission.scope)

    if perm is None:
        return None

    return perm.bit_offset + permission.scope.offset


@cached(_permission_registry, key=lambda db, key: key)
def permission_from_offset(db: orm.Session, key: int) -> ScopedPermission | None:
    try:
        scope = PermissionScope(key // PermissionScope.max_bit_length())
    except ValueError:
        return None

    perm = db.scalar(
        select(Permission)
        .where(Permission.bit_offset == key % PermissionScope.max_bit_length())
        .where(Permission.allowed_scopes.contains([scope]))
    )

    if perm is None:
        return None

    return ScopedPermission(resource=perm.resource, action=perm.action, scope=scope)


def db_permission(db: orm.Session, resource: str, action: str,
                  scope: PermissionScope = PermissionScope.ANY, ) -> Permission | None:
    """Fetches the Permission object from the database for the given resource, action, and scope."""
    return db.scalar(
        select(Permission)
        .where(Permission.resource == resource)
        .where(Permission.action == action)
        .where(Permission.allowed_scopes.contains([scope]))
    )
