import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Uuid, DateTime, func
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import mapped_column, Mapped, relationship

from files.model import FileAttachment
from model import Base


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Workspace(Base):
    __tablename__ = "workspaces"

    def __init__(self, **kwargs):
        from backend.auth.permissions.model import Role
        from backend.auth.permissions import permission_registry

        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        super().__init__(**kwargs)

        default_everyone = permission_registry(None).default_everyone_role()
        self.roles.append(Role(
            id=self.id,
            name="everyone",
            permissions=default_everyone.permissions,
            # This must be set here as the event listener won't trigger for bulk inserts
            allow_mask=default_everyone.allow_mask,
        ))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    channels: Mapped[list[Channel]] = relationship("Channel", back_populates="workspace", cascade="all, delete-orphan")
    members = relationship("User", secondary="workspace_members", back_populates="workspaces")
    files: Mapped[list[FileAttachment]] = relationship("FileAttachment", back_populates="workspace")

    roles: Mapped[list[Role]] = relationship(  # type: ignore[forward-reference]
        "Role",
        order_by="Role.priority",
        collection_class=ordering_list("priority"),
        back_populates="workspace",
        cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from backend.auth.permissions.model import ChannelRoleOverride
        self.roles_overrides.append(ChannelRoleOverride(role_id=self.workspace_id, channel_id=self.id))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column()

    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan")
    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="channels")
    files: Mapped[list[FileAttachment]] = relationship("FileAttachment", back_populates="channel")
    roles_overrides: Mapped[list["ChannelOverrides"]] = relationship(  # type: ignore[forward-reference]
        "ChannelRoleOverride",
        back_populates="channel",
        cascade="all, delete-orphan"
    )
