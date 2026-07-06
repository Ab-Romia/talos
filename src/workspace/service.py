"""
Service module for workspace and channel operations.
Handles business logic for workspace/channel management, member management, etc.
"""
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.model import User
from workspace.model import Workspace, Channel


class WorkspaceService:
    """Service for managing workspace operations."""

    @staticmethod
    def get_workspace(db: Session, workspace_id: uuid.UUID) -> Optional[Workspace]:
        """Get a workspace by ID."""
        return db.get(Workspace, workspace_id)

    @staticmethod
    def update_workspace_name(db: Session, workspace_id: uuid.UUID, name: str) -> Workspace:
        """Update workspace name."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")
        workspace.name = name
        db.commit()
        db.refresh(workspace)
        return workspace

    @staticmethod
    def update_workspace_description(db: Session, workspace_id: uuid.UUID, description: Optional[str]) -> Workspace:
        """Update workspace description."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")
        workspace.description = description
        db.commit()
        db.refresh(workspace)
        return workspace

    @staticmethod
    def update_workspace_icon(db: Session, workspace_id: uuid.UUID, icon_id: Optional[uuid.UUID]) -> Workspace:
        """Update workspace icon."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")
        workspace.icon_id = icon_id
        db.commit()
        db.refresh(workspace)
        return workspace

    @staticmethod
    def add_workspace_member(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Workspace:
        """Add a member to workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        user = db.get(User, user_id)
        if user is None:
            raise ValueError("User not found")

        if user not in workspace.members:
            workspace.members.append(user)
            db.commit()
            db.refresh(workspace)

        return workspace

    @staticmethod
    def _unlink_workspace_roles(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID):
        """Remove the user's assignments to every role belonging to the workspace."""
        from permissions.model import Role, users_roles

        db.execute(
            users_roles.delete().where(
                users_roles.c.user_id == user_id,
                users_roles.c.role_id.in_(
                    select(Role.id).where(Role.workspace_id == workspace_id)
                ),
            )
        )

    @staticmethod
    def remove_workspace_member(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Workspace:
        """Remove a member from workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        user = db.get(User, user_id)
        if user is None:
            raise ValueError("User not found")

        if user in workspace.members:
            workspace.members.remove(user)
            WorkspaceService._unlink_workspace_roles(db, workspace_id, user_id)
            db.commit()
            db.refresh(workspace)

        return workspace

    @staticmethod
    def get_workspace_members(db: Session, workspace_id: uuid.UUID) -> list[User]:
        """Get all members of a workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")
        return workspace.members

    @staticmethod
    def leave_workspace(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Leave a workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        if workspace.owner_id == user_id:
            raise ValueError("Owner cannot leave workspace")

        user = db.get(User, user_id)
        if user is None:
            raise ValueError("User not found")

        if user in workspace.members:
            workspace.members.remove(user)
            WorkspaceService._unlink_workspace_roles(db, workspace_id, user_id)
            db.commit()
            return True

        return False

    @staticmethod
    def delete_workspace(db: Session, workspace_id: uuid.UUID) -> bool:
        """Delete a workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        db.delete(workspace)
        db.commit()
        return True

    @staticmethod
    def create_channel(db: Session, workspace_id: uuid.UUID, name: str,
                      description: Optional[str] = None, is_public: bool = True) -> Channel:
        """Create a new channel in a workspace."""
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        channel = Channel(
            name=name,
            description=description,
            workspace_id=workspace_id,
            is_public=is_public
        )
        db.add(channel)
        db.commit()
        db.refresh(channel)
        return channel


class ChannelService:
    """Service for managing channel operations."""

    @staticmethod
    def get_channel(db: Session, channel_id: uuid.UUID) -> Optional[Channel]:
        """Get a channel by ID."""
        return db.get(Channel, channel_id)

    @staticmethod
    def rename_channel(db: Session, channel_id: uuid.UUID, name: str) -> Channel:
        """Rename a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.name = name
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def update_channel_description(db: Session, channel_id: uuid.UUID, description: Optional[str]) -> Channel:
        """Update channel description."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.description = description
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def toggle_channel_public(db: Session, channel_id: uuid.UUID, is_public: bool) -> Channel:
        """Toggle channel between public/private."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.is_public = is_public
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def mute_channel(db: Session, channel_id: uuid.UUID) -> Channel:
        """Mute a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.is_muted = True
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def unmute_channel(db: Session, channel_id: uuid.UUID) -> Channel:
        """Unmute a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.is_muted = False
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def archive_channel(db: Session, channel_id: uuid.UUID) -> Channel:
        """Archive a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.is_archived = True
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def unarchive_channel(db: Session, channel_id: uuid.UUID) -> Channel:
        """Unarchive a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")
        channel.is_archived = False
        db.commit()
        db.refresh(channel)
        return channel

    @staticmethod
    def delete_channel(db: Session, channel_id: uuid.UUID) -> bool:
        """Delete a channel."""
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError("Channel not found")

        db.delete(channel)
        db.commit()
        return True

    @staticmethod
    def get_workspace_channels(db: Session, workspace_id: uuid.UUID) -> list[Channel]:
        """Get all channels in a workspace (direct messages are never listed)."""
        return db.scalars(
            select(Channel)
            .where(Channel.workspace_id == workspace_id)
            .where(Channel.is_direct.is_(False))
        ).all()

