"""Chunking hygiene: element filtering + section-aware chunk_by_title path."""
import pytest
from unstructured.documents.elements import (
    ElementMetadata, Footer, Header, NarrativeText, Title,
)

from config import RagConfig
from processing.documents import build_chunk_documents

BASE_META = {"workspace_id": "ws1", "file_id": "f1", "filename": "guide.pdf"}


def _el(cls, text, page=1):
    el = cls(text=text)
    el.metadata = ElementMetadata(page_number=page)
    return el


@pytest.fixture
def elements():
    return [
        _el(Header, "ACME GUIDE — CONFIDENTIAL", page=1),
        _el(Title, "System Design", page=1),
        _el(NarrativeText, "Do one hard system design question per day. " * 5, page=1),
        _el(NarrativeText, "Use mock interviews to practice articulating tradeoffs. " * 5, page=2),
        _el(Title, "Behavioral", page=3),
        _el(NarrativeText, "Prepare STAR stories for your five biggest projects. " * 5, page=3),
        _el(Footer, "page 3", page=3),
    ]


def test_by_title_drops_header_and_footer(elements):
    cfg = RagConfig(chunking_strategy="by_title")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    joined = " ".join(d.page_content for d in docs)
    assert "CONFIDENTIAL" not in joined
    assert "page 3" not in joined


def test_by_title_merges_fragments_and_keeps_section_metadata(elements):
    cfg = RagConfig(chunking_strategy="by_title")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    # no bare-title fragment chunks: every chunk carries real prose
    assert all(len(d.page_content) > 60 for d in docs)
    sections = {d.metadata.get("section") for d in docs}
    assert "System Design" in sections and "Behavioral" in sections
    assert all(d.metadata["workspace_id"] == "ws1" for d in docs)
    assert all(isinstance(d.metadata.get("page_number"), int) for d in docs)


def test_by_title_respects_max_characters(elements):
    cfg = RagConfig(chunking_strategy="by_title", chunk_size=1000)
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    assert all(len(d.page_content) <= 1000 for d in docs)


def test_prepend_section_title_flag(elements):
    cfg = RagConfig(chunking_strategy="by_title", chunk_prepend_section_title=True)
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    sys_docs = [d for d in docs if d.metadata.get("section") == "System Design"]
    assert sys_docs and all(d.page_content.startswith("[System Design]\n") for d in sys_docs)


def test_recursive_strategy_preserves_legacy_behavior(elements):
    """recursive = today's pipeline: one doc per element (incl. Header/Footer), split >1000."""
    cfg = RagConfig(chunking_strategy="recursive")
    docs = build_chunk_documents(elements, base_metadata=BASE_META, config=cfg)
    joined = " ".join(d.page_content for d in docs)
    assert "CONFIDENTIAL" in joined            # legacy keeps noise (baseline arm fidelity)
    assert any(d.page_content == "System Design" for d in docs)  # bare title fragment survives
