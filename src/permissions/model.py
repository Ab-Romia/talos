import uuid
from enum import Enum as PyEnum
from typing import Iterable, Self, Generator

from pydantic import BaseModel
from pydantic_core import core_schema
from sqlalchemy import Enum, Table, Uuid, Column, ForeignKey, Boolean, orm, and_
from sqlalchemy import UniqueConstraint, Sequence, update, event, select, CheckConstraint, func
from sqlalchemy.dialects.postgresql import BIT, BitString, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship, foreign

from config import cfg
from database import Base

STATIC_ROLE_ID = uuid.UUID(int=0)
DEFAULT_EVERYONE_ROLE_ID = uuid.UUID(int=1)


def system_roles():
    """Defines the default system roles that are created on application initialization."""
    return [
        Role(
            id=STATIC_ROLE_ID,
            name="static",
            description="A reserved role for static permissions that cannot be overridden",
            workspace_id=None,
            priority=0,
        ),
        Role(
            id=DEFAULT_EVERYONE_ROLE_ID,
            name="everyone",
            description="Default role, contains the initial permissions for the everyone role."
                        "Every workspace gets a copy of this role on creation",
            workspace_id=None,
            priority=1,
        ),
    ]


def _default_bits():
    return BitString.from_int(0, length=cfg().auth.permission_bitstring_length)


class PermissionSet(int):
    """ Represents a bitfield-based permission set directly as a Python int. """

    def __new__(cls, bitstring: int | str | any = 0) -> PermissionSet:
        if isinstance(bitstring, str) or isinstance(bitstring, BitString):
            val = int(bitstring, 2)
        else:
            val = int(bitstring)

        return super().__new__(cls, val)  # type: ignore

    def empty(self) -> bool:
        return self == 0

    def __or__(self, other: int) -> PermissionSet:
        return PermissionSet(super().__or__(other))

    def __and__(self, other: int) -> PermissionSet:
        return PermissionSet(super().__and__(other))

    def __xor__(self, other: int) -> PermissionSet:
        return PermissionSet(super().__xor__(other))

    def __sub__(self, other: int) -> PermissionSet:
        return PermissionSet(self & ~other)

    def __len__(self) -> int:
        return bin(self).count("1")

    @property
    def bitstring(self) -> BitString:
        return BitString.from_int(self, cfg().auth.permission_bitstring_length)

    def iter(self, db: orm.Session) -> Generator[ScopedPermission, None, None]:
        from .service import permission_from_offset

        mask = int(self)
        bit_pos = 0

        while mask:
            if mask & 1:
                perm = permission_from_offset(db, bit_pos)
                if perm:
                    yield perm
            mask >>= 1
            bit_pos += 1

    def as_owner(self, is_owner: bool) -> "PermissionSet":
        """Workspace owners have all permissions; bypass bitfield checks entirely."""
        if is_owner:
            return PermissionSet((1 << cfg().auth.permission_bitstring_length) - 1)
        return self

    @classmethod
    def from_permissions(cls, permissions: Iterable[ScopedPermission | str] | ScopedPermission,
                         db: orm.Session) -> "PermissionSet":
        """Creates a PermissionSet instance from a list of Permission objects."""
        from .service import bit_offset

        if isinstance(permissions, ScopedPermission) or isinstance(permissions, str):
            permissions = [permissions]

        mask = 0
        for perm in permissions:
            if isinstance(perm, str):
                perm = ScopedPermission.from_str(perm)

            bit_pos = bit_offset(db, perm)
            if bit_pos is None:
                raise ValueError(f"Permission {perm} cannot be represented")
            mask |= (1 << bit_pos)
        return cls(mask)


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


class PermissionScope(PyEnum):
    ANY = 0
    OWN = 1

    def __lt__(self, other: PermissionScope) -> bool:
        return self.value < other.value

    def __str__(self):
        if self == PermissionScope.ANY:
            return "*"
        return self.name.lower()

    @property
    def offset(self) -> int:
        return self.value * self.max_bit_length()

    @classmethod
    def max_bit_length(cls) -> int:
        return cfg().auth.permission_bitstring_length // len(cls)

    @property
    def mask(self) -> int:
        return ((1 << self.max_bit_length()) - 1) << self.offset

    @classmethod
    def from_str(cls, raw_scope):
        if raw_scope is None or raw_scope == "*":
            return cls.ANY
        return cls[raw_scope.upper()]


