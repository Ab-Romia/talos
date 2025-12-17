"""
Metadata extraction utilities for documents.

Extracts useful metadata from documents to enhance retrieval.
"""

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import Document
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MetadataExtractor:
    """
    Extracts metadata from documents.

    Provides standard metadata extraction and custom extractors.
    """

    def __init__(
        self,
        extract_entities: bool = False,
        extract_keywords: bool = True,
        extract_summary: bool = False,
    ):
        self.extract_entities = extract_entities
        self.extract_keywords = extract_keywords
        self.extract_summary = extract_summary

    def extract(self, document: Document) -> Document:
        """Extract and add metadata to document."""
        metadata = dict(document.metadata)

        # Basic metadata
        metadata.update(self._extract_basic_metadata(document))

        # Content-based metadata
        if self.extract_keywords:
            metadata["keywords"] = self._extract_keywords(document.content)

        document.metadata = metadata
        return document

    def extract_batch(self, documents: List[Document]) -> List[Document]:
        """Extract metadata from multiple documents."""
        return [self.extract(doc) for doc in documents]

    def _extract_basic_metadata(self, document: Document) -> Dict[str, Any]:
        """Extract basic metadata from document."""
        content = document.content

        return {
            "content_length": len(content),
            "word_count": len(content.split()),
            "line_count": content.count("\n") + 1,
            "content_hash": hashlib.md5(content.encode()).hexdigest()[:16],
            "extracted_at": datetime.now().isoformat(),
        }

    def _extract_keywords(
        self,
        content: str,
        max_keywords: int = 10,
    ) -> List[str]:
        """Extract keywords from content using simple TF approach."""
        # Tokenize and clean
        words = re.findall(r"\b[a-zA-Z]{3,}\b", content.lower())

        # Filter stopwords
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you", "all",
            "can", "had", "her", "was", "one", "our", "out", "has",
            "have", "been", "were", "will", "more", "when", "who",
            "this", "that", "with", "from", "they", "which", "their",
            "what", "there", "would", "about", "into", "could", "other",
            "than", "then", "them", "these", "some", "such", "only",
        }
        words = [w for w in words if w not in stopwords]

        # Count frequencies
        word_freq: Dict[str, int] = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1

        # Get top keywords
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:max_keywords]]


class FileMetadataExtractor(MetadataExtractor):
    """Extracts file-specific metadata."""

    def extract(self, document: Document) -> Document:
        """Extract file metadata."""
        document = super().extract(document)

        source = document.metadata.get("source")
        if source:
            path = Path(source)
            if path.exists():
                stat = path.stat()
                document.metadata.update({
                    "file_size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_extension": path.suffix,
                    "file_stem": path.stem,
                })

        return document
