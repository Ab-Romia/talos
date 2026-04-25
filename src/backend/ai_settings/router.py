from pydantic import BaseModel, Field

from config import get_runtime_overrides, public_ai_settings, set_runtime_rag_patches
from backend.auth.utils.helpers import UserDep
from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["ai-settings"])


class AiSettingsUpdate(BaseModel):
    openai_model: str | None = None
    embedding_model: str | None = None
    embedding_provider: str | None = None
    llm_temperature: float | None = None
    llm_streaming: bool | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1, le=50)
    use_hybrid_retrieval: bool | None = None
    use_reranking: bool | None = None
    compression_type: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=32_000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4_000)
    chunking_strategy: str | None = None
    conversation_memory_k: int | None = Field(default=None, ge=0, le=100)
    milvus_host: str | None = None
    milvus_port: int | None = Field(default=None, ge=1, le=65_535)
    milvus_collection_name: str | None = None


@router.get("/config")
def get_ai_config(_user: UserDep):
    return public_ai_settings()


@router.patch("/config")
def patch_ai_config(body: AiSettingsUpdate, _user: UserDep):
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    set_runtime_rag_patches(data)
    return public_ai_settings()


@router.get("/config/overrides")
def get_overrides(_user: UserDep):
    return get_runtime_overrides()
