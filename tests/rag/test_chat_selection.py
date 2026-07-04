"""Pure re-ranking logic: rank-relevance x time-decay, redundancy suppressed."""
from datetime import datetime, timedelta, timezone

from langchain_core.documents import Document

from rag.retrieval.chat_selection import select_chat_context

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _doc(text, hours_old):
    return Document(page_content=text, metadata={
        "sent_at_end": (NOW - timedelta(hours=hours_old)).isoformat()})


def test_recent_beats_slightly_more_relevant_but_ancient():
    docs = [
        _doc("deploy key rotation discussion", hours_old=24 * 365),  # rank 0, a year old
        _doc("we rotated the deploy key yesterday", hours_old=2),    # rank 1, fresh
    ]
    out = select_chat_context(docs, k=1, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert out[0].page_content == "we rotated the deploy key yesterday"


def test_old_but_only_candidate_survives():
    docs = [_doc("ancient but unique fact", hours_old=24 * 365)]
    out = select_chat_context(docs, k=3, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert len(out) == 1


def test_near_duplicates_suppressed():
    docs = [
        _doc("staging database runs on port 5544", hours_old=1),
        _doc("staging database runs on port 5544 !", hours_old=1),   # near-dupe
        _doc("prod key lives in the vault", hours_old=1),
    ]
    out = select_chat_context(docs, k=2, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    texts = [d.page_content for d in out]
    assert len(texts) == 2
    assert "prod key lives in the vault" in texts


def test_k_caps_output_and_missing_timestamp_is_tolerated():
    docs = [Document(page_content=f"unique text {i}", metadata={}) for i in range(5)]
    out = select_chat_context(docs, k=3, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert len(out) == 3


def test_stats_reports_drops_and_keeps():
    docs = [
        _doc("staging database runs on port 5544", hours_old=1),
        _doc("staging database runs on port 5544 !", hours_old=1),   # near-dupe
        _doc("prod key lives in the vault", hours_old=1),
        _doc("unrelated fourth candidate", hours_old=1),
    ]
    stats = {}
    out = select_chat_context(docs, k=2, now=NOW, half_life_hours=168,
                              overlap_threshold=0.6, stats=stats)
    assert stats == {"considered": 4, "dropped_redundant": 1, "kept": 2, "truncated": 1}
    assert stats["considered"] == stats["dropped_redundant"] + stats["kept"] + stats["truncated"]
    assert len(out) == 2
