import uuid
from typing import Annotated, Callable

from cachetools import cached, LRUCache
from fastapi import Path, Depends
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import BitString

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from config import cfg
from model import DatabaseDep
from model.messaging import Channel
from .model import Role, ChannelRoleOverride as Override, STATIC_ROLE_ID
from .registry import PermissionRegistry, PermissionSet, ScopedPermission

# TODO: use reddis
permission_cache = LRUCache(maxsize=2 ** 16)


@cached({}, key=lambda db: None)
def permission_registry(db: DatabaseDep):
    return PermissionRegistry(db)


PermissionRegistryDep = Annotated[PermissionRegistry, Depends(permission_registry)]


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
        if permissions is None:
            return PermissionSet()
        return PermissionSet.from_mask(permissions)

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

    def helper(user_permissions: UserPermissionsDep, is_owner: Annotated[bool, Depends(is_owner)]):
        nonlocal required_perms

        if required_perms is None:
            required_perms = PermissionSet.from_permissions(
                ScopedPermission.from_str(p) for p in required_permissions
            )

        missing = required_perms - user_permissions.as_owner(is_owner)

        if not missing.empty():
            raise errors.Forbidden(missing)

    return helper
