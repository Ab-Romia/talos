import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

# Pre-mock modules that ingestion.py imports at module level
sys.modules.setdefault("langchain_unstructured", MagicMock())

# Load rag.ingestion directly without triggering rag/__init__.py
# This avoids the heavy import chain (pymilvus, langchain_openai, etc.)
_spec = importlib.util.spec_from_file_location(
    "rag.ingestion",
    os.path.join(os.path.dirname(__file__), "../../src/rag/ingestion.py"),
    submodule_search_locations=[],
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["rag.ingestion"] = _mod
_spec.loader.exec_module(_mod)

format_citations = _mod.format_citations
ingest_file_chunks = _mod.ingest_file_chunks


@pytest.mark.unit
class TestFormatCitations:
    def _format(self, docs):
        return list(format_citations(docs))

    def test_workspace_file_with_page(self):
        doc = Document(
            page_content="text",
            metadata={"filename": "report.pdf", "page_number": 5, "file_id": "abc123"},
        )
        citations = self._format([doc])
        assert len(citations) == 1
        assert "report.pdf" in citations[0]
        assert "p.5" in citations[0]
        assert "file:abc123" in citations[0]

    def test_workspace_file_no_page(self):
        doc = Document(
            page_content="text",
            metadata={"filename": "notes.md", "page_number": "", "file_id": "xyz"},
        )
        citations = self._format([doc])
        assert len(citations) == 1
        assert "notes.md" in citations[0]
        assert "p." not in citations[0]

    def test_cli_doc_source(self):
        doc = Document(
            page_content="text",
            metadata={"source": "./docs/README.md"},
        )
        citations = self._format([doc])
        assert len(citations) == 1
        assert "./docs/README.md" in citations[0]

    def test_unknown_source(self):
        doc = Document(page_content="text", metadata={})
        citations = self._format([doc])
        assert len(citations) == 1
        assert "unknown" in citations[0]

    def test_deduplicates(self):
        docs = [
            Document(page_content="a", metadata={"filename": "same.pdf", "page_number": 1, "file_id": "x"}),
            Document(page_content="b", metadata={"filename": "same.pdf", "page_number": 1, "file_id": "x"}),
        ]
        citations = self._format(docs)
        assert len(citations) == 1

    def test_numbering(self):
        docs = [
            Document(page_content="a", metadata={"source": "doc1.pdf"}),
            Document(page_content="b", metadata={"source": "doc2.pdf"}),
            Document(page_content="c", metadata={"source": "doc3.pdf"}),
        ]
        citations = self._format(docs)
        assert citations[0].startswith("[1]")
        assert citations[1].startswith("[2]")
        assert citations[2].startswith("[3]")


@pytest.mark.unit
class TestIngestFileChunks:
    def test_sets_metadata(self):
        mock_vs = MagicMock()
        mock_get_vs = MagicMock(return_value=mock_vs)
        # Patch the lazy import target
        with patch.dict("sys.modules", {"rag.vector_store": MagicMock(get_workspace_vectorstore=mock_get_vs)}):
            chunk = Document(page_content="hello", metadata={"chunk_index": 0})
            ingest_file_chunks([chunk], workspace_id="ws-1", file_id="f-1")

        assert chunk.metadata["workspace_id"] == "ws-1"
        assert chunk.metadata["file_id"] == "f-1"
        assert chunk.metadata["chunk_index"] == 0

    def test_calls_add_documents(self):
        mock_vs = MagicMock()
        mock_get_vs = MagicMock(return_value=mock_vs)
        with patch.dict("sys.modules", {"rag.vector_store": MagicMock(get_workspace_vectorstore=mock_get_vs)}):
            chunks = [Document(page_content="a", metadata={})]
            ingest_file_chunks(chunks, workspace_id="ws-1", file_id="f-1")

        mock_vs.add_documents.assert_called_once_with(chunks)
