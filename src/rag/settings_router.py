"""Workspace/channel AI-config endpoints (rag-owned).

GET returns the resolved effective config + raw overrides + provenance.
PATCH validates against the AiConfigPatch whitelist; null clears a key.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import AsyncSessionLocal
from rag.ai_settings import AiConfigPatch, AiSettings, OVERRIDABLE, resolve_ai_config
from workspace import require_perms as require
from workspace.model import Channel

workspace_ai = APIRouter(tags=["rag"])
channel_ai = APIRouter(tags=["rag"])


def _view(workspace_id: UUID, channel_id: UUID | None):
    """Resolved view for a scope — runs sync DB reads via a short session."""
    from database import SessionLocal
    with SessionLocal() as db:
        cfg, prov = resolve_ai_config(workspace_id, channel_id, db)
        row = db.scalar(
            select(AiSettings)
            .where(AiSettings.workspace_id == workspace_id)
            .where(AiSettings.channel_id.is_(None) if channel_id is None
                   else AiSettings.channel_id == channel_id))
        overrides = dict(row.overrides) if row else {}
    return {
        "effective": {k: getattr(cfg, k) for k in OVERRIDABLE},
        "overrides": overrides,
        "provenance": prov,
    }


def _apply_patch(workspace_id: UUID, channel_id: UUID | None, patch: AiConfigPatch):
    from database import SessionLocal
    delta = patch.model_dump(exclude_unset=True)  # null values present = clear

    def _merge_into(overrides: dict | None) -> dict:
        merged = dict(overrides or {})
        for k, v in delta.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        return merged

    def _scope_row(db):
        return db.scalar(
            select(AiSettings)
            .where(AiSettings.workspace_id == workspace_id)
            .where(AiSettings.channel_id.is_(None) if channel_id is None
                   else AiSettings.channel_id == channel_id))

    with SessionLocal() as db:
        row = _scope_row(db)
        if row is None:
            row = AiSettings(workspace_id=workspace_id, channel_id=channel_id, overrides={})
            db.add(row)
        row.overrides = _merge_into(row.overrides)
        try:
            db.commit()
        except IntegrityError:
            # Check-then-insert race: a concurrent first-PATCH created the scope
            # row between our select and commit (unique constraint fired). The
            # row now exists, so one retry — re-select and merge into it.
            db.rollback()
            row = _scope_row(db)
            row.overrides = _merge_into(row.overrides)
            db.commit()


@workspace_ai.get("/ai/config", dependencies=[require("workspace:view")])
async def get_workspace_ai_config(workspace_id: UUID):
    return _view(workspace_id, None)


@workspace_ai.patch("/ai/config", dependencies=[require("workspace.role:manage")])
async def patch_workspace_ai_config(workspace_id: UUID, patch: AiConfigPatch):
    _apply_patch(workspace_id, None, patch)
    return _view(workspace_id, None)


async def _channel_workspace(channel_id: UUID) -> UUID:
    async with AsyncSessionLocal() as db:
        ws = await db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if ws is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return ws


@channel_ai.get("/ai/config", dependencies=[require("channel:view")])
async def get_channel_ai_config(channel_id: UUID):
    ws = await _channel_workspace(channel_id)
    return _view(ws, channel_id)


@channel_ai.patch("/ai/config", dependencies=[require("workspace.role:manage")])
async def patch_channel_ai_config(channel_id: UUID, patch: AiConfigPatch):
    ws = await _channel_workspace(channel_id)
    _apply_patch(ws, channel_id, patch)
    return _view(ws, channel_id)
