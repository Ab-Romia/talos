"""
Citation handler for tracking and formatting source citations.

Manages document references and generates citation formats.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import Document
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Citation:
    """Represents a citation to a source document."""

    document_index: int
    document: Document
    relevance_score: Optional[float] = None
    excerpt: Optional[str] = None


class CitationHandler:
    """
    Handler for managing and formatting citations.

    Tracks which documents were used and formats citations.
    """

    def __init__(
        self,
        citation_style: str = "numbered",
        include_excerpts: bool = True,
        max_excerpt_length: int = 200,
    ):
        """
        Initialize citation handler.

        Args:
            citation_style: Citation format (numbered, footnote, inline)
            include_excerpts: Whether to include text excerpts
            max_excerpt_length: Maximum excerpt length
        """
        self.citation_style = citation_style
        self.include_excerpts = include_excerpts
        self.max_excerpt_length = max_excerpt_length
        self.citations: List[Citation] = []

    def add_citation(
        self,
        document_index: int,
        document: Document,
        relevance_score: Optional[float] = None,
        excerpt: Optional[str] = None,
    ) -> Citation:
        """
        Add a citation.

        Args:
            document_index: Index in document list
            document: Source document
            relevance_score: Relevance score
            excerpt: Specific excerpt cited

        Returns:
            Created Citation
        """
        citation = Citation(
            document_index=document_index,
            document=document,
            relevance_score=relevance_score,
            excerpt=excerpt,
        )
        self.citations.append(citation)
        return citation

    def track_sources(
        self,
        documents: List[Document],
        used_indices: Optional[List[int]] = None,
    ) -> List[Citation]:
        """
        Track which documents were used as sources.

        Args:
            documents: All context documents
            used_indices: Indices of documents actually used

        Returns:
            List of citations
        """
        self.citations = []

        indices = used_indices or range(len(documents))

        for i in indices:
            if i < len(documents):
                doc = documents[i]
                excerpt = None

                if self.include_excerpts:
                    excerpt = doc.content[:self.max_excerpt_length]
                    if len(doc.content) > self.max_excerpt_length:
                        excerpt += "..."

                self.add_citation(
                    document_index=i + 1,  # 1-indexed for display
                    document=doc,
                    relevance_score=doc.score,
                    excerpt=excerpt,
                )

        return self.citations

    def format_citations(self) -> str:
        """
        Format citations for display.

        Returns:
            Formatted citation string
        """
        if not self.citations:
            return ""

        if self.citation_style == "numbered":
            return self._format_numbered()
        elif self.citation_style == "footnote":
            return self._format_footnote()
        elif self.citation_style == "inline":
            return self._format_inline()
        else:
            return self._format_numbered()

    def _format_numbered(self) -> str:
        """Format as numbered list."""
        lines = ["\n**Sources:**"]

        for citation in self.citations:
            source = citation.document.metadata.get("source", "Unknown")
            line = f"[{citation.document_index}] {source}"

            if citation.relevance_score is not None:
                line += f" (relevance: {citation.relevance_score:.2f})"

            lines.append(line)

            if self.include_excerpts and citation.excerpt:
                lines.append(f"    > {citation.excerpt}")

        return "\n".join(lines)

    def _format_footnote(self) -> str:
        """Format as footnotes."""
        lines = ["\n---\n**References:**"]

        for citation in self.citations:
            source = citation.document.metadata.get("source", "Unknown")
            lines.append(f"^{citation.document_index}: {source}")

        return "\n".join(lines)

    def _format_inline(self) -> str:
        """Format as inline citations."""
        sources = []
        for citation in self.citations:
            source = citation.document.metadata.get("source", "Unknown")
            sources.append(f"{source}")

        return f"\n\n*Sources: {', '.join(sources)}*"

    def get_citation_metadata(self) -> Dict[str, Any]:
        """Get metadata about citations."""
        return {
            "num_citations": len(self.citations),
            "sources": [
                {
                    "index": c.document_index,
                    "source": c.document.metadata.get("source", "Unknown"),
                    "score": c.relevance_score,
                }
                for c in self.citations
            ],
        }

    def clear(self) -> None:
        """Clear all citations."""
        self.citations = []
