import uuid
from typing import Annotated, Self, Iterable, Callable

from bidict import bidict
from cachetools import cached, LRUCache, TTLCache
from fastapi import Depends, Path
from sqlalchemy import select, or_

from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep
from model import DatabaseDep, get_db
from model.identity import Permission, Role, ChannelRoleOverride, PermissionScope

EVERYONE_ID = uuid.UUID(int=0)

PERMISSIONS = {
    "workspace": {
        "actions": [
            "create",
            "read",
            "update",
            "delete"
        ],
        "scope": ["*", "own"]
    },
    "audit_log": {
        "actions": ["read"],
        "scopes": ["workspace"]
    },
    "member": {
        "actions": [
            "invite"
            "kick",
            "ban",
            "change_nickname",
            "manage_nickname",
            "moderate",
        ],
        "scopes": ["workspace"]
    },
    "channel": {
        "actions": ["create", "read", "update", "delete"],
        "scopes": ["own", "channel"]
    },
    "mention": {
        "actions": ["*", "here", "roles", "members"],
        "scopes": ["channel"]

    },
    "message": {
        "actions": [
            "send",
            "manage",
            "embed_links",
            "attach_files",
            "voice",
            "poll",
            "pin"
        ],
        "scopes": ["own", "channel"]
    },
    "permission": {
        "actions": ["edit", "grant", "revoke"],
        "scopes": ["workspace"]
    },
    "meeting": {
        "actions": ["create", "join", "manage", "end",
                    "speak", "priority_speak", "request_to_speak",
                    "stream",
                    ],
        "scopes": ["workspace", "channel"],
        "subresources": {
            "member": {
                "actions": ["mute", "deafen", "move"],
                "scopes": ["workspace", "channel"]
            },
        }
    },
    "ai": {
        "actions": ["use", "manage"],
        "scopes": ["workspace", "channel"]
    },
    "commands": {
        "actions": ["use", "manage"],
        "scopes": ["workspace", "channel"]
    },
}

default_perm_cache = TTLCache(ttl=60, maxsize=1)
perm_cache = LRUCache(maxsize=2 ** 16)


class PermissionRegistry:
    _permission_registry = bidict()
    _scope_mask_cache = dict()
    _global_instance = None

    def __init__(self, db: DatabaseDep = None):
        self.db = db or next(get_db())

    @classmethod
    def get_instance(cls) -> Self:
        if cls._global_instance is None:
            cls._global_instance = cls()

        return cls._global_instance

    @cached(cache=_permission_registry.inverse)
    def bit_offset(self, key: Permission) -> int | None:
        perm_id: int = self.db.scalar(
            select(Permission.bit_offset)
            .where(Permission.resource == key.resource)
            .where(Permission.action == key.action)
            .where(Permission.scope == key.scope)
        )
        return perm_id

    @cached(cache=_permission_registry)
    def permission(self, key: int) -> Permission | None:
        resource, action, scope = self.db.scalar(
            select(Permission.resource, Permission.action, Permission.scope)
            .where(Permission.bit_offset == key)
        ).one_or_none()
        return Permission(resource=resource, action=action, scope=scope)

    def permission_mask(self, required_perm: Permission) -> int:
        """Computes a bitmask for the given permission string, considering both the resource-action pair and the scope."""

        scope_bits = self.scope_mask(required_perm.scope)
        resource_action_bits = 0
        bit_offsets = self.db.scalars(
            select(Permission.bit_offset)
            .where(Permission.resource == required_perm.resource)
            .where(Permission.action == required_perm.action)
        )

        for bit_offset in bit_offsets:
            resource_action_bits |= (1 << bit_offset)

        return resource_action_bits & scope_bits

    @cached(cache=_scope_mask_cache)
    def scope_mask(self, scope: PermissionScope) -> int:
        """Computes a bitmask for the given scope string."""
        if scope == PermissionScope.ANY:
            bit_offsets = self.db.scalars(select(Permission.bit_offset))
        else:
            bit_offsets = self.db.scalars(
                select(Permission.bit_offset)
                .where(Permission.scope == scope)
            )

        mask = 0
        for offset in bit_offsets:
            mask |= (1 << offset)

        return mask


class PermissionSet:
    """
    Represents a bitmask-based permission set.
    """

    def __init__(self, registry: PermissionRegistry = None):
        self.mask = 0
        self.registry = registry or PermissionRegistry.get_instance()

    @classmethod
    def from_mask(cls, mask: int) -> Self:
        """Creates a PermissionSet instance from a given bitmask integer."""
        instance = cls()
        instance.mask = mask
        return instance

    @classmethod
    def from_permission_list(cls, perms: Iterable[Permission]) -> Self:
        """Creates a PermissionSet instance from a list of Permission objects."""
        instance = cls()
        for perm in perms:
            instance[perm] = True
        return instance

    def collapse_scope(self) -> Self:
        """
        Sets the ANY scope bit for a resource-action pair iff the user has that permission in any scope.
        Clears other bits.

        NOTE: Assumes this bit order follows the order of PermissionScope
        """
        new_set = PermissionSet()
        for i, scope in enumerate(reversed(PermissionScope)):
            scope_mask = self.registry.scope_mask(scope)
            new_set.mask |= (self.mask & scope_mask) >> i

        return new_set

    def __setitem__(self, key: Permission, value: bool):
        bit_pos = self.registry.bit_offset(key)
        if bit_pos is None:
            raise ValueError(f"Permission {key} cannot be represented")

        if value:
            self.mask |= (1 << bit_pos)
        else:
            self.mask &= ~(1 << bit_pos)

    def __contains__(self, item: Permission) -> bool:
        bit_pos = self.registry.bit_offset(item)
        if bit_pos is None:
            return False

        return bool(self.mask & (1 << bit_pos))

    def __or__(self, other: PermissionSet):
        return self.from_mask(self.mask | other.mask)

    def __and__(self, other: PermissionSet):
        return self.from_mask(self.mask & other.mask)

    def __sub__(self, other: PermissionSet):
        return self.from_mask(self.mask & ~other.mask)

    def __iter__(self):
        mask = self.mask
        bit_pos = 0

        while mask:
            if mask & 1:
                perm = self.registry.permission(bit_pos)
                if perm:
                    yield perm
            mask >>= 1
            bit_pos += 1

    def __len__(self) -> int:
        return bin(self.mask).count("1")


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
        permissions = base_permissions(wid, db)
        deny_overrides = PermissionSet()
        allow_overrides = PermissionSet()

        roles_and_overrides = db.scalars(
            select(Role, ChannelRoleOverride)
            .join(ChannelRoleOverride, Role.id == ChannelRoleOverride.role_id, isouter=True)
            .where(Role.users.any(id=uid))
            .where(Role.workspace_id == cid)
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

    def assert_perms(user_permissions: Annotated[PermissionSet, Depends(user_perms)],
                     is_owner: Annotated[bool, Depends(is_owner)]):
        if not is_owner:
            # Clear OWN scope permissions if the user is not the owner
            user_permissions -= PermissionSet.from_mask(registry.scope_mask(PermissionScope.OWN))

        user_permissions = user_permissions.collapse_scope()
        if not required_perms <= user_permissions:
            raise errors.Forbidden(required_perms - user_permissions)

    return assert_perms
