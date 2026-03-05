import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import DateTime, UUID, Table, Column, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.base import Base

users_platform_roles = Table(
    "users_platform_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False, index=True)

    name: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column()
    roles: Mapped[list["PlatformRole"]] = relationship("PlatformRole",
                                                       secondary="users_platform_roles",
                                                       back_populates="users")


class OTP(Base):
    __tablename__ = "otp"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)
    code: Mapped[str] = mapped_column()


# class UserPassword(Base):
#     __tablename__ = "user_passwords"
#     user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
#     hashed_password: Mapped[str] = mapped_column()
#     created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)


class Issuer(PyEnum):
    password = "/api/auth/password"
    totp = "/api/auth/totp"
    google = "/api/auth/google"
    github = "/api/auth/github"


class TokenType(PyEnum):
    bearer = "Bearer"


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[Issuer] = mapped_column(Enum(Issuer), index=True)
    sub: Mapped[str | None] = mapped_column()
    secret: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)


platform_roles_permissions = Table(
    "platform_role_permissions", Base.metadata,
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), index=True)


class PlatformRole(Base):
    __tablename__ = "platform_roles"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()
    permissions: Mapped[list["Permission"]] = relationship("Permission",
                                                           secondary="platform_role_permissions")
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="users_platform_roles",
        back_populates="roles"
    )


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()
