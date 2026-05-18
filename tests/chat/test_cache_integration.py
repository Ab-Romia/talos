"""
End-to-end tests for cache layer with service integration.

Tests hot/cold cache behavior, TTL expiration, size-based eviction,
deduplication, and seamless merging for paginated retrieval.
"""
import time

from backend.chat import WSMessage
from backend.chat.cache import HotColdCache
from backend.chat.service import store_message, get_messages, get_message_by_id


class TestCacheHotStorage:
    """Hot cache (in-memory) behavior."""

    def test_message_put_appears_in_hot(self, fresh_cache, test_users, test_channel):
        """Message put() immediately appears in hot cache."""
        user = test_users[0]
        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Test",
        )

        fresh_cache.put(msg)
        hot_msgs = fresh_cache.get_hot(test_channel.id)

        assert len(hot_msgs) == 1
        assert hot_msgs[0].id == msg.id

    def test_multiple_messages_hot_cache(self, fresh_cache, test_users, test_channel):
        """Multiple messages accumulate in hot cache."""
        user = test_users[0]

        msgs = []
        for i in range(10):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)
            msgs.append(msg)

        hot_msgs = fresh_cache.get_hot(test_channel.id)

        assert len(hot_msgs) == 10
        for msg in msgs:
            assert any(h.id == msg.id for h in hot_msgs)

    def test_hot_cache_size_limit_eviction(self, fresh_cache, test_users, test_channel):
        """Oldest messages evicted from hot when exceeds HOT_MAX_PER_CHANNEL (100)."""
        user = test_users[0]

        # Send 120 messages (exceeds max of 100)
        msg_ids = []
        for i in range(120):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)
            msg_ids.append(msg.id)

        hot_msgs = fresh_cache.get_hot(test_channel.id)

        # Hot cache should have 100 most recent
        assert len(hot_msgs) == 100
        # First 20 should not be in hot (evicted)
        hot_ids = {m.id for m in hot_msgs}
        for i in range(20):
            assert msg_ids[i] not in hot_ids
        # Last 100 should be in hot
        for i in range(20, 120):
            assert msg_ids[i] in hot_ids


class TestCacheColdStorage:
    """Cold cache (persistent) behavior."""

    def test_message_put_persists_to_cold(self, fresh_cache, test_users, test_channel):
        """Message put() also persists to cold storage."""
        user = test_users[0]
        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Test",
        )

        fresh_cache.put(msg)
        cold_msgs = fresh_cache._load_cold(test_channel.id)

        assert len(cold_msgs) == 1
        assert cold_msgs[0].id == msg.id

    def test_evicted_messages_in_cold(self, fresh_cache, test_users, test_channel):
        """Messages evicted from hot cache are in cold storage."""
        user = test_users[0]

        # Send 110 messages
        first_msg = None
        for i in range(110):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)
            if i == 0:
                first_msg = msg

        # First message should not be in hot (evicted)
        hot_msgs = fresh_cache.get_hot(test_channel.id)
        assert first_msg.id not in {m.id for m in hot_msgs}

        # But should be in cold
        cold_msgs = fresh_cache._load_cold(test_channel.id)
        assert any(m.id == first_msg.id for m in cold_msgs)


class TestCacheHotColdMerge:
    """Hot and cold cache merging and deduplication."""

    def test_get_all_merges_hot_and_cold(self, fresh_cache, test_users, test_channel):
        """get_all() merges hot and cold caches."""
        user = test_users[0]

        # Send 110 messages (some in hot, some in cold)
        for i in range(110):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)

        all_msgs = fresh_cache.get_all(test_channel.id)

        assert len(all_msgs) == 110

    def test_get_all_deduplicates_messages(self, fresh_cache, test_users, test_channel):
        """get_all() deduplicates if same message in both hot and cold."""
        user = test_users[0]

        for i in range(110):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)

        all_msgs = fresh_cache.get_all(test_channel.id)
        msg_ids = [m.id for m in all_msgs]

        # Should be no duplicates
        assert len(msg_ids) == len(set(msg_ids))

    def test_get_all_sorted_by_sent_at(self, fresh_cache, test_users, test_channel):
        """get_all() returns messages sorted by sent_at."""
        user = test_users[0]

        for i in range(50):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)

        all_msgs = fresh_cache.get_all(test_channel.id)

        # Verify sorted ascending
        for i in range(len(all_msgs) - 1):
            assert all_msgs[i].sent_at <= all_msgs[i + 1].sent_at

    def test_get_all_pagination_across_boundary(self, fresh_cache, test_users, test_channel):
        """Pagination works correctly across hot/cold boundary."""
        user = test_users[0]

        # Send 50 messages (all in hot initially)
        for i in range(50):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)

        # Send 60 more (first 50 go to cold)
        for i in range(50, 110):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)

        # Paginate with offset that crosses boundary
        page = fresh_cache.get_all(test_channel.id, limit=30, offset=40)

        assert len(page) == 30
        # Check we got the right messages
        texts = [m.text for m in page]
        expected_texts = [f"Message {i}" for i in range(40, 70)]
        assert texts == expected_texts


