"""Task 4 — RagTrace: one structured record of what a RAG run actually used,
shared by /ask debug, debug_ask.py, and the eval harness."""

from langchain_core.documents import Document
from rag.trace import RagTrace


def test_trace_round_trips():
    t = RagTrace(model="gpt-4o-mini", embedding_provider="openai",
                 effective_config={"use_hyde": False}, original_query="q",
                 rewritten_query="q2", hyde_used=False,
                 file_candidates=[], chat_candidates=[],
                 injected_tail_size=2, final_context="ctx", prompt="p")
    d = t.as_dict()
    assert d["model"] == "gpt-4o-mini"
    assert d["rewritten_query"] == "q2"
    assert d["injected_tail_size"] == 2
    assert d["effective_config"] == {"use_hyde": False}


def test_defaults_are_safe():
    t = RagTrace()
    d = t.as_dict()
    assert d["file_candidates"] == []
    assert d["chat_candidates"] == []
    assert d["rewritten_query"] is None


def test_doc_summary_extracts_metadata_and_snippet():
    doc = Document(page_content="hello world " * 50, metadata={"message_id": "m1", "source": "chat"})
    s = RagTrace.doc_summary(doc)
    assert s["metadata"]["message_id"] == "m1"
    assert s["metadata"]["source"] == "chat"
    assert len(s["snippet"]) <= 240
    assert s["snippet"].startswith("hello world")
