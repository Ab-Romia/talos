"""
Context compression for efficient RAG (CLaRa-inspired).

Compresses retrieved context while preserving relevant information.
"""

from typing import Any, List, Optional

from src.core.base_interfaces import BaseContextCompressor, Document
from src.core.config_loader import CompressionConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ContextCompressor(BaseContextCompressor):
    """
    CLaRa-inspired context compressor.

    Reduces context size while preserving information relevant to the query.
    """

    def __init__(
        self,
        config: CompressionConfig,
        llm_service: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
    ):
        """
        Initialize context compressor.

        Args:
            config: Compression configuration
            llm_service: LLM for extraction-based compression
            embedding_service: Embeddings for similarity-based compression
        """
        self.config = config
        self.llm_service = llm_service
        self.embedding_service = embedding_service

        self.extraction_prompt = """Extract only the sentences from the following document that are relevant to answering the question.
Do not add any new information. Only include sentences from the original document.

Question: {query}

Document:
{content}

Relevant sentences:"""

    def set_llm_service(self, llm_service: Any) -> None:
        """Set LLM service."""
        self.llm_service = llm_service

    def set_embedding_service(self, embedding_service: Any) -> None:
        """Set embedding service."""
        self.embedding_service = embedding_service

    def compress(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Document]:
        """
        Compress context documents.

        Args:
            query: Query for relevance filtering
            documents: Documents to compress

        Returns:
            Compressed documents
        """
        if not self.config.enabled or not documents:
            return documents

        method = self.config.method

        if method == "llm_extractor":
            return self._llm_extraction(query, documents)
        elif method == "embeddings_filter":
            return self._embeddings_filter(query, documents)
        elif method == "llm_chain_filter":
            return self._llm_chain_filter(query, documents)
        else:
            return documents

    def _llm_extraction(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Document]:
        """Extract relevant sentences using LLM."""
        if self.llm_service is None:
            logger.warning("No LLM service for extraction compression")
            return documents

        compressed = []
        target_ratio = self.config.compression_ratio

        for doc in documents:
            try:
                prompt = self.extraction_prompt.format(
                    query=query,
                    content=doc.content,
                )

                result = self.llm_service.generate(
                    query=prompt,
                    context=[],
                )

                extracted = result.answer.strip()

                # Only use if actually compressed
                if extracted and len(extracted) < len(doc.content) * (1 + target_ratio):
                    compressed_doc = Document(
                        id=doc.id,
                        content=extracted,
                        metadata={**doc.metadata, "compressed": True},
                        score=doc.score,
                    )
                    compressed.append(compressed_doc)
                else:
                    compressed.append(doc)

            except Exception as e:
                logger.warning(f"Compression failed for document: {e}")
                compressed.append(doc)

        logger.debug(
            f"Compressed {len(documents)} documents",
            avg_compression=self._calc_compression_ratio(documents, compressed),
        )

        return compressed

    def _embeddings_filter(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Document]:
        """Filter document sentences by embedding similarity."""
        if self.embedding_service is None:
            logger.warning("No embedding service for embeddings filter")
            return documents

        import numpy as np

        threshold = self.config.similarity_threshold
        query_embedding = np.array(self.embedding_service.embed_query(query))

        compressed = []

        for doc in documents:
            # Split into sentences
            sentences = self._split_sentences(doc.content)
            if not sentences:
                compressed.append(doc)
                continue

            # Embed sentences
            sentence_embeddings = np.array(
                self.embedding_service.embed_documents(sentences)
            )

            # Calculate similarities
            similarities = self._cosine_similarities(query_embedding, sentence_embeddings)

            # Keep sentences above threshold
            kept_sentences = [
                sent for sent, sim in zip(sentences, similarities)
                if sim >= threshold
            ]

            if kept_sentences:
                compressed_content = " ".join(kept_sentences)
                compressed_doc = Document(
                    id=doc.id,
                    content=compressed_content,
                    metadata={**doc.metadata, "compressed": True},
                    score=doc.score,
                )
                compressed.append(compressed_doc)
            else:
                compressed.append(doc)

        return compressed

    def _llm_chain_filter(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Document]:
        """Filter documents using LLM relevance judgment."""
        if self.llm_service is None:
            logger.warning("No LLM service for chain filter")
            return documents

        filter_prompt = """Is the following document relevant to answering the question?
Answer only 'yes' or 'no'.

Question: {query}

Document: {content}

Is relevant:"""

        filtered = []

        for doc in documents:
            try:
                # Truncate for efficiency
                content = doc.content[:1000]

                result = self.llm_service.generate(
                    query=filter_prompt.format(query=query, content=content),
                    context=[],
                )

                answer = result.answer.strip().lower()
                if "yes" in answer:
                    filtered.append(doc)

            except Exception as e:
                logger.warning(f"Filter check failed: {e}")
                filtered.append(doc)  # Keep on error

        return filtered if filtered else documents

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        import re

        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _cosine_similarities(
        self,
        query_vec: Any,
        doc_vecs: Any,
    ) -> List[float]:
        """Calculate cosine similarities."""
        import numpy as np

        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)

        similarities = np.dot(doc_vecs, query_vec) / (doc_norms * query_norm + 1e-10)
        return similarities.tolist()

    def _calc_compression_ratio(
        self,
        original: List[Document],
        compressed: List[Document],
    ) -> float:
        """Calculate average compression ratio."""
        if not original:
            return 1.0

        original_len = sum(len(d.content) for d in original)
        compressed_len = sum(len(d.content) for d in compressed)

        return compressed_len / original_len if original_len > 0 else 1.0
