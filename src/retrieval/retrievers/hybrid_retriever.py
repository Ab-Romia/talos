"""
Hybrid retriever combining dense and sparse retrieval.

Uses Reciprocal Rank Fusion (RRF) to combine results.
"""

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.base_interfaces import BaseRetriever, BaseVectorStore, Document, RetrievalResult
from src.core.config_loader import RetrieverConfig
from src.core.exceptions import RetrievalError
from src.indexing.embedding_service import EmbeddingService
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BM25Index:
    """Simple BM25 index for sparse retrieval."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: List[Document] = []
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.doc_freqs: Dict[str, int] = {}
        self.term_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}

    def index(self, documents: List[Document]) -> None:
        """Build BM25 index from documents."""
        import math

        self.documents = documents
        self.term_freqs = []
        self.doc_freqs = {}

        for doc in documents:
            tokens = self._tokenize(doc.content)
            self.doc_lengths.append(len(tokens))

            # Term frequency for this document
            tf: Dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            self.term_freqs.append(tf)

            # Document frequency
            for token in set(tokens):
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0

        # Calculate IDF
        n_docs = len(documents)
        for term, df in self.doc_freqs.items():
            self.idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
        """Search using BM25 scoring."""
        query_tokens = self._tokenize(query)
        scores = []

        for i, doc in enumerate(self.documents):
            score = 0.0
            doc_len = self.doc_lengths[i]
            tf = self.term_freqs[i]

            for token in query_tokens:
                if token in tf:
                    term_freq = tf[token]
                    idf = self.idf.get(token, 0)

                    # BM25 formula
                    numerator = term_freq * (self.k1 + 1)
                    denominator = term_freq + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_length)
                    score += idf * numerator / denominator

            scores.append((doc, score))

        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text."""
        text = text.lower()
        tokens = re.findall(r'\b\w+\b', text)
        return tokens


class HybridRetriever(BaseRetriever):
    """
    Hybrid retriever combining dense and sparse (BM25) retrieval.

    Uses Reciprocal Rank Fusion (RRF) for result combination.
    """

    def __init__(
        self,
        config: RetrieverConfig,
        vector_store: BaseVectorStore,
        embedding_service: EmbeddingService,
        collection_name: str,
        documents: Optional[List[Document]] = None,
    ):
        """
        Initialize hybrid retriever.

        Args:
            config: Retriever configuration
            vector_store: Vector store for dense retrieval
            embedding_service: Embedding service
            collection_name: Collection name
            documents: Documents for BM25 index (optional, can be set later)
        """
        self.config = config
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.collection_name = collection_name

        # BM25 index
        self.bm25_index = BM25Index()
        if documents:
            self.bm25_index.index(documents)

    def set_documents(self, documents: List[Document]) -> None:
        """Set documents for BM25 index."""
        self.bm25_index.index(documents)

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        Retrieve using hybrid search.

        Args:
            query: Query string
            top_k: Number of documents to retrieve
            filters: Optional metadata filters

        Returns:
            RetrievalResult with fused results
        """
        top_k = top_k or self.config.top_k
        start_time = time.perf_counter()

        try:
            # Retrieve more candidates for fusion
            pool_size = min(top_k * 3, 100)

            # Dense retrieval
            dense_results = self._dense_retrieve(query, pool_size, filters)

            # Sparse retrieval (BM25)
            sparse_results = self._sparse_retrieve(query, pool_size)

            # Fuse results using RRF
            fused_docs = self._reciprocal_rank_fusion(
                dense_results,
                sparse_results,
                top_k,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            logger.log_retrieval(
                query=query,
                num_results=len(fused_docs),
                method="hybrid",
                latency_ms=latency_ms,
            )

            return RetrievalResult(
                documents=fused_docs,
                query=query,
                method="hybrid",
                total_found=len(fused_docs),
                latency_ms=latency_ms,
                metadata={
                    "dense_weight": self.config.dense_weight,
                    "sparse_weight": self.config.sparse_weight,
                },
            )

        except Exception as e:
            raise RetrievalError(
                f"Hybrid retrieval failed: {e}",
                query=query,
                retrieval_method="hybrid",
                cause=e,
            )

    def _dense_retrieve(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Perform dense retrieval."""
        # Check if collection exists
        if not self.vector_store.collection_exists(self.collection_name):
            logger.warning(f"Collection '{self.collection_name}' does not exist, skipping dense retrieval")
            return []

        query_embedding = self.embedding_service.embed_query(query)

        documents = self.vector_store.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            top_k=top_k,
            filters=filters,
        )

        return [(doc, doc.score or 0.0) for doc in documents]

    def _sparse_retrieve(
        self,
        query: str,
        top_k: int,
    ) -> List[Tuple[Document, float]]:
        """Perform BM25 sparse retrieval."""
        if not self.bm25_index.documents:
            return []
        return self.bm25_index.search(query, top_k)

    def _reciprocal_rank_fusion(
        self,
        dense_results: List[Tuple[Document, float]],
        sparse_results: List[Tuple[Document, float]],
        top_k: int,
    ) -> List[Document]:
        """
        Combine results using Reciprocal Rank Fusion (RRF).

        RRF score = sum(weight / (k + rank)) for each list
        """
        k = self.config.rrf_k
        doc_scores: Dict[str, float] = {}
        doc_map: Dict[str, Document] = {}

        # Process dense results
        for rank, (doc, _) in enumerate(dense_results):
            doc_id = doc.id or doc.content[:50]
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
                doc_scores[doc_id] = 0.0
            doc_scores[doc_id] += self.config.dense_weight / (k + rank + 1)

        # Process sparse results
        for rank, (doc, _) in enumerate(sparse_results):
            doc_id = doc.id or doc.content[:50]
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
                doc_scores[doc_id] = 0.0
            doc_scores[doc_id] += self.config.sparse_weight / (k + rank + 1)

        # Sort by fused score
        sorted_ids = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)

        results = []
        for doc_id in sorted_ids[:top_k]:
            doc = doc_map[doc_id]
            doc.score = doc_scores[doc_id]
            results.append(doc)

        return results

    def retrieve_with_scores(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Retrieve documents with scores."""
        result = self.retrieve(query, top_k, filters)
        return [(doc, doc.score or 0.0) for doc in result.documents]
