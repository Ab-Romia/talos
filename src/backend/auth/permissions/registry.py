from typing import Self, Iterable, Generator

from bidict import bidict, OnDup, RAISE, DROP_OLD
from cachetools import cached
from pydantic import BaseModel
from pydantic_core import core_schema
from sqlalchemy import orm, select
from sqlalchemy.dialects.postgresql import BitString

from backend.auth.permissions.model import PermissionScope, Permission, DEFAULT_EVERYONE_ROLE_ID, Role


class PermissionRegistry:
    # offset <-> permission
    _permission_registry = bidict()

    def __init__(self, db: orm.Session):
        self._permission_registry.on_dup = OnDup(key=RAISE, val=DROP_OLD)
        self.db = db

    def default_everyone_role(self):
        return self.db.get(Role, DEFAULT_EVERYONE_ROLE_ID)

    @cached(_permission_registry.inverse, key=lambda self, permission: permission)
    def bit_offset(self, permission: ScopedPermission) -> int | None:
        perm = self.db_permission(permission.resource, permission.action, permission.scope)

        if perm is None:
            return None

        return perm.bit_offset + permission.scope.offset

    @cached(_permission_registry, key=lambda self, key: key)
    def permission_from_offset(self, key: int) -> ScopedPermission | None:
        try:
            scope = PermissionScope(key // PermissionScope.max_bit_length())
        except ValueError:
            return None

        perm = self.db.scalar(
            select(Permission)
            .where(Permission.bit_offset == key % PermissionScope.max_bit_length())
            .where(Permission.allowed_scopes.contains([scope]))
        )

        if perm is None:
            return None

        return ScopedPermission(resource=perm.resource, action=perm.action, scope=scope)

    def db_permission(self, resource: str, action: str,
                      scope: PermissionScope = PermissionScope.ANY) -> Permission | None:
        """Fetches the Permission object from the database for the given resource, action, and scope."""
        return self.db.scalar(
            select(Permission)
            .where(Permission.resource == resource)
            .where(Permission.action == action)
            .where(Permission.allowed_scopes.contains([scope]))
        )

    def clear_caches(self):
        self.bit_offset.cache_clear()
        self.permission_from_offset.cache_clear()


class ScopedPermission(BaseModel):
    resource: str
    action: str
    scope: PermissionScope

    @classmethod
    def from_str(cls, perm_str: str) -> Self:
        """
        Creates an instance of the class based on a permission string. The permission
        string is expected to follow the format `resource:action:scope`. The resource
        and action are mandatory, while the scope is optional. If the scope is not
        provided, it defaults to `PermissionScope.ANY`.

        :param perm_str: A string representation of the permission in the
            format `resource[.subresource]:action[:scope]`. The resource and action are required,
            and the scope, if provided, represents the level of access.
        :raises ValueError: If the resource or action part of the string is empty.
        :return: An instance of `Permission` from the parsed string.
        """
        resource, action, raw_scope = [*perm_str.split(":") + [None] * 3][:3]

        if not resource or not action:
            raise ValueError("Permission resource and action cannot be empty.")

        scope = PermissionScope.from_str(raw_scope) if raw_scope else PermissionScope.ANY

        return cls(resource=resource,
                   action=action,
                   scope=scope)

    def __str__(self):
        return f"{self.resource}:{self.action}:{self.scope if self.scope else '*'}"

    def __eq__(self, other: ScopedPermission) -> bool:
        return (self.resource, self.action, self.scope) == (other.resource, other.action, other.scope)

    def __hash__(self):
        return hash((self.resource, self.action, self.scope))

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        # Parse permission strings directly into ScopedPermission.
        return core_schema.no_info_before_validator_function(
            lambda v: cls.from_str(v) if isinstance(v, str) else v,
            handler(source_type),
        )


class PermissionSet:
    """
    Represents a bitfield-based permission set.
    """

    def __init__(self, bitstring: int = 0, registry: PermissionRegistry | None = None):
        from .core import permission_registry
        self.bitstring = bitstring
        self.registry = registry if registry is not None else permission_registry(None)

    @classmethod
    def from_mask(cls, mask: int | str | BitString) -> Self:
        """Creates a PermissionSet instance from a given bitfield integer."""
        if isinstance(mask, BitString):
            mask = int(mask, 2)
        elif isinstance(mask, str):
            mask = int(mask, 2)

        instance = cls()
        instance.bitstring = mask
        return instance

    @classmethod
    def from_permissions(cls, perms: Iterable[ScopedPermission]) -> Self:
        """Creates a PermissionSet instance from a list of Permission objects."""
        instance = cls()
        for perm in perms:
            instance[perm] = True
        return instance

    def empty(self):
        return self.bitstring == 0

    def __setitem__(self, key: ScopedPermission, value: bool):
        bit_pos = self.registry.bit_offset(key)
        if bit_pos is None:
            raise ValueError(f"Permission {key} cannot be represented")

        if value:
            self.bitstring |= (1 << bit_pos)
        else:
            self.bitstring &= ~(1 << bit_pos)

    def __contains__(self, item: ScopedPermission) -> bool:
        bit_pos = self.registry.bit_offset(item)
        if bit_pos is None:
            return False

        return bool(self.bitstring & (1 << bit_pos))

    def __eq__(self, other: PermissionSet) -> bool:
        return self.bitstring == other.bitstring

    def __or__(self, other: PermissionSet):
        return PermissionSet(bitstring=self.bitstring | other.bitstring, registry=self.registry)

    def __xor__(self, other: PermissionSet):
        return PermissionSet(bitstring=self.bitstring ^ other.bitstring, registry=self.registry)

    def __and__(self, other: PermissionSet):
        return PermissionSet(bitstring=self.bitstring & other.bitstring, registry=self.registry)

    def __sub__(self, other: PermissionSet):
        return PermissionSet(bitstring=self.bitstring & ~other.bitstring, registry=self.registry)

    def __iter__(self) -> Generator[ScopedPermission]:
        mask = self.bitstring
        bit_pos = 0

        while mask:
            if mask & 1:
                perm = self.registry.permission_from_offset(bit_pos)
                if perm:
                    yield perm
            mask >>= 1
            bit_pos += 1

    def __len__(self) -> int:
        return bin(self.bitstring).count("1")

    def as_owner(self, is_owner):
        """Set OWN permissions as ANY permissions if the user is an owner."""
        if is_owner:
            self.bitstring |= (
                    (self.bitstring & PermissionScope.OWN.mask)
                    >> PermissionScope.OWN.offset
                    << PermissionScope.ANY.offset
            )

        return self
