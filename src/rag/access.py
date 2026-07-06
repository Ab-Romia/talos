from uuid import UUID

from sqlalchemy import select, or_


def accessible_channel_ids(db, user_id: UUID, workspace_id: UUID) -> set[UUID]:
    from chat.realtime import _get_accessible_channels
    from workspace.model import Channel

    visible = _get_accessible_channels(db, user_id)
    ws_channels = set(
        db.scalars(
            select(Channel.id).where(
                Channel.workspace_id == workspace_id,
                Channel.deleted_at.is_(None),
            )
        )
    )
    return visible & ws_channels


def accessible_file_ids(db, user_id: UUID, workspace_id: UUID,
                        channel_id: UUID | None = None) -> set[UUID]:
    """
    Files the AI may retrieve for a user asking in a given conversation.

    Scope is deliberately narrow and matches what the user can see in the UI:
      - workspace **documents** (File.channel_id IS NULL) — if the user may read
        workspace files (owners always may), and
      - the **current conversation's own attachments** (File.channel_id == channel_id)
        — only if the user can access that channel/DM/group.

    Nothing else: no other channels' attachments, and no owner "see everything"
    bypass (which would otherwise leak other users' private DM/group files).
    """
    from filesystem.model import File
    from permissions import user_perms, ScopedPermission
    from workspace.model import Workspace
    from chat.realtime import _get_accessible_channels

    base = select(File.id).where(
        File.workspace_id == workspace_id,
        File.deleted_at.is_(None),
    )
    conds = []

    ws = db.get(Workspace, workspace_id)
    is_owner = ws is not None and ws.owner_id == user_id
    perms = user_perms(user_id=user_id, workspace_id=workspace_id, channel_id=None, db=db)
    if is_owner or ScopedPermission.from_str("files:read") in perms.iter(db):
        conds.append(File.channel_id.is_(None))

    if channel_id is not None and channel_id in _get_accessible_channels(db, user_id):
        conds.append(File.channel_id == channel_id)

    if not conds:
        return set()
    return set(db.scalars(base.where(or_(*conds))))
