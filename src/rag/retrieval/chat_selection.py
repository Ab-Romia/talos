"""Query-time re-ranking of recalled chat segments.

score = rank_relevance * (floor + (1-floor) * 0.5^(age_h/half_life)), then a
greedy pick that skips candidates lexically redundant (Jaccard) with an
already-picked one. Rank-based relevance (1/(1+rank)) keeps this independent
of Milvus' distance metric; the decay floor keeps an old-but-uniquely-relevant
segment retrievable instead of decaying to zero.
"""
from datetime import datetime

from langchain_core.documents import Document

__all__ = ["select_chat_context"]

_DECAY_FLOOR = 0.25


def _age_hours(doc: Document, now: datetime) -> float:
    stamp = doc.metadata.get("sent_at_end") or doc.metadata.get("sent_at") or ""
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 0.0
    return max((now - then).total_seconds() / 3600.0, 0.0)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def select_chat_context(
    candidates: list[Document],
    *,
    k: int,
    now: datetime,
    half_life_hours: float,
    overlap_threshold: float,
) -> list[Document]:
    scored = []
    for rank, doc in enumerate(candidates):
        relevance = 1.0 / (1.0 + rank)
        decay = 0.5 ** (_age_hours(doc, now) / half_life_hours)
        recency = _DECAY_FLOOR + (1.0 - _DECAY_FLOOR) * decay
        scored.append((relevance * recency, rank, doc))
    scored.sort(key=lambda t: (-t[0], t[1]))

    picked: list[Document] = []
    picked_tokens: list[set[str]] = []
    for _score, _rank, doc in scored:
        if len(picked) >= k:
            break
        tokens = set(doc.page_content.lower().split())
        if any(_jaccard(tokens, seen) > overlap_threshold for seen in picked_tokens):
            continue
        picked.append(doc)
        picked_tokens.append(tokens)
    return picked
