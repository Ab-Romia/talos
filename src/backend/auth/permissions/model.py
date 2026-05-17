import functools
import uuid
from enum import Enum as PyEnum
from functools import cached_property

import sqlalchemy as sql
from sqlalchemy import UniqueConstraint, Sequence, update, and_, event, select, not_, CheckConstraint, func
from sqlalchemy.dialects.postgresql import BIT, BitString, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship, foreign

from config import cfg
from model import Base
from model.messaging import Workspace, Channel

EVERYONE_ID = uuid.UUID(int=0)
DEFAULT_BITS = BitString.from_int(0, length=cfg().auth.permission_bitstring_length)


@functools.total_ordering
class PermissionScope(PyEnum):
    OWN = 0
    CHANNEL = 1
    WORKSPACE = 2
    ANY = 3  # Any must be last

    def __lt__(self, other: PermissionScope) -> bool:
        return self.value < other.value

    def __str__(self):
        if self == PermissionScope.ANY:
            return "*"
        return self.name.lower()

    @cached_property
    def offset(self) -> int:
        return self.value * self.max_bit_length()

    @classmethod
    def max_bit_length(cls) -> int:
        return cfg().auth.permission_bitstring_length // len(cls)

    @cached_property
    def mask(self) -> int:
        return ((1 << self.max_bit_length()) - 1) << self.offset

    @classmethod
    def from_str(cls, raw_scope):
        if raw_scope is None or raw_scope == "*":
            return cls.ANY
        return cls[raw_scope.upper()]


users_roles = sql.Table(
    "users_roles", Base.metadata,
    sql.Column("user_id", sql.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sql.Column("role_id", sql.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey("roles.id", ondelete="CASCADE"))
    permission_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey("permissions.id", ondelete="CASCADE"))
    channel_id: Mapped[uuid.UUID | None] = mapped_column(sql.ForeignKey("channels.id", ondelete="CASCADE"),
                                                         default=None)
    scope: Mapped[PermissionScope] = mapped_column(sql.Enum(PermissionScope), nullable=False)
    is_deny: Mapped[bool] = mapped_column(sql.Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", "channel_id", "scope", name="uq_role_perm_chan_scope"),
        CheckConstraint(not_(sql.and_(channel_id.is_(None), is_deny)), name="chk_no_deny_for_global_perms")
    )

    permission = relationship("Permission", backref="role_associations")
    role = relationship("Role", back_populates="permissions", overlaps="permissions,permission_overrides")
    channel = relationship("Channel")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    resource: Mapped[str] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    allowed_scopes: Mapped[list[PermissionScope]] = mapped_column(ARRAY(sql.Enum(PermissionScope)))
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
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()

    # TODO: consider UUID = 0 instead?
    # `workspace_id` == None: a global role, applies to the entire app
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(sql.ForeignKey(Workspace.id, ondelete="CASCADE"),
                                                           index=True,
                                                           default=None)

    priority: Mapped[int] = mapped_column(index=True, default=0)

    # PERF: Precomputed bitfields, recomputed on permission or role changes
    allow_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=DEFAULT_BITS)

    workspace = relationship("Workspace", back_populates="roles")
    users = relationship("User", secondary=users_roles, back_populates="roles")
    permissions: Mapped[list[RolePermission]] = relationship(
        RolePermission,
        back_populates="role",
        cascade="all, delete-orphan",
        overlaps="role,permission_overrides",
    )

    __table_args__ = (
        UniqueConstraint(workspace_id, name),
    )


class ChannelRoleOverride(Base):
    __tablename__ = "role_overrides"

    role_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(Role.id, ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(Channel.id, ondelete="CASCADE"), primary_key=True)

    permission_overrides: Mapped[list[RolePermission]] = relationship(
        RolePermission,
        primaryjoin=and_(
            foreign(RolePermission.role_id) == role_id,
            foreign(RolePermission.channel_id) == channel_id,
        ),
        cascade="all, delete-orphan",
        overlaps="role,permissions,channel",
    )

    # PERF: Precomputed bitfield, recomputed on permission or role changes
    allow_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=DEFAULT_BITS)
    deny_mask: Mapped[BitString] = mapped_column(BIT(cfg().auth.permission_bitstring_length), default=DEFAULT_BITS)


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
