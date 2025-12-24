"""
Document chunking strategies including CLaRa-inspired semantic chunking.

Provides multiple chunking strategies optimized for different use cases.
"""

import re
import hashlib
from abc import ABC
from typing import Any, Dict, List, Optional

from src.core.base_interfaces import BaseChunker, Document
from src.core.config_loader import ChunkingConfig
from src.core.exceptions import ChunkingError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TextChunker(BaseChunker, ABC):
    """Base class for text chunkers."""

    def __init__(self, config: ChunkingConfig):
        self.config = config

    def _create_chunk_document(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_index: int = 0,
    ) -> Document:
        """Create a document chunk with metadata."""
        chunk_metadata = {
            "chunk_index": chunk_index,
            "chunk_size": len(content),
        }
        if metadata:
            chunk_metadata.update(metadata)

        # Generate deterministic ID based on content
        content_hash = hashlib.md5(content.encode()).hexdigest()
        doc_id = f"doc_{content_hash}"

        return Document(
            content=content,
            metadata=chunk_metadata,
            id=doc_id
        )

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Chunk multiple documents."""
        all_chunks = []
        for doc in documents:
            chunks = self.chunk(doc.content, doc.metadata)
            all_chunks.extend(chunks)
        return all_chunks


class FixedChunker(TextChunker):
    """
    Fixed-size chunking strategy.

    Splits text into chunks of approximately equal size with overlap.
    """

    def chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Split text into fixed-size chunks."""
        if not text.strip():
            return []

        chunk_size = self.config.chunk_size
        overlap = self.config.chunk_overlap

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # Try to break at word boundary
            if end < len(text):
                # Look for space within last 20% of chunk
                search_start = max(start, end - chunk_size // 5)
                last_space = text.rfind(" ", search_start, end)
                if last_space > start:
                    end = last_space

            chunk_text = text[start:end].strip()

            if chunk_text and len(chunk_text) >= self.config.min_chunk_size:
                chunks.append(
                    self._create_chunk_document(chunk_text, metadata, chunk_index)
                )
                chunk_index += 1

            start = end - overlap if end < len(text) else len(text)

        return chunks


class RecursiveChunker(TextChunker):
    """
    Recursive character text splitting strategy.

    Tries to split by multiple separators, starting with larger units.
    """

    def chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Split text recursively using separators."""
        if not text.strip():
            return []

        chunks = self._split_recursive(text, self.config.separators)

        documents = []
        for i, chunk in enumerate(chunks):
            if chunk.strip() and len(chunk.strip()) >= self.config.min_chunk_size:
                documents.append(
                    self._create_chunk_document(chunk.strip(), metadata, i)
                )

        return documents

    def _split_recursive(
        self,
        text: str,
        separators: List[str],
    ) -> List[str]:
        """Recursively split text using separators."""
        if not separators:
            return [text]

        separator = separators[0]
        remaining_separators = separators[1:]

        # Split by current separator
        if separator:
            splits = text.split(separator)
        else:
            # Empty separator means character-level split
            splits = list(text)

        # Merge small chunks and split large ones
        chunks = []
        current_chunk = ""

        for split in splits:
            if not split.strip():
                continue

            potential_chunk = current_chunk + separator + split if current_chunk else split

            if len(potential_chunk) <= self.config.chunk_size:
                current_chunk = potential_chunk
            else:
                # Save current chunk if it's large enough
                if current_chunk and len(current_chunk) >= self.config.min_chunk_size:
                    chunks.append(current_chunk)
                elif current_chunk:
                    # Merge with next
                    split = current_chunk + separator + split

                # Try to split large chunks with remaining separators
                if len(split) > self.config.max_chunk_size and remaining_separators:
                    sub_chunks = self._split_recursive(split, remaining_separators)
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = split

        if current_chunk:
            chunks.append(current_chunk)

        return chunks


class SentenceChunker(TextChunker):
    """
    Sentence-based chunking strategy.

    Groups sentences until reaching target chunk size.
    """

    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self._sentence_pattern = re.compile(
            r"(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])\s*\n"
        )

    def chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Split text into sentence-based chunks."""
        if not text.strip():
            return []

        # Split into sentences
        sentences = self._sentence_pattern.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current_chunk = []
        current_length = 0
        chunk_index = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > self.config.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                if len(chunk_text) >= self.config.min_chunk_size:
                    chunks.append(
                        self._create_chunk_document(chunk_text, metadata, chunk_index)
                    )
                    chunk_index += 1

                # Start new chunk with overlap
                if self.config.chunk_overlap > 0:
                    # Keep last few sentences for overlap
                    overlap_text = ""
                    overlap_sentences = []
                    for s in reversed(current_chunk):
                        if len(overlap_text) + len(s) < self.config.chunk_overlap:
                            overlap_sentences.insert(0, s)
                            overlap_text = " ".join(overlap_sentences)
                        else:
                            break
                    current_chunk = overlap_sentences
                    current_length = len(overlap_text)
                else:
                    current_chunk = []
                    current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space

        # Don't forget last chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            if len(chunk_text) >= self.config.min_chunk_size:
                chunks.append(
                    self._create_chunk_document(chunk_text, metadata, chunk_index)
                )

        return chunks


class MarkdownChunker(TextChunker):
    """
    Markdown-aware chunking strategy.

    Respects markdown structure (headers, code blocks, etc.).
    """

    def chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Split markdown text respecting structure."""
        if not text.strip():
            return []

        # Split by headers
        sections = self._split_by_headers(text)

        chunks = []
        chunk_index = 0

        for section_title, section_content in sections:
            section_metadata = dict(metadata or {})
            if section_title:
                section_metadata["section_title"] = section_title

            # If section is small enough, keep as single chunk
            if len(section_content) <= self.config.chunk_size:
                if len(section_content.strip()) >= self.config.min_chunk_size:
                    chunks.append(
                        self._create_chunk_document(
                            section_content.strip(), section_metadata, chunk_index
                        )
                    )
                    chunk_index += 1
            else:
                # Split large sections
                sub_chunks = self._split_section(section_content)
                for sub_chunk in sub_chunks:
                    if len(sub_chunk.strip()) >= self.config.min_chunk_size:
                        chunks.append(
                            self._create_chunk_document(
                                sub_chunk.strip(), section_metadata, chunk_index
                            )
                        )
                        chunk_index += 1

        return chunks

    def _split_by_headers(self, text: str) -> List[tuple]:
        """Split markdown by headers."""
        # Pattern to match headers
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        sections = []
        last_end = 0
        current_title = None

        for match in header_pattern.finditer(text):
            # Save previous section
            if last_end > 0 or match.start() > 0:
                content = text[last_end : match.start()].strip()
                if content:
                    sections.append((current_title, content))

            current_title = match.group(2).strip()
            last_end = match.end()

        # Add final section
        final_content = text[last_end:].strip()
        if final_content:
            sections.append((current_title, final_content))

        # If no sections found, return whole text
        if not sections:
            sections = [(None, text)]

        return sections

    def _split_section(self, text: str) -> List[str]:
        """Split a section into smaller chunks."""
        # Try splitting by paragraphs first
        paragraphs = text.split("\n\n")

        chunks = []
        current_chunk = ""

        for para in paragraphs:
            if not para.strip():
                continue

            if len(current_chunk) + len(para) > self.config.chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks


class SemanticChunker(TextChunker):
    """
    CLaRa-inspired semantic chunking strategy.

    Uses embeddings to find natural breakpoints based on semantic similarity.
    This is the recommended chunking strategy for optimal RAG performance.
    """

    def __init__(
        self,
        config: ChunkingConfig,
        embedding_service: Optional[Any] = None,
    ):
        super().__init__(config)
        self._embedding_service = embedding_service
        self._sentence_pattern = re.compile(
            r"(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])\s*\n|\n\n+"
        )

    def set_embedding_service(self, embedding_service: Any) -> None:
        """Set embedding service for semantic chunking."""
        self._embedding_service = embedding_service

    def chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Split text based on semantic similarity."""
        if not text.strip():
            return []

        # If no embedding service, fall back to sentence chunking
        if self._embedding_service is None:
            logger.warning(
                "No embedding service for semantic chunking, falling back to sentences"
            )
            return self._fallback_chunk(text, metadata)

        try:
            return self._semantic_chunk(text, metadata)
        except Exception as e:
            logger.warning(f"Semantic chunking failed: {e}, falling back to sentences")
            return self._fallback_chunk(text, metadata)

    def _semantic_chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Perform semantic chunking using embeddings."""
        import numpy as np

        # Split into sentences
        sentences = self._sentence_pattern.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 1:
            return [self._create_chunk_document(text.strip(), metadata, 0)]

        # Get embeddings for sentences
        embeddings = self._embedding_service.embed_documents(sentences)
        embeddings = np.array(embeddings)

        # Calculate similarities between consecutive sentences
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        # Find breakpoints based on threshold
        breakpoints = self._find_breakpoints(similarities)

        # Create chunks based on breakpoints
        chunks = []
        chunk_start = 0
        chunk_index = 0

        for bp in breakpoints:
            chunk_sentences = sentences[chunk_start : bp + 1]
            chunk_text = " ".join(chunk_sentences)

            # Ensure chunk is within size limits
            if len(chunk_text) > self.config.max_chunk_size:
                # Split oversized chunk
                sub_chunks = self._split_oversized(chunk_text)
                for sub_chunk in sub_chunks:
                    if len(sub_chunk.strip()) >= self.config.min_chunk_size:
                        chunks.append(
                            self._create_chunk_document(
                                sub_chunk.strip(), metadata, chunk_index
                            )
                        )
                        chunk_index += 1
            elif len(chunk_text.strip()) >= self.config.min_chunk_size:
                chunks.append(
                    self._create_chunk_document(chunk_text.strip(), metadata, chunk_index)
                )
                chunk_index += 1

            chunk_start = bp + 1

        # Handle remaining sentences
        if chunk_start < len(sentences):
            chunk_text = " ".join(sentences[chunk_start:])
            if len(chunk_text.strip()) >= self.config.min_chunk_size:
                chunks.append(
                    self._create_chunk_document(chunk_text.strip(), metadata, chunk_index)
                )

        return chunks

    def _cosine_similarity(self, vec1, vec2) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2 + 1e-10)

    def _find_breakpoints(self, similarities: List[float]) -> List[int]:
        """Find breakpoints based on similarity threshold."""
        import numpy as np

        if not similarities:
            return []

        threshold_type = self.config.breakpoint_threshold_type
        threshold_amount = self.config.breakpoint_threshold_amount

        if threshold_type == "percentile":
            threshold = np.percentile(similarities, 100 - threshold_amount)
        elif threshold_type == "standard_deviation":
            mean = np.mean(similarities)
            std = np.std(similarities)
            threshold = mean - threshold_amount * std
        elif threshold_type == "interquartile":
            q1 = np.percentile(similarities, 25)
            q3 = np.percentile(similarities, 75)
            iqr = q3 - q1
            threshold = q1 - threshold_amount * iqr
        else:
            threshold = 0.5  # Default

        breakpoints = []
        for i, sim in enumerate(similarities):
            if sim < threshold:
                breakpoints.append(i)

        return breakpoints

    def _split_oversized(self, text: str) -> List[str]:
        """Split oversized chunk into smaller pieces."""
        chunks = []
        start = 0
        chunk_size = self.config.chunk_size

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # Try to break at sentence boundary
            if end < len(text):
                last_period = text.rfind(". ", start, end)
                if last_period > start:
                    end = last_period + 1

            chunks.append(text[start:end])
            start = end

        return chunks

    def _fallback_chunk(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Fallback to sentence-based chunking."""
        sentence_chunker = SentenceChunker(self.config)
        return sentence_chunker.chunk(text, metadata)


def create_chunker(
    config: ChunkingConfig,
    embedding_service: Optional[Any] = None,
) -> TextChunker:
    """
    Factory function to create chunker based on config.

    Args:
        config: Chunking configuration
        embedding_service: Optional embedding service for semantic chunking

    Returns:
        Appropriate chunker instance
    """
    chunker_map = {
        "fixed": FixedChunker,
        "recursive": RecursiveChunker,
        "sentence": SentenceChunker,
        "markdown": MarkdownChunker,
        "semantic": SemanticChunker,
    }

    chunker_class = chunker_map.get(config.strategy)
    if chunker_class is None:
        raise ChunkingError(
            f"Unknown chunking strategy: {config.strategy}",
            strategy=config.strategy,
            details={"supported_strategies": list(chunker_map.keys())},
        )

    if config.strategy == "semantic":
        return chunker_class(config, embedding_service)

    return chunker_class(config)
