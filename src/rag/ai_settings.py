"""Per-workspace (and per-channel) AI configuration.

One rag-owned table of whitelisted overrides layered over global_rag_config:
global -> workspace default (channel_id IS NULL) -> channel override.
Resolution returns a real RagConfig (model_copy), so the existing config=
seam and RagTrace.effective_config stay honest by construction.
"""

import uuid
from datetime import datetime

import sqlalchemy as sql
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import ForeignKey, Index, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from config import RagConfig, global_rag_config
from database import Base
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = ["AiSettings", "AiConfigPatch", "OVERRIDABLE", "resolve_ai_config"]

OVERRIDABLE: tuple[str, ...] = (
    "use_hyde", "use_query_rewrite", "use_reranking",
    "retrieval_top_k", "rerank_fetch_k",
    "chat_recall_k", "chat_recall_fetch_k",
    "chat_decay_half_life_hours", "chat_recall_overlap_threshold",
    "llm_temperature", "openai_model",
)


class AiSettings(Base):
    __tablename__ = "ai_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", name="uq_ai_settings_scope"),
        # Postgres treats NULLs as distinct, so the composite constraint can't
        # guard the workspace-default row — a partial unique index does.
        Index("uq_ai_settings_ws_default", "workspace_id",
              unique=True, postgresql_where=sql.text("channel_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(sql.Uuid, primary_key=True, default=uuid.uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"))
    overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        sql.DateTime(timezone=True), default=sql.func.now(), onupdate=sql.func.now())


class AiConfigPatch(BaseModel):
    """Whitelisted, bounded overrides. extra='forbid' IS the blacklist."""
    model_config = ConfigDict(extra="forbid")

    use_hyde: bool | None = None
    use_query_rewrite: bool | None = None
    use_reranking: bool | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1, le=50)
    rerank_fetch_k: int | None = Field(default=None, ge=1, le=100)
    chat_recall_k: int | None = Field(default=None, ge=0, le=10)
    chat_recall_fetch_k: int | None = Field(default=None, ge=1, le=50)
    chat_decay_half_life_hours: float | None = Field(default=None, ge=1, le=8760)
    chat_recall_overlap_threshold: float | None = Field(default=None, ge=0, le=1)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    openai_model: str | None = None

    @field_validator("openai_model")
    @classmethod
    def _model_vetted(cls, v):
        if v is not None and v not in global_rag_config.ai_model_allow_list:
            raise ValueError(f"model not in allow-list: {v}")
        return v


def _clean(overrides: dict, workspace_id: uuid.UUID | None = None) -> dict:
    """Keep only whitelisted keys whose values still pass AiConfigPatch
    validation (defense in depth — rows are validated on write, but
    model_copy(update=...) does NOT re-validate, so stale/poisoned rows must
    never reach the resolved RagConfig: wrong types, out-of-bounds values, or
    a model since removed from the allow-list are dropped per key)."""
    cleaned: dict = {}
    for k, v in (overrides or {}).items():
        if k not in OVERRIDABLE or v is None:
            continue
        try:
            # NOTE: per-key validation — if a cross-field validator is ever
            # added to AiConfigPatch, this would miss it (validate the whole
            # layer at once then).
            patch = AiConfigPatch(**{k: v})
        except ValidationError:
            logger.warning(
                "dropping invalid ai_settings override "
                f"(workspace_id={workspace_id}, key={k})")
            continue
        # Store the COERCED value, not the raw one: model_copy(update=...)
        # doesn't re-validate, so e.g. "9" must land as int 9 and "false"
        # as bool False — never as truthy strings.
        cleaned[k] = getattr(patch, k)
    return cleaned


def resolve_ai_config(
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    db: Session,
) -> tuple[RagConfig, dict]:
    """global -> workspace -> channel. Returns (effective config, provenance)."""
    rows = db.execute(
        select(AiSettings.channel_id, AiSettings.overrides)
        .where(AiSettings.workspace_id == workspace_id)
        .where(sql.or_(AiSettings.channel_id.is_(None),
                       AiSettings.channel_id == channel_id))
    ).all()
    ws_over: dict = {}
    ch_over: dict = {}
    for ch_id, overrides in rows:
        if ch_id is None:
            ws_over = _clean(overrides, workspace_id)
        elif channel_id is not None and ch_id == channel_id:
            ch_over = _clean(overrides, workspace_id)

    provenance = {k: "global" for k in OVERRIDABLE}
    provenance.update({k: "workspace" for k in ws_over})
    provenance.update({k: "channel" for k in ch_over})

    merged = {**ws_over, **ch_over}
    cfg = global_rag_config.model_copy(update=merged) if merged else global_rag_config
    return cfg, provenance
