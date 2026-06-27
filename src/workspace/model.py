import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func, Uuid, event, UniqueConstraint
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import mapped_column, Mapped, relationship, object_session

from filesystem.model import File
from model import Base

if TYPE_CHECKING:
    from chat.model import Message


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    owner = relationship("User")
    channels: Mapped[list[Channel]] = relationship("Channel", back_populates="workspace", cascade="all, delete-orphan")
    members = relationship("User", secondary="workspace_members", back_populates="workspaces")
    files: Mapped[list[File]] = relationship("File", back_populates="workspace")

    roles: Mapped[list[Role]] = relationship(  # type: ignore[forward-reference]
        "Role",
        order_by="Role.priority",
        collection_class=ordering_list("priority"),
        back_populates="workspace",
        cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="channel", cascade="all, delete-orphan")
    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="channels")
    files: Mapped[list[File]] = relationship("File", back_populates="channel",
                                             foreign_keys="File.channel_id",
                                             cascade="all, delete-orphan")
    roles_overrides: Mapped[list["ChannelOverrides"]] = relationship(  # type: ignore[forward-reference]
        "ChannelRoleOverride",
        back_populates="channel",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_channel_workspace"),
        UniqueConstraint("name", "workspace_id", name="uq_channel_name_workspace")
    )


@event.listens_for(Workspace, "after_insert")
def after_insert_ws(_mapper, _connection, target):
    from permissions.model import Role, DEFAULT_EVERYONE_ROLE_ID
    db_session = object_session(target)

    if db_session is None:
        raise RuntimeError("No session found for after_insert event. This should not happen.")

    default_everyone = db_session.get(Role, DEFAULT_EVERYONE_ROLE_ID)
    target.roles.append(
        Role(id=target.id,
             name="everyone",
             permissions=default_everyone.permissions,
             allow_mask=default_everyone.allow_mask,
             workspace_id=target.id,
             priority=0)
    )
    target.members.append(target.owner)


@event.listens_for(Channel, "after_insert")
def after_insert_channel(_mapper, _connection, target):
    from permissions.model import ChannelRoleOverride

    target.roles_overrides.append(
        ChannelRoleOverride(role_id=target.workspace_id, channel_id=target.id)
    )
