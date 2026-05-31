from functools import lru_cache

from .config import *  # noqa: F401,F403
from .config_ import Config
from .prompts import *  # noqa: F401,F403
from .runtime_rag import get_effective_rag_config, get_runtime_overrides, public_ai_settings, set_runtime_rag_patches

__all__ = [
    "get_effective_rag_config",
    "get_runtime_overrides",
    "public_ai_settings",
    "set_runtime_rag_patches",
    "global_rag_config",
    "RagConfig",
    "LoggingConfig",
    "CompressionType",
    "RAG_PROMPT",
    "QUERY_REWRITE_PROMPT",
    "RAG_PROMPT_WITHOUT_MEMORY",
]


@lru_cache
def cfg() -> Config:
    return Config()  # noqa