users_roles = Table(
    "users_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"))
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), default=None)
    scope: Mapped[PermissionScope] = mapped_column(Enum(PermissionScope), nullable=False, default=PermissionScope.ANY)
    is_deny: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", "channel_id", "scope", name="uq_role_perm_chan_scope"),
        CheckConstraint(~(channel_id.is_(None) & is_deny), name="chk_no_deny_for_global_perms")
    )

    permission = relationship("Permission", backref="role_associations")
    role = relationship("Role", overlaps="permissions,permission_overrides")
    channel = relationship("Channel")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    resource: Mapped[str] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    allowed_scopes: Mapped[list[PermissionScope]] = mapped_column(ARRAY(Enum(PermissionScope)),
                                                                  default=[PermissionScope.ANY])
    description: Mapped[str | None] = mapped_column()
    bit_offset: Mapped[int] = mapped_column(Sequence(
        "permission_bit_offset_seq",
        metadata=Base.metadata,
        start=0,
        minvalue=0,
        maxvalue=cfg().auth.permission_bitstring_length // len(PermissionScope) - 1
    ), index=True, unique=True)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()

    # `workspace_id` == None: a global role, applies to the entire app
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"),
                                                           index=True,
                                                           default=None)

    priority: Mapped[int] = mapped_column(index=True, default=0)

    # PERF: Precomputed bitfields, recomputed on permission or role changes
    allow_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=_default_bits)

    workspace = relationship("Workspace", back_populates="roles")
    users = relationship("User", secondary=users_roles, back_populates="roles")
    permissions: Mapped[list[RolePermission]] = relationship(
        RolePermission,
        primaryjoin=lambda: and_(
            foreign(RolePermission.role_id) == Role.id,
            RolePermission.channel_id.is_(None),
        ),
        cascade="all, delete-orphan",
        overlaps="role,permission_overrides",
    )

    __table_args__ = (
        UniqueConstraint(workspace_id, name),
    )


class ChannelRoleOverride(Base):
    __tablename__ = "role_overrides"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Role.id, ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True)

    permission_overrides: Mapped[list[RolePermission]] = relationship(
        RolePermission,
        primaryjoin=(foreign(RolePermission.role_id) == role_id)
                    & (foreign(RolePermission.channel_id) == channel_id),
        cascade="all, delete-orphan",
        overlaps="role,permissions,channel",
    )

    # PERF: Precomputed bitfield, recomputed on permission or role changes
    allow_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=_default_bits)
    deny_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=_default_bits)

    channel = relationship("Channel", back_populates="roles_overrides")


def _apply_mask_update(connection, target: RolePermission, enabled: int):
    offset_expr = cfg().auth.permission_bitstring_length - (
        select(Permission.bit_offset)
        .where(Permission.id == target.permission_id)
    ).scalar_subquery() - target.scope.offset - 1

    if target.channel_id is None:
        connection.execute(
            update(Role)
            .where(Role.id == target.role_id)
            .values(allow_mask=func.set_bit(Role.allow_mask, offset_expr, enabled))
        )
    else:
        mask_field = ChannelRoleOverride.deny_mask if target.is_deny else ChannelRoleOverride.allow_mask
        connection.execute(
            update(ChannelRoleOverride)
            .where(ChannelRoleOverride.role_id == target.role_id)
            .where(ChannelRoleOverride.channel_id == target.channel_id)
            .values({mask_field: func.set_bit(mask_field, offset_expr, enabled)})
        )


@event.listens_for(RolePermission, "after_insert")
def after_insert(_mapper, connection, target):
    _apply_mask_update(connection, target, enabled=1)


@event.listens_for(RolePermission, "after_delete")
def after_delete(_mapper, connection, target):
    _apply_mask_update(connection, target, enabled=0)
