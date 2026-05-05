import functools
import uuid
from datetime import datetime
from enum import Enum as PyEnum, auto
from typing import Any, Self

import sqlalchemy as sql
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, BIT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import cfg
from model import Base
from model.messaging import Workspace, Channel


class Issuer(PyEnum):
    password = "/api/auth/password"
    totp = "/api/auth/totp"
    oauth = "/api/auth/oauth"
    passkey = "/api/auth/passkey"


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
    OWN = auto()
    CHANNEL = auto()
    WORKSPACE = auto()
    ANY = auto()

    def __lt__(self, other: PermissionScope) -> bool:
        return self.value < other.value

    def __str__(self):
        return self.name.lower()

    @classmethod
    def from_str(cls, raw_scope) -> Self:
        if raw_scope is None or raw_scope == "*":
            return cls.ANY
        return cls[raw_scope.upper()]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(CITEXT(32), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    # TODO remove email_verified: users are only added to the database after verification
    signup_complete: Mapped[bool] = mapped_column(default=False, index=True)
    name: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column(default={})
    roles: Mapped[list["Role"]] = relationship(secondary=users_roles, back_populates=__tablename__)

    __table_args__ = (
        # Ensure that the emails and usernames are partitioned
        # Emails must contain an @, and usernames cannot contain @
        # no string can be both
        sql.CheckConstraint(
            sql.func.regexp_like(username, r"^[a-zA-Z][a-zA-Z0-9-]{3,}$"),
            name="username_format"
        ),
        sql.CheckConstraint(
            sql.text("primary_email LIKE '%@%'"),
            name="email_format"
        )
    )


class OTP(Base):
    __tablename__ = "otp"
    user_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(User.id, ondelete="CASCADE"), primary_key=True)
    verified_at: Mapped[datetime | None] = mapped_column(sql.DateTime(), default=None)
    code: Mapped[str] = mapped_column()


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(User.id, ondelete="CASCADE"), index=True)
    issuer: Mapped[Issuer] = mapped_column(sql.Enum(Issuer), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(default={})
    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(sql.DateTime(), default=None)

    user = relationship("User", backref="identity_providers")


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    last_used_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    user_agent: Mapped[str | None] = mapped_column()


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

    # PERF: Precomputed bitmasks, recomputed on permission or role changes
    allow_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length),
                                            name=f"allow_mask_{cfg().auth.permission_bitstring_version}",
                                            default=0)

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

    # PERF: Precomputed bitmasks, recomputed on permission or role changes
    allow_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length),
                                            name=f"allow_mask_{cfg().auth.permission_bitstring_version}",
                                            default=0)
    deny_mask: Mapped[int] = mapped_column(BIT(cfg().auth.permission_bitstring_length),
                                           name=f"deny_mask_{cfg().auth.permission_bitstring_version}",
                                           default=0)
