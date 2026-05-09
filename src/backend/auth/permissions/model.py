import functools
import uuid
from enum import Enum as PyEnum
from typing import Self, Iterable

import sqlalchemy as sql
from bidict import bidict
from cachetools import cached, TTLCache
from sqlalchemy import select, UniqueConstraint, orm, exists, text
from sqlalchemy.dialects.postgresql import BIT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import cfg
from model import Base
from model.messaging import Workspace, Channel

EVERYONE_ID = uuid.UUID(int=0)
BITSTRING_LENGTH = cfg().auth.permission_bitstring_length
DEFAULT_BITS = text(f"CAST(0 AS BIT({BITSTRING_LENGTH}))")

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


class PermissionRegistry:
    _permission_registry = bidict()

    def __init__(self, db: orm.Session):
        self.db = db

    @cached(TTLCache(ttl=60, maxsize=1))
    def default_base_permissions(self) -> PermissionSet:
        allow = self.db.scalar(
            select(Role.allow_mask)
            .where(Role.id == EVERYONE_ID)
        )
        assert allow is not None

        return PermissionSet.from_mask(allow)

    @cached(_permission_registry.inverse)
    def bit_offset(self, resource: str, action: str, scope: PermissionScope) -> int | None:
        return self.db.scalar(
            select(Permission.bit_offset)
            .where(Permission.resource == resource)
            .where(Permission.action == action)
            .where(Permission.scope == scope)
        )

    @cached(_permission_registry)
    def permission_from_offset(self, key: int) -> Permission | None:
        return self.db.scalar(
            select(Permission)
            .where(Permission.bit_offset == key)
        )

    def get_permission(self, resource: str, action: str, scope: PermissionScope) -> Permission | None:
        return self.db.scalar(
            select(Permission)
            .where(Permission.resource == resource)
            .where(Permission.action == action)
            .where(Permission.scope == scope)
        )

    @cached({})
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

    def clear_caches(self):
        self.default_base_permissions.cache_clear()
        self.bit_offset.cache_clear()
        self.permission_from_offset.cache_clear()
        self.scope_mask.cache_clear()


class PermissionSet:
    """
    Represents a bitfield-based permission set.
    """

    def __init__(self, registry: PermissionRegistry | None = None):
        from .core import permission_registry
        self.mask = 0
        self.registry = registry if registry is not None else permission_registry()

    @classmethod
    def from_mask(cls, mask: int | str) -> Self:
        """Creates a PermissionSet instance from a given bitfield integer."""

        # TODO: the order of the bits is flipped in db??

        if isinstance(mask, str):
            mask = int(mask[::-1], 2)
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

    def collapse_scope(self):
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

    def empty(self):
        return self.mask == 0

    def __setitem__(self, key: Permission, value: bool):
        bit_pos = self.registry.bit_offset(key.resource, key.action, key.scope)
        if bit_pos is None:
            raise ValueError(f"Permission {key} cannot be represented")

        if value:
            self.mask |= (1 << bit_pos)
        else:
            self.mask &= ~(1 << bit_pos)

    def __contains__(self, item: Permission) -> bool:
        bit_pos = self.registry.bit_offset(item.resource, item.action, item.scope)
        if bit_pos is None:
            return False

        return bool(self.mask & (1 << bit_pos))

    def __eq__(self, other: PermissionSet) -> bool:
        return self.mask == other.mask

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
                perm = self.registry.permission_from_offset(bit_pos)
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
    sql.Column("is_deny", sql.Boolean, nullable=False, default=False),
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
        if self == PermissionScope.ANY:
            return "*"
        return self.name.lower()

    @classmethod
    def from_str(cls, raw_scope):
        if raw_scope is None or raw_scope == "*":
            return cls.ANY
        return cls[raw_scope.upper()]


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    resource: Mapped[str] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    scope: Mapped[PermissionScope] = mapped_column(sql.Enum(PermissionScope))
    description: Mapped[str | None] = mapped_column()
    bit_offset: Mapped[int] = mapped_column(default=0)

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

    def validate(self, db: orm.Session) -> bool:
        """Validates that the permission exists in the database."""
        return db.execute(
            exists()
            .where(Permission.resource == self.resource,
                   Permission.action == self.action,
                   Permission.scope == self.scope)
            .select()
        ).scalar_one()

    def __str__(self):
        return f"{self.resource}:{self.action}:{self.scope if self.scope else '*'}"


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
    allow_mask: Mapped[int] = mapped_column(BIT(BITSTRING_LENGTH), server_default=DEFAULT_BITS)

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
    allow_mask: Mapped[int] = mapped_column(BIT(BITSTRING_LENGTH), server_default=DEFAULT_BITS)
    deny_mask: Mapped[int] = mapped_column(BIT(BITSTRING_LENGTH), server_default=DEFAULT_BITS)

# TODO: compute masks
