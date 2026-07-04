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


def accessible_file_ids(db, user_id: UUID, workspace_id: UUID) -> set[UUID]:
    from filesystem.model import File
    from permissions import user_perms, ScopedPermission
    from workspace.model import Workspace

    base = select(File.id).where(
        File.workspace_id == workspace_id,
        File.deleted_at.is_(None),
    )

    ws = db.get(Workspace, workspace_id)
    if ws is not None and ws.owner_id == user_id:
        return set(db.scalars(base))

    conds = []
    channel_ids = accessible_channel_ids(db, user_id, workspace_id)
    if channel_ids:
        conds.append(File.channel_id.in_(channel_ids))

    perms = user_perms(user_id=user_id, workspace_id=workspace_id, channel_id=None, db=db)
    if ScopedPermission.from_str("files:read") in perms.iter(db):
        conds.append(File.channel_id.is_(None))

    if not conds:
        return set()
    return set(db.scalars(base.where(or_(*conds))))
