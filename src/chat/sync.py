"""Workspace-level realtime sync.

Channel rooms are only computed when a socket connects, so membership,
channel-list, role and DM changes are otherwise invisible to already-connected
clients. This module fans a lightweight ``workspace_sync`` signal out to each
affected user's personal room; the client reacts by refetching the relevant
list and reconnecting its socket to pick up newly-accessible (or now-removed)
rooms.
"""
import asyncio
import uuid
from typing import Iterable

from sqlalchemy import select

from database import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Capture the main event loop so sync request handlers can emit onto it."""
    global _loop
    _loop = loop


def _emit(user_ids: Iterable[uuid.UUID], payload: dict) -> None:
    from chat.realtime import sio

    loop = _loop
    if loop is None:
        return
    targets = {str(u) for u in user_ids if u is not None}
    for uid in targets:
        try:
            asyncio.run_coroutine_threadsafe(
                sio.emit("workspace_sync", payload, room=f"user:{uid}"), loop
            )
        except Exception:
            logger.debug("workspace_sync emit scheduling failed", exc_info=True)


def workspace_member_ids(db, workspace_id: uuid.UUID) -> set[uuid.UUID]:
    from workspace.model import Workspace, WorkspaceMember

    ids = set(db.scalars(
        select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
    ))
    owner = db.scalar(select(Workspace.owner_id).where(Workspace.id == workspace_id))
    if owner:
        ids.add(owner)
    return ids


def notify_workspace(db, workspace_id: uuid.UUID, resource: str, *,
                     action: str | None = None, name: str | None = None,
                     targets: Iterable[uuid.UUID] | None = None) -> None:
    """Signal a workspace change to its members (or an explicit ``targets`` set)."""
    payload = {"resource": resource, "workspace_id": str(workspace_id)}
    if action:
        payload["action"] = action
    if name:
        payload["name"] = name
    ids = set(targets) if targets is not None else workspace_member_ids(db, workspace_id)
    _emit(ids, payload)


def notify_workspace_id(workspace_id: uuid.UUID, resource: str, *,
                        action: str | None = None, name: str | None = None,
                        targets: Iterable[uuid.UUID] | None = None) -> None:
    """Like :func:`notify_workspace` but opens its own session to resolve members."""
    if targets is not None:
        payload = {"resource": resource, "workspace_id": str(workspace_id)}
        if action:
            payload["action"] = action
        if name:
            payload["name"] = name
        _emit(set(targets), payload)
        return
    with SessionLocal() as db:
        notify_workspace(db, workspace_id, resource, action=action, name=name)
