import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

import sqlalchemy as sql
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base


class Issuer(PyEnum):
    password = "/api/auth/password"
    totp = "/api/auth/totp"
    oauth = "/api/auth/oauth"
    passkey = "/api/auth/passkey"


class User(Base):
    from backend.auth.permissions.model import Role, users_roles
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
    roles: Mapped[list[Role]] = relationship(secondary=users_roles, back_populates=__tablename__)

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
