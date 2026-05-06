import functools
import uuid
from enum import Enum as PyEnum
from typing import Self, Iterable

import sqlalchemy as sql
from bidict import bidict
from cachetools import cached, LRUCache, TTLCache
from sqlalchemy import select, UniqueConstraint
from sqlalchemy.dialects.postgresql import BIT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import cfg
from model import DatabaseDep, get_db, Base
from model.messaging import Workspace, Channel

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

    def permission_field(self, required_perm: Permission) -> int:
        """Computes a bitfield for the given permission string, considering both the resource-action pair and the scope."""

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
    Represents a bitfield-based permission set.
    """

    def __init__(self, registry: PermissionRegistry = None):
        self.mask = 0
        self.registry = registry or PermissionRegistry.get_instance()

    @classmethod
    def from_mask(cls, mask: int) -> Self:
        """Creates a PermissionSet instance from a given bitfield integer."""
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
        Sets the ANY scope bit for a resource-action pair if the user has that permission in any scope.
        Clears other bits.

        NOTE: Assumes this bit order follows the order of PermissionScope
        """
        new_set = PermissionSet()
        for scope in PermissionScope:
            scope_mask = self.registry.scope_mask(scope)
            shift = PermissionScope.ANY.value - scope.value
            if shift >= 0:
                new_set.mask |= (self.mask & scope_mask) << shift
            else:
                new_set.mask |= (self.mask & scope_mask) >> -shift

        return self | new_set

    def __setitem__(self, key: Permission, value: bool):
        bit_pos = self.registry.bit_offset(key)
        if bit_pos is None:
            raise ValueError(f"Permission {key} cannot be represented")

        if value:
            self.mask |= (1 << bit_pos)
        else:
            self.mask &= ~(1 << bit_pos)

    def __contains__(self, item: Permission) -> bool:
        # TODO: consider scope
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


users_roles = sql.Table(
    "users_roles", Base.metadata,
    sql.Column("user_id", sql.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sql.Column("role_id", sql.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)
role_permissions = sql.Table(
    "role_permissions", Base.metadata,
    sql.Column("role_id", sql.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    sql.Column("permission_id", sql.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)
override_permissions = sql.Table(
    "override_permissions", Base.metadata,
    sql.Column("role_id", sql.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    sql.Column("channel_id", sql.ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
    sql.Column("permission_id", sql.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    sql.ForeignKeyConstraint(("role_id", "channel_id"),
                             ("role_overrides.role_id", "role_overrides.channel_id"))
)


@functools.total_ordering
class PermissionScope(PyEnum):
    OWN = 0
    CHANNEL = 1
    WORKSPACE = 2
    ANY = 3

    def __lt__(self, other: PermissionScope) -> bool:
        return self.value < other.value

    def __str__(self):
        return self.name.lower()

    @classmethod
    def from_str(cls, raw_scope) -> Self:
        if raw_scope is None or raw_scope == "*":
            return cls.ANY
        return cls[raw_scope.upper()]


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    resource: Mapped[str] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    scope: Mapped[PermissionScope] = mapped_column(sql.Enum(PermissionScope), index=True)
    is_deny: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column()
    bit_offset: Mapped[int] = mapped_column(default=0, name="bit_offset_0")

    def covers(self, other: Permission, check_deny=True) -> bool:
        if (
                self.resource != other.resource
                or self.action != other.action
                or self.scope < other.scope
                or (check_deny and self.is_deny and not other.is_deny)

        ):
            return False

        return True

    # TODO: assert that resource, action
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
        return f"{self.resource}:{self.action}:{self.scope.value if self.scope else '*'}"


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()

    # `workspace_id` == None: a global role, applies to the entire app
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(sql.ForeignKey(Workspace.id, ondelete="CASCADE"), index=True,
                                                           default=None)

    priority: Mapped[int] = mapped_column(index=True, default=0)

    # PERF: Precomputed bitfields, recomputed on permission or role changes
    allow_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=0)

    users = relationship("User", secondary=users_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, backref="roles")

    __table_args__ = (
        UniqueConstraint(workspace_id, name),
    )


class ChannelRoleOverride(Base):
    __tablename__ = "role_overrides"

    role_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(Role.id, ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(Channel.id, ondelete="CASCADE"), primary_key=True)

    permissions = relationship("Permission", secondary=override_permissions)

    # PERF: Precomputed bitfield, recomputed on permission or role changes
    allow_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=0)
    deny_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=0)
