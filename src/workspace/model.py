import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func, Uuid, event, UniqueConstraint
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import mapped_column, Mapped, relationship, object_session

from database import Base
from filesystem.model import File

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
    description: Mapped[str | None] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # use_alter breaks the workspaces<->files FK cycle (files.workspace_id points
    # back at workspaces) so create_all/drop_all can order the tables.
    icon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL", use_alter=True, name="fk_workspaces_icon_id_files"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    owner = relationship("User")
    channels: Mapped[list[Channel]] = relationship("Channel", back_populates="workspace", cascade="all, delete-orphan")
    members = relationship("User", secondary="workspace_members", back_populates="workspaces")
    files: Mapped[list[File]] = relationship("File", back_populates="workspace", foreign_keys="File.workspace_id")
    icon = relationship("File", foreign_keys=[icon_id])

    roles: Mapped[list[Role]] = relationship(  # type: ignore[forward-reference]
        "Role",
        order_by="Role.priority",
        collection_class=ordering_list("priority"),
        back_populates="workspace",
        cascade="all, delete-orphan"
    )


class DMParticipant(Base):
    """The two members of a direct-message conversation. Access to a DM channel
    is granted by rows here and NOTHING else — roles (and even the workspace
    owner) do not apply."""
    __tablename__ = "dm_participants"
    channel_id = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True)
    user_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    is_public: Mapped[bool] = mapped_column(default=True)
    is_muted: Mapped[bool] = mapped_column(default=False)
    is_archived: Mapped[bool] = mapped_column(default=False)

    # Direct-message conversation between exactly two workspace members.
    # dm_key = "min_uuid:max_uuid" makes the pair unique per workspace via the
    # (name, workspace_id) constraint (name is set to the key on creation).
    # Group conversations set both is_direct and is_group: they reuse the DM
    # participant/permission machinery (access is by DMParticipant rows only)
    # but hold N members and carry a display name in `description`.
    is_direct: Mapped[bool] = mapped_column(default=False)
    is_group: Mapped[bool] = mapped_column(default=False)
    dm_key: Mapped[str | None] = mapped_column(nullable=True, default=None)

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
