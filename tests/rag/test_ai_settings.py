"""ai_settings: whitelist validation, layered resolution, provenance."""
import uuid

import pytest
from pydantic import ValidationError

from config import RagConfig
from rag.ai_settings import AiConfigPatch, AiSettings, resolve_ai_config


def test_patch_rejects_non_whitelisted_field():
    with pytest.raises(ValidationError):
        AiConfigPatch(openai_api_key="steal-me")
    with pytest.raises(ValidationError):
        AiConfigPatch(chat_index_interval_minutes=1)


def test_patch_bounds():
    with pytest.raises(ValidationError):
        AiConfigPatch(retrieval_top_k=0)
    with pytest.raises(ValidationError):
        AiConfigPatch(llm_temperature=3.0)
    assert AiConfigPatch(retrieval_top_k=7).retrieval_top_k == 7


def test_patch_model_allow_list():
    with pytest.raises(ValidationError):
        AiConfigPatch(openai_model="arbitrary-model-9000")
    assert AiConfigPatch(openai_model="gpt-4o").openai_model == "gpt-4o"


def test_resolution_layers_and_provenance(db_session, test_channel):
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"use_hyde": False, "retrieval_top_k": 9}))
    db_session.add(AiSettings(workspace_id=ws, channel_id=test_channel.id,
                              overrides={"retrieval_top_k": 3}))
    db_session.commit()

    cfg, prov = resolve_ai_config(ws, test_channel.id, db_session)
    assert cfg.use_hyde is False                    # workspace layer
    assert cfg.retrieval_top_k == 3                 # channel wins
    assert prov["use_hyde"] == "workspace"
    assert prov["retrieval_top_k"] == "channel"
    assert prov["use_reranking"] == "global"

    cfg2, prov2 = resolve_ai_config(ws, None, db_session)
    assert cfg2.retrieval_top_k == 9                # workspace default only
    assert isinstance(cfg2, RagConfig)

    # cleanup
    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_resolution_drops_type_poisoned_override(db_session, test_channel):
    """model_copy(update=...) does not re-validate, so read-side cleaning must
    drop stale/poisoned values per key — valid keys in the same row survive."""
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"retrieval_top_k": "not-an-int",
                                         "use_hyde": False}))
    db_session.commit()

    from config import global_rag_config
    cfg, prov = resolve_ai_config(ws, None, db_session)
    assert cfg.use_hyde is False                    # valid key applied
    assert cfg.retrieval_top_k == global_rag_config.retrieval_top_k  # bad key dropped
    assert prov["use_hyde"] == "workspace"
    assert prov["retrieval_top_k"] == "global"      # provenance after cleaning

    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_resolution_drops_model_removed_from_allow_list(db_session, test_channel):
    """Allow-list narrowing must be retroactive: a stored model no longer in
    ai_model_allow_list falls back to the global model."""
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"openai_model": "removed-model-1"}))
    db_session.commit()

    from config import global_rag_config
    cfg, prov = resolve_ai_config(ws, None, db_session)
    assert cfg.openai_model == global_rag_config.openai_model
    assert prov["openai_model"] == "global"

    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_resolution_coerces_override_types(db_session, test_channel):
    """Coercible-but-wrong-typed row values must land COERCED, not raw:
    "9" -> int 9, "false" -> bool False (raw would be a truthy string)."""
    ws = test_channel.workspace_id
    db_session.add(AiSettings(workspace_id=ws, channel_id=None,
                              overrides={"retrieval_top_k": "9",
                                         "use_hyde": "false"}))
    db_session.commit()

    cfg, _ = resolve_ai_config(ws, None, db_session)
    assert cfg.retrieval_top_k == 9 and isinstance(cfg.retrieval_top_k, int)
    assert cfg.use_hyde is False

    for row in db_session.query(AiSettings).filter_by(workspace_id=ws).all():
        db_session.delete(row)
    db_session.commit()


def test_resolution_no_rows_returns_global(db_session, test_channel):
    cfg, prov = resolve_ai_config(uuid.uuid4(), None, db_session)
    from config import global_rag_config
    assert cfg.retrieval_top_k == global_rag_config.retrieval_top_k
    assert set(prov.values()) == {"global"}
