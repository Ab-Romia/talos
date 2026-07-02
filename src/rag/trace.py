from dataclasses import dataclass, field, asdict

from langchain_core.documents import Document

__all__ = ["RagTrace"]


@dataclass
class RagTrace:
    """Everything a single RAG run actually used — model, effective config,
    queries, retrieved candidates, final context, and the exact prompt.

    Filled once per run by RAGChain and consumed identically by the /ask debug
    flag, scripts/debug_ask.py, and the eval harness, so observability has one
    source of truth instead of ad-hoc reach-ins.
    """

    model: str = ""
    embedding_provider: str = ""
    request_id: str = ""
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    effective_config: dict = field(default_factory=dict)
    original_query: str = ""
    rewritten_query: str | None = None
    hyde_used: bool = False
    file_candidates: list[dict] = field(default_factory=list)
    chat_candidates: list[dict] = field(default_factory=list)
    chat_selection: dict = field(default_factory=dict)
    injected_tail_size: int = 0
    final_context: str = ""
    prompt: str = ""

    @staticmethod
    def doc_summary(doc: Document) -> dict:
        """A compact, JSON-safe view of a retrieved document."""
        return {"metadata": dict(doc.metadata), "snippet": doc.page_content[:240]}

    def as_dict(self) -> dict:
        return asdict(self)
