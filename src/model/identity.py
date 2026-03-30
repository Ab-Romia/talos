import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Table, Column, ForeignKey, Enum, Uuid, func, event
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import cfg
from model import Base

users_platform_roles = Table(
    "users_platform_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False, index=True)

    name: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column(default={})
    roles: Mapped[list["PlatformRole"]] = relationship("PlatformRole",
                                                       secondary="users_platform_roles",
                                                       back_populates="users")
    uploaded_files: Mapped[list["FileAttachment"]] = relationship("FileAttachment", back_populates="uploader")


class OTP(Base):
    __tablename__ = "otp"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None)
    code: Mapped[str] = mapped_column()


# class UserPassword(Base):
#     __tablename__ = "user_passwords"
#     user_id: Mapped[Uuid] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
#     hashed_password: Mapped[str] = mapped_column()
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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


class PlatformRole(Base):
    __tablename__ = "platform_roles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
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
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None] = mapped_column()


class OAuth2Token(BaseModel):
    token_type: TokenType
    access_token: str = Field(..., max_length=512)
    refresh_token: str = Field(..., max_length=512)
    expires_at: datetime
