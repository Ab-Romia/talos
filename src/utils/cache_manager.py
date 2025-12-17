"""
Cache management for embeddings and retrieval results.

Provides efficient caching to reduce API calls and improve performance.
"""

import hashlib
import json
import pickle
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class LRUCache(Generic[T]):
    """Thread-safe LRU cache implementation."""

    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        self._cache: OrderedDict[str, T] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """Get item from cache."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: T) -> None:
        """Set item in cache."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        """Delete item from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


class TTLCache(Generic[T]):
    """Thread-safe cache with time-to-live expiration."""

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, tuple[T, datetime]] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """Get item from cache if not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if datetime.now() - timestamp < timedelta(seconds=self.ttl_seconds):
                    self._hits += 1
                    return value
                # Expired
                del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: T) -> None:
        """Set item in cache with current timestamp."""
        with self._lock:
            # Cleanup expired entries if cache is full
            if len(self._cache) >= self.maxsize:
                self._cleanup_expired()

            self._cache[key] = (value, datetime.now())

            # If still full after cleanup, remove oldest
            if len(self._cache) > self.maxsize:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]

    def _cleanup_expired(self) -> None:
        """Remove expired entries."""
        now = datetime.now()
        expired = [
            k for k, (_, ts) in self._cache.items()
            if now - ts >= timedelta(seconds=self.ttl_seconds)
        ]
        for k in expired:
            del self._cache[k]

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }


class EmbeddingCache:
    """
    Specialized cache for embeddings with persistence support.

    Caches text-to-embedding mappings to reduce API calls.
    """

    def __init__(
        self,
        maxsize: int = 10000,
        persist_path: Optional[str] = None,
        model_name: str = "default",
    ):
        self.maxsize = maxsize
        self.persist_path = Path(persist_path) if persist_path else None
        self.model_name = model_name
        self._cache: LRUCache[List[float]] = LRUCache(maxsize=maxsize)

        # Load persisted cache if available
        if self.persist_path and self.persist_path.exists():
            self._load()

    def _hash_text(self, text: str) -> str:
        """Generate hash key for text."""
        content = f"{self.model_name}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, text: str) -> Optional[List[float]]:
        """Get embedding from cache."""
        key = self._hash_text(text)
        return self._cache.get(key)

    def set(self, text: str, embedding: List[float]) -> None:
        """Store embedding in cache."""
        key = self._hash_text(text)
        self._cache.set(key, embedding)

    def get_many(self, texts: List[str]) -> tuple[Dict[str, List[float]], List[str]]:
        """
        Get embeddings for multiple texts.

        Returns:
            Tuple of (cached embeddings dict, list of uncached texts)
        """
        cached = {}
        uncached = []

        for text in texts:
            embedding = self.get(text)
            if embedding is not None:
                cached[text] = embedding
            else:
                uncached.append(text)

        return cached, uncached

    def set_many(self, embeddings: Dict[str, List[float]]) -> None:
        """Store multiple embeddings."""
        for text, embedding in embeddings.items():
            self.set(text, embedding)

    def save(self) -> None:
        """Persist cache to disk."""
        if self.persist_path:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persist_path, "wb") as f:
                pickle.dump(dict(self._cache._cache), f)

    def _load(self) -> None:
        """Load cache from disk."""
        if self.persist_path and self.persist_path.exists():
            try:
                with open(self.persist_path, "rb") as f:
                    data = pickle.load(f)
                    for key, value in data.items():
                        self._cache.set(key, value)
            except (pickle.UnpicklingError, EOFError):
                # Corrupted cache file, start fresh
                pass

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        if self.persist_path and self.persist_path.exists():
            self.persist_path.unlink()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = self._cache.stats()
        stats["model_name"] = self.model_name
        stats["persist_path"] = str(self.persist_path) if self.persist_path else None
        return stats


class CacheManager:
    """
    Central cache manager for the RAG system.

    Manages multiple caches for different purposes.
    """

    def __init__(
        self,
        embedding_cache_size: int = 10000,
        retrieval_cache_size: int = 1000,
        retrieval_cache_ttl: int = 300,
        persist_dir: Optional[str] = None,
    ):
        self.persist_dir = Path(persist_dir) if persist_dir else None

        # Embedding cache (persistent)
        embed_persist = None
        if self.persist_dir:
            embed_persist = str(self.persist_dir / "embedding_cache.pkl")
        self.embedding_cache = EmbeddingCache(
            maxsize=embedding_cache_size,
            persist_path=embed_persist,
        )

        # Retrieval results cache (TTL-based)
        self.retrieval_cache: TTLCache[Any] = TTLCache(
            maxsize=retrieval_cache_size,
            ttl_seconds=retrieval_cache_ttl,
        )

        # Query processing cache (LRU)
        self.query_cache: LRUCache[Dict[str, Any]] = LRUCache(maxsize=500)

    def get_retrieval_key(self, query: str, top_k: int, method: str) -> str:
        """Generate cache key for retrieval results."""
        content = f"{query}:{top_k}:{method}"
        return hashlib.sha256(content.encode()).hexdigest()

    def cache_retrieval(
        self,
        query: str,
        top_k: int,
        method: str,
        results: Any,
    ) -> None:
        """Cache retrieval results."""
        key = self.get_retrieval_key(query, top_k, method)
        self.retrieval_cache.set(key, results)

    def get_cached_retrieval(
        self,
        query: str,
        top_k: int,
        method: str,
    ) -> Optional[Any]:
        """Get cached retrieval results."""
        key = self.get_retrieval_key(query, top_k, method)
        return self.retrieval_cache.get(key)

    def save_all(self) -> None:
        """Persist all caches."""
        self.embedding_cache.save()

    def clear_all(self) -> None:
        """Clear all caches."""
        self.embedding_cache.clear()
        self.retrieval_cache.clear()
        self.query_cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get statistics for all caches."""
        return {
            "embedding_cache": self.embedding_cache.stats(),
            "retrieval_cache": self.retrieval_cache.stats(),
            "query_cache": self.query_cache.stats(),
        }
