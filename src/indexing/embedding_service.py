"""
Embedding service with multi-provider support.

Supports OpenAI, HuggingFace, Cohere, and local models for
generating vector embeddings.
"""

import os
import time
from abc import ABC
from typing import Dict, List, Optional

from src.core.base_interfaces import BaseEmbedding
from src.core.config_loader import EmbeddingConfig
from src.core.exceptions import EmbeddingError, EmbeddingRateLimitError
from src.utils.logger import get_logger
from src.utils.cache_manager import EmbeddingCache
from src.utils.async_helpers import sync_retry

logger = get_logger(__name__)


class EmbeddingService(BaseEmbedding, ABC):
    """Base class for embedding services."""

    def __init__(self, config: EmbeddingConfig, cache: Optional[EmbeddingCache] = None):
        self.config = config
        self.cache = cache or EmbeddingCache(model_name=config.model_name)

    def embed_with_cache(self, texts: List[str]) -> List[List[float]]:
        """Embed texts with caching support."""
        cached, uncached = self.cache.get_many(texts)

        if uncached:
            new_embeddings = self.embed_documents(uncached)
            for text, embedding in zip(uncached, new_embeddings):
                cached[text] = embedding
                self.cache.set(text, embedding)

        return [cached[text] for text in texts]


class OpenAIEmbedding(EmbeddingService):
    """OpenAI embedding implementation."""

    def __init__(
        self,
        config: Optional[EmbeddingConfig] = None,
        cache: Optional[EmbeddingCache] = None,
    ):
        config = config or EmbeddingConfig(
            provider="openai",
            model_name="text-embedding-3-small",
            dimension=1536,
        )
        super().__init__(config, cache)

        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize OpenAI client."""
        try:
            from openai import OpenAI

            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise EmbeddingError(
                    f"API key not found in environment variable: {self.config.api_key_env}",
                    model=self.config.model_name,
                )

            client_kwargs = {"api_key": api_key}
            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url

            self._client = OpenAI(**client_kwargs)

        except ImportError:
            raise ImportError(
                "openai is required for OpenAI embeddings. "
                "Install it with: pip install openai"
            )

    @sync_retry(max_retries=3, base_delay=1.0)
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query."""
        cached = self.cache.get(text)
        if cached is not None:
            return cached

        try:
            response = self._client.embeddings.create(
                model=self.config.model_name,
                input=text,
            )
            embedding = response.data[0].embedding

            if self.config.normalize:
                embedding = self._normalize(embedding)

            self.cache.set(text, embedding)
            return embedding

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise EmbeddingRateLimitError(cause=e)
            raise EmbeddingError(
                f"Failed to generate embedding: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents with batching."""
        if not texts:
            return []

        all_embeddings = []

        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i : i + self.config.batch_size]
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    @sync_retry(max_retries=3, base_delay=1.0)
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts."""
        try:
            start_time = time.perf_counter()

            response = self._client.embeddings.create(
                model=self.config.model_name,
                input=texts,
            )

            embeddings = [item.embedding for item in response.data]

            if self.config.normalize:
                embeddings = [self._normalize(e) for e in embeddings]

            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                f"Embedded batch of {len(texts)} texts",
                latency_ms=f"{latency_ms:.2f}",
            )

            return embeddings

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise EmbeddingRateLimitError(cause=e)
            raise EmbeddingError(
                f"Failed to generate batch embeddings: {e}",
                model=self.config.model_name,
                batch_size=len(texts),
                cause=e,
            )

    def _normalize(self, embedding: List[float]) -> List[float]:
        """Normalize embedding to unit length."""
        import math

        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            return [x / norm for x in embedding]
        return embedding

    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return self.config.dimension

    @property
    def model_name(self) -> str:
        """Return model name."""
        return self.config.model_name


class HuggingFaceEmbedding(EmbeddingService):
    """HuggingFace/Sentence Transformers embedding implementation."""

    def __init__(
        self,
        config: Optional[EmbeddingConfig] = None,
        cache: Optional[EmbeddingCache] = None,
    ):
        config = config or EmbeddingConfig(
            provider="huggingface",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            dimension=384,
        )
        super().__init__(config, cache)

        self._model = None
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize sentence transformer model."""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.model_name)

            # Update dimension from model
            self.config.dimension = self._model.get_sentence_embedding_dimension()

        except ImportError:
            raise ImportError(
                "sentence-transformers is required for HuggingFace embeddings. "
                "Install it with: pip install sentence-transformers"
            )

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query."""
        cached = self.cache.get(text)
        if cached is not None:
            return cached

        try:
            embedding = self._model.encode(
                text,
                normalize_embeddings=self.config.normalize,
            ).tolist()

            self.cache.set(text, embedding)
            return embedding

        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate embedding: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        if not texts:
            return []

        try:
            start_time = time.perf_counter()

            embeddings = self._model.encode(
                texts,
                batch_size=self.config.batch_size,
                normalize_embeddings=self.config.normalize,
                show_progress_bar=False,
            ).tolist()

            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                f"Embedded {len(texts)} documents",
                latency_ms=f"{latency_ms:.2f}",
            )

            return embeddings

        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate embeddings: {e}",
                model=self.config.model_name,
                batch_size=len(texts),
                cause=e,
            )

    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return self.config.dimension

    @property
    def model_name(self) -> str:
        """Return model name."""
        return self.config.model_name


class CohereEmbedding(EmbeddingService):
    """Cohere embedding implementation."""

    def __init__(
        self,
        config: Optional[EmbeddingConfig] = None,
        cache: Optional[EmbeddingCache] = None,
    ):
        config = config or EmbeddingConfig(
            provider="cohere",
            model_name="embed-english-v3.0",
            dimension=1024,
            api_key_env="COHERE_API_KEY",
        )
        super().__init__(config, cache)

        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Cohere client."""
        try:
            import cohere

            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise EmbeddingError(
                    f"API key not found: {self.config.api_key_env}",
                    model=self.config.model_name,
                )

            self._client = cohere.Client(api_key)

        except ImportError:
            raise ImportError(
                "cohere is required for Cohere embeddings. "
                "Install it with: pip install cohere"
            )

    @sync_retry(max_retries=3, base_delay=1.0)
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query."""
        cached = self.cache.get(text)
        if cached is not None:
            return cached

        try:
            response = self._client.embed(
                texts=[text],
                model=self.config.model_name,
                input_type="search_query",
            )
            embedding = response.embeddings[0]

            self.cache.set(text, embedding)
            return embedding

        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate embedding: {e}",
                model=self.config.model_name,
                cause=e,
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        if not texts:
            return []

        all_embeddings = []

        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i : i + self.config.batch_size]
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    @sync_retry(max_retries=3, base_delay=1.0)
    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts."""
        try:
            response = self._client.embed(
                texts=texts,
                model=self.config.model_name,
                input_type="search_document",
            )
            return response.embeddings

        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate batch embeddings: {e}",
                model=self.config.model_name,
                batch_size=len(texts),
                cause=e,
            )

    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return self.config.dimension

    @property
    def model_name(self) -> str:
        """Return model name."""
        return self.config.model_name


def create_embedding_service(
    config: EmbeddingConfig,
    cache: Optional[EmbeddingCache] = None,
) -> EmbeddingService:
    """
    Factory function to create embedding service based on config.

    Args:
        config: Embedding configuration
        cache: Optional embedding cache

    Returns:
        Appropriate embedding service instance
    """
    provider_map = {
        "openai": OpenAIEmbedding,
        "huggingface": HuggingFaceEmbedding,
        "sentence_transformers": HuggingFaceEmbedding,
        "cohere": CohereEmbedding,
    }

    provider_class = provider_map.get(config.provider)
    if provider_class is None:
        raise EmbeddingError(
            f"Unknown embedding provider: {config.provider}",
            details={"supported_providers": list(provider_map.keys())},
        )

    return provider_class(config, cache)
