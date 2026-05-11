"""
Hot / Cold cache for chat messages.

Hot  → in-memory deque per channel, capped by size and TTL.
        Represents recently-active data that must be served with
        the lowest possible latency.

Cold → persistent store (currently an in-memory dict; swap the
        _persist() / _load_cold() stubs for SQLAlchemy / Redis /
        any real DB without changing the public interface).

Write path  :  put()  writes to BOTH hot and cold atomically.
Read path   :  get_hot()  serves only live cache.
               get_all()  merges hot + cold, deduplicates, paginates.
"""

import time
from collections import defaultdict, deque
from uuid import UUID

from .models import WSMessage

HOT_TTL_SECONDS: int = 300  # message stays hot for 5 min after arrival
HOT_MAX_PER_CHANNEL: int = 100  # max messages held in hot cache per channel


class HotColdCache:
    def __init__(self, ttl: int = HOT_TTL_SECONDS, max_hot: int = HOT_MAX_PER_CHANNEL) -> None:
        self._ttl = ttl
        self._max_hot = max_hot

        # TODO:
        #  for hot: Use Redis + rabbitmq for hot cache in a multi-worker deployment (shared state + pub/sub eviction).
        #  for cold: Database storage (replace the in-memory dict with SQLAlchemy calls).

        # hot:  channel_id → deque[(monotonic_ts, Message)]
        self._hot: dict[UUID, deque[tuple[float, WSMessage]]] = defaultdict(deque)
        # cold: channel_id → list[Message]
        self._cold: dict[UUID, list[WSMessage]] = defaultdict(list)

    def put(self, message: WSMessage) -> None:
        """
        Write a message into the hot cache and persist it to cold storage.
        If the hot cache overflows, the oldest entry is evicted to cold.
        """
        cid = message.channel_id
        now = time.monotonic()

        hot = self._hot[cid]
        hot.append((now, message))

        # Size-based eviction: oldest entry leaves hot → cold
        while len(hot) > self._max_hot:
            _, evicted = hot.popleft()
            self._persist(evicted)

        # Always persist to cold (primary store)
        self._persist(message)

    def get_hot(self, channel_id: UUID) -> list[WSMessage]:
        """Return messages currently in the hot cache, pruning stale ones."""
        self._evict_stale(channel_id)
        return [msg for _, msg in self._hot[channel_id]]

    def get_all(self, channel_id: UUID, limit: int | None = None, offset: int = 0, ) -> list[WSMessage]:
        """
        Merge hot + cold, deduplicate by message id, sort by created_at,
        then return the requested page.
        """
        self._evict_stale(channel_id)

        seen: set[UUID] = set()
        merged: list[WSMessage] = []

        # Cold first (full history)
        for msg in self._load_cold(channel_id):
            if msg.id not in seen:
                seen.add(msg.id)
                merged.append(msg)

        # Hot may contain messages not yet flushed to the DB snapshot
        for _, msg in self._hot[channel_id]:
            if msg.id not in seen:
                seen.add(msg.id)
                merged.append(msg)

        merged.sort(key=lambda m: m.sent_at)
        if limit is None:
            return merged[offset:]
        return merged[offset: offset + limit]

    def get_by_id(self, channel_id: UUID, message_id: UUID) -> WSMessage | None:
        """Lookup a single message; checks hot cache first, then cold."""
        for _, msg in self._hot[channel_id]:
            if msg.id == message_id:
                return msg
        for msg in self._load_cold(channel_id):
            if msg.id == message_id:
                return msg
        return None

    def _evict_stale(self, channel_id: UUID) -> None:
        """Remove TTL-expired entries from the hot cache."""
        now = time.monotonic()
        hot = self._hot[channel_id]
        while hot and (now - hot[0][0]) > self._ttl:
            hot.popleft()  # already persisted on put(); just drop from hot

    def _persist(self, message: WSMessage) -> None:
        """
        Cold-storage write.
        Replace this stub with an async DB call / SQLAlchemy session flush.
        """
        cold = self._cold[message.channel_id]
        # Avoid duplicate writes (hot overflow + initial put)
        if not cold or cold[-1].id != message.id:
            cold.append(message)

    def _load_cold(self, channel_id: UUID) -> list[WSMessage]:
        """
        Cold-storage read.
        Replace this stub with a DB query (e.g. SELECT … ORDER BY created_at).
        """
        return list(self._cold[channel_id])


# Module-level singleton — import and use directly everywhere
cache = HotColdCache()
