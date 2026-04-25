"""Runtime RAG/AI config overrides (merges on top of env-backed ``global_rag_config``)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .config import RagConfig, global_rag_config

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_OVERRIDES_PATH = _DATA_DIR / "ai_runtime.json"

# Keys clients may change via the API; secrets use env (``openai_api_key``) only
_PATCHABLE: frozenset[str] = frozenset(
    {
        "openai_model",
        "embedding_model",
        "embedding_provider",
        "llm_temperature",
        "llm_streaming",
        "retrieval_top_k",
        "use_hybrid_retrieval",
        "use_reranking",
        "compression_type",
        "chunk_size",
        "chunk_overlap",
        "chunking_strategy",
        "conversation_memory_k",
        "milvus_host",
        "milvus_port",
        "milvus_collection_name",
    }
)

_lock = threading.RLock()


def _read_disk() -> dict:
    if not _OVERRIDES_PATH.is_file():
        return {}
    try:
        with open(_OVERRIDES_PATH, encoding="utf-8") as f:
            t = f.read()
            if not t.strip():
                return {}
            return json.loads(t)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_disk(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def get_runtime_overrides() -> dict:
    with _lock:
        d = _read_disk()
    return {k: v for k, v in d.items() if k in _PATCHABLE and v is not None}


def get_effective_rag_config() -> RagConfig:
    raw = get_runtime_overrides()
    if not raw:
        return global_rag_config
    return global_rag_config.model_copy(update=raw, deep=True)


def set_runtime_rag_patches(updates: dict) -> dict:
    clean = {k: v for k, v in updates.items() if k in _PATCHABLE and v is not None}
    if not clean:
        return get_runtime_overrides()
    # Validate merge (raises on bad types / values)
    get_effective_rag_config().model_copy(update=clean, deep=True)
    with _lock:
        data = _read_disk()
        data.update(clean)
        _write_disk(data)
    return get_runtime_overrides()


def public_ai_settings() -> dict:
    c = get_effective_rag_config()
    d = c.model_dump(mode="json", exclude={"openai_api_key", "langchain_api_key"})
    d["openai_api_key_set"] = c.openai_api_key is not None
    d["overrides"] = get_runtime_overrides()
    d["source"] = "env+runtime" if get_runtime_overrides() else "env"
    return d
