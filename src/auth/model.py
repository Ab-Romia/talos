import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, TYPE_CHECKING

import sqlalchemy as sql
from sqlalchemy import Uuid, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from permissions.model import Role
    from workspace.model import Workspace
    from filesystem.model import File


class Issuer(PyEnum):
    password = "/api/auth/password"
    totp = "/api/auth/totp"
    oauth = "/api/auth/oauth"
    passkey = "/api/auth/passkey"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    username: Mapped[str] = mapped_column(CITEXT(32), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(CITEXT(), unique=True, index=True)
    signup_complete: Mapped[bool] = mapped_column(default=False, index=True)
    name: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    data: Mapped[dict[str, Any]] = mapped_column(default={})

    identity_providers: Mapped[list["IdentityProvider"]] = relationship("IdentityProvider",
                                                                        back_populates="user",
                                                                        cascade="all, delete-orphan")
    workspaces: Mapped[list["Workspace"]] = relationship(
        secondary="workspace_members",
        back_populates="members")
    roles: Mapped[list[Role]] = relationship(secondary="users_roles", back_populates="users")
    uploaded_files: Mapped[list[File]] = relationship(
        "File",
        back_populates="uploader",
        cascade="all, delete-orphan",
    )

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
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey(User.id, ondelete="CASCADE"), index=True)
    issuer: Mapped[Issuer] = mapped_column(sql.Enum(Issuer), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(default={})
    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(sql.DateTime(), default=None)

    user = relationship("User", back_populates="identity_providers")


class ProviderToken(Base):
    """Persisted OAuth tokens for third-party API access (e.g., Google Drive).

    Distinct from IdentityProvider, which only stores the OIDC claims used
    for sign-in. One row per (user, provider).
    """
    __tablename__ = "provider_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(index=True)
    access_token: Mapped[str] = mapped_column()
    refresh_token: Mapped[str | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(sql.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    last_used_at: Mapped[datetime] = mapped_column(sql.DateTime(timezone=True), default=sql.func.now())
    user_agent: Mapped[str | None] = mapped_column()
