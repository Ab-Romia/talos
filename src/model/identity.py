import functools
import uuid
from datetime import datetime
from enum import Enum as PyEnum, auto
from typing import Any, Self

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Table, Column, ForeignKey, Enum, Uuid, func, CheckConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base

users_platform_roles = Table(
    "users_platform_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(CITEXT(32), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    # TODO remove email_verified: users are only added to the database after verification
    signup_complete: Mapped[bool] = mapped_column(default=False, index=True)
    name: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column(default={})
    roles: Mapped[list["Role"]] = relationship("Role",
                                               secondary="users_platform_roles",
                                               back_populates="users")

    __table_args__ = (
        # Ensure that the emails and usernames are partitioned
        # Emails must contain an @, and usernames cannot contain @
        # no string can be both
        CheckConstraint(
            func.regexp_like(username, r"^[a-zA-Z][a-zA-Z0-9-]{3,}$"),
            name="username_format"
        ),
        CheckConstraint(
            text("primary_email LIKE '%@%'"),
            name="email_format"
        )
    )


class OTP(Base):
    __tablename__ = "otp"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)
    code: Mapped[str] = mapped_column()


class Issuer(PyEnum):
    password = "/api/auth/password"
    totp = "/api/auth/totp"
    oauth = "/api/auth/oauth"
    passkey = "/api/auth/passkey"


class TokenType(PyEnum):
    bearer = "Bearer"


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[Issuer] = mapped_column(Enum(Issuer), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)


platform_roles_permissions = Table(
    "platform_role_permissions", Base.metadata,
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    user_agent: Mapped[str | None] = mapped_column()


class Role(Base):
    __tablename__ = "platform_roles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()
    permissions: Mapped[list["Permission"]] = relationship(secondary="platform_role_permissions")
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True,
                                                           default=None)
    priority: Mapped[int] = mapped_column(index=True, default=0)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True,
                                                         default=None)

    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="users_platform_roles",
        back_populates="roles"
    )


@functools.total_ordering
class PermissionScope(PyEnum, int):
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


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource: Mapped[str] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(index=True)
    scope: Mapped[PermissionScope] = mapped_column(Enum(PermissionScope), index=True)
    is_deny: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column()

    def covers(self, other: Permission) -> bool:
        if (self.resource != other.resource
                or self.action != other.action
                or self.scope < other.scope):
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
        :type perm_str: str
        :raises ValueError: If the resource or action part of the string is empty.
        :return: An instance of the class created based on the parsed permission string.
        :rtype: Self
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


class OAuth2Token(BaseModel):
    token_type: TokenType
    access_token: str = Field(..., max_length=512)
    refresh_token: str = Field(..., max_length=512)
    expires_at: datetime
