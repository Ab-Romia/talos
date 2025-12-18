"""
Dense retriever using vector similarity search.

Primary retrieval method using dense embeddings and vector search.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.base_interfaces import BaseRetriever, BaseVectorStore, Document, RetrievalResult
from src.core.config_loader import RetrieverConfig
from src.core.exceptions import RetrievalError
from src.indexing.embedding_service import EmbeddingService
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DenseRetriever(BaseRetriever):
    """
    Dense retriever using vector similarity search.

    Uses embeddings to find semantically similar documents.
    """

    def __init__(
        self,
        config: RetrieverConfig,
        vector_store: BaseVectorStore,
        embedding_service: EmbeddingService,
        collection_name: str,
    ):
        """
        Initialize dense retriever.

        Args:
            config: Retriever configuration
            vector_store: Vector store for search
            embedding_service: Embedding service for query encoding
            collection_name: Collection to search
        """
        self.config = config
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.collection_name = collection_name

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant documents for a query.

        Args:
            query: Query string
            top_k: Number of documents to retrieve
            filters: Optional metadata filters

        Returns:
            RetrievalResult with documents and metadata
        """
        top_k = top_k or self.config.top_k
        start_time = time.perf_counter()

        try:
            # Check if collection exists
            if not self.vector_store.collection_exists(self.collection_name):
                logger.warning(f"Collection '{self.collection_name}' does not exist")
                return RetrievalResult(
                    documents=[],
                    query=query,
                    method="dense",
                    total_found=0,
                    latency_ms=0,
                    metadata={"error": "collection_not_found"},
                )

            # Generate query embedding
            query_embedding = self.embedding_service.embed_query(query)

            # Search vector store
            documents = self.vector_store.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                top_k=top_k,
                filters=filters,
            )

            # Filter by similarity threshold
            if self.config.similarity_threshold > 0:
                documents = [
                    doc for doc in documents
                    if doc.score and doc.score >= self.config.similarity_threshold
                ]

            latency_ms = (time.perf_counter() - start_time) * 1000

            logger.log_retrieval(
                query=query,
                num_results=len(documents),
                method="dense",
                latency_ms=latency_ms,
            )

            return RetrievalResult(
                documents=documents,
                query=query,
                method="dense",
                total_found=len(documents),
                latency_ms=latency_ms,
            )

        except Exception as e:
            raise RetrievalError(
                f"Dense retrieval failed: {e}",
                query=query,
                retrieval_method="dense",
                cause=e,
            )

    def retrieve_with_scores(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Retrieve documents with relevance scores."""
        result = self.retrieve(query, top_k, filters)
        return [(doc, doc.score or 0.0) for doc in result.documents]


class MultiQueryRetriever(DenseRetriever):
    """
    Multi-query retriever that generates multiple query variations.

    Improves recall by searching with multiple query formulations.
    """

    def __init__(
        self,
        config: RetrieverConfig,
        vector_store: BaseVectorStore,
        embedding_service: EmbeddingService,
        collection_name: str,
        query_generator: Optional[Any] = None,
        num_queries: int = 3,
    ):
        super().__init__(config, vector_store, embedding_service, collection_name)
        self.query_generator = query_generator
        self.num_queries = num_queries

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """Retrieve using multiple query variations."""
        top_k = top_k or self.config.top_k
        start_time = time.perf_counter()

        # Generate query variations
        queries = [query]
        if self.query_generator:
            try:
                additional_queries = self.query_generator.generate(
                    query, num_queries=self.num_queries - 1
                )
                queries.extend(additional_queries)
            except Exception as e:
                logger.warning(f"Query generation failed: {e}")

        # Retrieve for each query
        all_docs: Dict[str, Document] = {}
        doc_scores: Dict[str, List[float]] = {}

        for q in queries:
            try:
                result = super().retrieve(q, top_k=top_k * 2, filters=filters)
                for doc in result.documents:
                    if doc.id not in all_docs:
                        all_docs[doc.id] = doc
                        doc_scores[doc.id] = []
                    doc_scores[doc.id].append(doc.score or 0.0)
            except RetrievalError:
                continue

        # Combine scores using RRF
        final_docs = self._fuse_results(all_docs, doc_scores, top_k)

        latency_ms = (time.perf_counter() - start_time) * 1000

        return RetrievalResult(
            documents=final_docs,
            query=query,
            method="multi_query",
            total_found=len(final_docs),
            latency_ms=latency_ms,
            metadata={"num_queries": len(queries)},
        )

    def _fuse_results(
        self,
        all_docs: Dict[str, Document],
        doc_scores: Dict[str, List[float]],
        top_k: int,
    ) -> List[Document]:
        """Fuse results from multiple queries using average score."""
        fused_scores = {}
        for doc_id, scores in doc_scores.items():
            fused_scores[doc_id] = sum(scores) / len(scores)

        # Sort by fused score
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

        results = []
        for doc_id in sorted_ids[:top_k]:
            doc = all_docs[doc_id]
            doc.score = fused_scores[doc_id]
            results.append(doc)

        return results
