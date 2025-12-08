import uuid
from datetime import datetime
from typing import Optional, Any
from enum import Enum as PyEnum

from sqlalchemy import DateTime, UUID, Table, Column, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.model.base import Base

Base.registry.type_annotation_map[dict[str, Any]] = JSONB

users_platform_roles = Table(
    "users_platform_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column()
    roles: Mapped[list["PlatformRole"]] = relationship("PlatformRole",
                                                       secondary="user_platform_roles",
                                                       back_populates="users")


class AuthType(PyEnum):
    PASSWORD = "password"
    OAUTH = "oauth"
    SAML = "saml"
    LDAP = "ldap"


class AuthProvider(Base):
    __tablename__ = "auth_providers"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auth_type: Mapped[AuthType] = mapped_column(Enum(AuthType), nullable=False)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column()


platform_roles_permissions = Table(
    "platform_role_permissions", Base.metadata,
    Column("platform_role_id", ForeignKey("platform_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class PlatformRole(Base):
    __tablename__ = "platform_roles"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column()
    permissions: Mapped[list["Permission"]] = relationship("Permission",
                                                           secondary="platform_role_permissions")


class Permission(Base):
    __tablename__ = "permissions"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column()
