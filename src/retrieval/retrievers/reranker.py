"""
Cross-encoder reranker for two-stage retrieval.

Provides more accurate relevance scoring using cross-attention.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.base_interfaces import BaseReranker, Document
from src.core.config_loader import RerankerConfig
from src.core.exceptions import RerankerError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CrossEncoderReranker(BaseReranker):
    """
    Cross-encoder reranker using sentence-transformers.

    Provides more accurate relevance scoring than bi-encoder retrieval.
    """

    def __init__(self, config: RerankerConfig):
        """
        Initialize cross-encoder reranker.

        Args:
            config: Reranker configuration
        """
        self.config = config
        self._model = None

        if config.enabled:
            self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize the cross-encoder model."""
        try:
            from sentence_transformers import CrossEncoder

            device = "cuda" if self.config.use_gpu else "cpu"
            self._model = CrossEncoder(
                self.config.model_name,
                device=device,
            )
            logger.info(
                f"Initialized cross-encoder reranker",
                model=self.config.model_name,
                device=device,
            )

        except ImportError:
            raise ImportError(
                "sentence-transformers is required for reranking. "
                "Install with: pip install sentence-transformers"
            )

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        """
        Rerank documents based on query relevance.

        Args:
            query: Query string
            documents: Documents to rerank
            top_n: Number of documents to return after reranking

        Returns:
            Reranked documents
        """
        if not self.config.enabled or not documents:
            return documents[:top_n] if top_n else documents

        if self._model is None:
            self._initialize_model()

        top_n = top_n or self.config.top_n
        start_time = time.perf_counter()

        try:
            # Create query-document pairs
            pairs = [(query, doc.content) for doc in documents]

            # Score pairs
            scores = self._model.predict(
                pairs,
                batch_size=self.config.batch_size,
                show_progress_bar=False,
            )

            # Sort by score
            scored_docs = list(zip(documents, scores))
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            # Filter by threshold and limit
            results = []
            for doc, score in scored_docs[:top_n]:
                if score >= self.config.relevance_threshold:
                    doc.score = float(score)
                    results.append(doc)

            latency_ms = (time.perf_counter() - start_time) * 1000

            logger.debug(
                f"Reranked {len(documents)} -> {len(results)} documents",
                latency_ms=f"{latency_ms:.2f}",
            )

            return results

        except Exception as e:
            raise RerankerError(
                f"Reranking failed: {e}",
                model=self.config.model_name,
                num_documents=len(documents),
                cause=e,
            )

    def score(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Tuple[Document, float]]:
        """
        Score documents without reordering.

        Args:
            query: Query string
            documents: Documents to score

        Returns:
            Documents with scores (original order)
        """
        if not self.config.enabled or not documents:
            return [(doc, doc.score or 0.0) for doc in documents]

        if self._model is None:
            self._initialize_model()

        try:
            pairs = [(query, doc.content) for doc in documents]
            scores = self._model.predict(
                pairs,
                batch_size=self.config.batch_size,
                show_progress_bar=False,
            )

            return [(doc, float(score)) for doc, score in zip(documents, scores)]

        except Exception as e:
            raise RerankerError(
                f"Scoring failed: {e}",
                model=self.config.model_name,
                num_documents=len(documents),
                cause=e,
            )


class CohereReranker(BaseReranker):
    """
    Cohere reranker using Cohere's Rerank API.

    Provides high-quality reranking via API.
    """

    def __init__(
        self,
        config: RerankerConfig,
        api_key_env: str = "COHERE_API_KEY",
    ):
        self.config = config
        self.api_key_env = api_key_env
        self._client = None

        if config.enabled:
            self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Cohere client."""
        import os

        try:
            import cohere

            api_key = os.getenv(self.api_key_env)
            if not api_key:
                raise RerankerError(
                    f"Cohere API key not found in {self.api_key_env}",
                    model=self.config.model_name,
                )

            self._client = cohere.Client(api_key)

        except ImportError:
            raise ImportError(
                "cohere is required for Cohere reranker. "
                "Install with: pip install cohere"
            )

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        """Rerank documents using Cohere."""
        if not self.config.enabled or not documents:
            return documents[:top_n] if top_n else documents

        if self._client is None:
            self._initialize_client()

        top_n = top_n or self.config.top_n

        try:
            # Extract document texts
            doc_texts = [doc.content for doc in documents]

            # Call Cohere Rerank
            response = self._client.rerank(
                query=query,
                documents=doc_texts,
                top_n=top_n,
                model=self.config.model_name or "rerank-english-v3.0",
            )

            # Map results back to documents
            results = []
            for result in response.results:
                doc = documents[result.index]
                doc.score = result.relevance_score
                if doc.score >= self.config.relevance_threshold:
                    results.append(doc)

            return results

        except Exception as e:
            raise RerankerError(
                f"Cohere reranking failed: {e}",
                model=self.config.model_name,
                num_documents=len(documents),
                cause=e,
            )

    def score(
        self,
        query: str,
        documents: List[Document],
    ) -> List[Tuple[Document, float]]:
        """Score documents using Cohere."""
        if not self.config.enabled or not documents:
            return [(doc, doc.score or 0.0) for doc in documents]

        reranked = self.rerank(query, documents, top_n=len(documents))
        return [(doc, doc.score or 0.0) for doc in reranked]
