from enum import Enum
from typing import Literal, ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["global_rag_config", "RagConfig", "LoggingConfig", "CompressionType"]


class CompressionType(str, Enum):
    LLM = "llm"
    EMBEDDINGS = "embeddings"
    PIPELINE = "pipeline"
    NONE = "none"


class RagConfig(BaseSettings):
    openai_api_key: SecretStr | None = None
    # Optional OpenAI-compatible endpoint override (e.g. an OpenRouter proxy).
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"

    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "openai"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "talos_documents"

    # Eval-tuned default (was 5): top_k=10 beat top_k=5 consistently
    # (+0.03-0.05 page-recall) in the live-PDF ablation.
    # See evaluation/live_pdf_eval/REPORT.md.
    retrieval_top_k: int = 10
    # Candidate pool the dense stage fetches BEFORE the cross-encoder reranks
    # down to retrieval_top_k. Widening here is what lets reranking improve
    # recall rather than merely reorder the same top_k. Ignored when
    # use_reranking is False.
    # Eval-tuned default (was 20): 50 chosen in the live-PDF ablation
    # (minilm 0.892@50 vs 0.861@20; bge tied 0.892 across 20/50/100).
    # See evaluation/live_pdf_eval/REPORT.md.
    rerank_fetch_k: int = 50
    use_hybrid_retrieval: bool = False
    use_reranking: bool = True
    # HyDE and query rewriting each add an LLM call per query (latency + cost).
    # Gated so they can be turned off (e.g. local/low-VRAM runs, or the
    # technical-corpus regimes where they don't help). Default preserves the
    # prior always-on behaviour.
    use_hyde: bool = True
    use_query_rewrite: bool = True

    compression_type: CompressionType = CompressionType.NONE
    # Similarity floor for the embeddings-filter compressor. Configurable so the
    # eval can calibrate it (0.76 was found too aggressive for
    # text-embedding-3-small) and so what eval sweeps is what prod can ship.
    compression_similarity_threshold: float = 0.76

    chunk_size: int = 1000
    chunk_overlap: int = 200
    # Eval-tuned default (was "recursive"): "recursive" fragments elements
    # into short chunks (median 67 chars) with 9-13% boilerplate in top-k;
    # "by_title" merges into section-sized chunks (median 440 chars) with
    # 0.000 boilerplate and +18.6pt judged correctness in the live-PDF
    # ablation. See evaluation/live_pdf_eval/REPORT.md.
    chunking_strategy: str = "by_title"
    # "by_title" only: prepend the active section heading to each chunk's text
    # before embedding ("[Section]\ntext"). Cheap contextual anchor; ablated in
    # evaluation/live_pdf_eval and failed its pre-set bar (>0.02 page-recall
    # over plain by_title) — stays False. See evaluation/live_pdf_eval/REPORT.md.
    chunk_prepend_section_title: bool = False

    # Chat-memory indexing: the cron embeds messages older than the grace window
    # (so live messages still in the un-indexed tail aren't indexed prematurely);
    # chat_context_cap bounds the un-indexed tail injected directly per ask.
    chat_index_interval_minutes: int = 5
    chat_index_grace_seconds: int = 300
    chat_index_batch_size: int = 500
    # Max batches drained per cron tick (backlog burst recovery); each batch is
    # chat_index_batch_size messages.
    chat_index_max_batches: int = 10
    chat_recall_k: int = 3
    chat_context_cap: int = 50
    # Char budget for that tail (≈ tokens×4, tokenizer-free). The message cap
    # bounds COUNT; this bounds LENGTH, so 50 pasted walls of text can't blow
    # the model's context window. The newest message is always kept whole.
    chat_context_char_budget: int = 16000
    # Conversation segmentation for chat-memory indexing: a segment closes on
    # an inactivity gap or a size cap; segments (not single messages) are the
    # embedded retrieval unit.
    chat_segment_gap_minutes: int = 30
    chat_segment_max_messages: int = 12
    # Chat recall re-ranking: fetch a wider candidate pool, then re-rank by
    # rank-relevance x time-decay with lexical redundancy suppression down to
    # chat_recall_k.
    chat_recall_fetch_k: int = 10
    chat_decay_half_life_hours: float = 168.0  # one week
    chat_recall_overlap_threshold: float = 0.6

    llm_temperature: float = 0.0
    llm_streaming: bool = True

    langchain_tracing_v2: bool = False
    langchain_api_key: SecretStr | None = None
    langchain_project: str = "gp-artifact-rag"

    # Models a workspace admin may select via ai_settings (vetted allow-list;
    # never free text). Extend deliberately.
    ai_model_allow_list: list[str] = ["gpt-4o-mini", "gpt-4o", "qwen2.5:7b-instruct"]

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    # Logging level
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Log format string
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # Log file path
    file_path: str | None = None
    # Enable rich console logging
    enable_rich: bool = True
    # Enable metrics logging
    enable_metrics: bool = True


global_rag_config = RagConfig()
# logging_config = LoggingConfig()