class TestCacheTTLExpiration:
    """TTL-based cache expiration."""

    def test_ttl_stale_eviction(self, test_users, test_channel):
        """Messages older than TTL removed from hot cache."""
        # Create cache with short TTL
        cache = HotColdCache(ttl=1)  # 1 second TTL
        user = test_users[0]

        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Old message",
        )

        cache.put(msg)
        hot_before = cache.get_hot(test_channel.id)
        assert len(hot_before) == 1

        # Wait for TTL to expire
        time.sleep(1.1)

        hot_after = cache.get_hot(test_channel.id)
        assert len(hot_after) == 0

    def test_ttl_expired_messages_still_in_cold(self, test_users, test_channel):
        """TTL-expired messages remain in cold storage."""
        cache = HotColdCache(ttl=1)
        user = test_users[0]

        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Old message",
        )

        cache.put(msg)

        # Wait for TTL to expire
        time.sleep(1.1)

        hot_msgs = cache.get_hot(test_channel.id)
        assert len(hot_msgs) == 0

        cold_msgs = cache._load_cold(test_channel.id)
        assert len(cold_msgs) == 1
        assert cold_msgs[0].id == msg.id

    def test_get_all_includes_expired_messages(self, test_users, test_channel):
        """get_all() includes expired messages from cold storage."""
        cache = HotColdCache(ttl=1)
        user = test_users[0]

        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Old message",
        )

        cache.put(msg)
        time.sleep(1.1)

        all_msgs = cache.get_all(test_channel.id)

        assert len(all_msgs) == 1
        assert all_msgs[0].id == msg.id


class TestCacheWithServiceLayer:
    """Cache integration with service layer (end-to-end)."""

    def test_service_send_uses_cache(self, test_users, test_channel):
        """Service layer send_message uses cache automatically."""
        user = test_users[0]

        msg = store_message(test_channel.id, user.id, "Test via service")

        # Verify in cache
        retrieved = get_message_by_id(test_channel.id, msg.id)

        assert retrieved is not None
        assert retrieved.text == "Test via service"

    def test_service_retrieval_honors_cache_state(self, test_users, test_channel):
        """Service layer retrieval gets merged cache results."""
        user = test_users[0]

        # Send 120 messages (creates hot/cold split)
        msg_ids = []
        for i in range(120):
            msg = store_message(test_channel.id, user.id, f"Message {i}")
            msg_ids.append(msg.id)

        # Get all via service
        all_msgs = get_messages(test_channel.id)

        assert len(all_msgs) == 120
        # All messages accessible
        for i in range(120):
            assert any(m.id == msg_ids[i] for m in all_msgs)

    def test_service_pagination_across_cache_layers(self, test_users, test_channel):
        """Service pagination works across hot/cold boundary."""
        user = test_users[0]

        # Create hot/cold split
        for i in range(120):
            store_message(test_channel.id, user.id, f"Message {i}")

        # Paginate with offset crossing boundary
        page = get_messages(test_channel.id, limit=30, offset=50)

        assert len(page) == 30
        # Check correct messages
        for i, msg in enumerate(page):
            assert msg.text == f"Message {50 + i}"


class TestCacheGetById:
    """Cache lookup by message ID."""

    def test_get_by_id_checks_hot_first(self, fresh_cache, test_users, test_channel):
        """get_by_id() checks hot cache first."""
        user = test_users[0]

        msg = WSMessage(
            channel_id=test_channel.id,
            sender_id=user.id,
            text="Test",
        )

        fresh_cache.put(msg)
        retrieved = fresh_cache.get_by_id(test_channel.id, msg.id)

        assert retrieved is not None
        assert retrieved.id == msg.id

    def test_get_by_id_falls_back_to_cold(self, fresh_cache, test_users, test_channel):
        """get_by_id() falls back to cold storage if not in hot."""
        user = test_users[0]

        # Send 110 messages (first evicted to cold)
        first_msg_id = None
        for i in range(110):
            msg = WSMessage(
                channel_id=test_channel.id,
                sender_id=user.id,
                text=f"Message {i}",
            )
            fresh_cache.put(msg)
            if i == 0:
                first_msg_id = msg.id

        # First message in cold, not in hot
        retrieved = fresh_cache.get_by_id(test_channel.id, first_msg_id)

        assert retrieved is not None
        assert retrieved.id == first_msg_id
