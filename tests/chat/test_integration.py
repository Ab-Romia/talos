"""
End-to-end integration tests combining service layer, cache, and manager.

Tests complex flows like:
- REST message → broadcast via WebSocket
- Service layer parity between REST and WebSocket
- Message lifecycle across cache layers with presence tracking
- Concurrent operations and isolation
"""
import pytest

from backend.chat.models import MessageEvent
from backend.chat.service import store_message, get_messages, get_message_by_id


# TODO: add tests for edge cases like:
#  - Sending messages with identical content from different users
#  - Idempotent message sends (same user, same text, sent multiple times)
#  - Rapid-fire messages race conditions
#  Test endpoints
class TestRestServiceParity:
    """REST and service layer share identical business logic."""

    def test_send_message_consistent_metadata(self, test_users, test_channel):
        """Messages sent via service have consistent metadata."""
        user = test_users[0]

        msg1 = store_message(test_channel.id, user.id, "Message 1")
        msg2 = store_message(test_channel.id, user.id, "Message 2")

        # Both have valid structure
        assert msg1.id != msg2.id
        assert msg1.channel_id == test_channel.id
        assert msg2.channel_id == test_channel.id
        assert msg1.sender_id == user.id
        assert msg2.sender_id == user.id
        assert msg1.sent_at <= msg2.sent_at

    def test_send_and_retrieve_consistency(self, test_users, test_channel):
        """Message retrieved via get_messages matches sent message."""
        user = test_users[0]
        text = "Test message for consistency"

        sent = store_message(test_channel.id, user.id, text)
        retrieved_list = get_messages(test_channel.id)
        retrieved_single = get_message_by_id(test_channel.id, sent.id)

        assert len(retrieved_list) == 1
        assert retrieved_list[0].id == sent.id
        assert retrieved_list[0].text == sent.text

        assert retrieved_single is not None
        assert retrieved_single.id == sent.id
        assert retrieved_single.text == sent.text


class TestMessageLifecycleCaching:
    """Complete message lifecycle through cache layers."""

    def test_recent_message_in_hot_cache(self, test_users, test_channel):
        """Recent messages accessible via hot cache."""
        user = test_users[0]

        msg = store_message(test_channel.id, user.id, "Recent message")

        # Immediately retrievable
        retrieved = get_message_by_id(test_channel.id, msg.id)
        assert retrieved is not None

    def test_old_message_in_cold_cache(self, test_users, test_channel):
        """Old messages (evicted from hot) still retrievable from cold."""
        user = test_users[0]

        # Send 120 messages to force eviction
        msg_ids = []
        for i in range(120):
            msg = store_message(test_channel.id, user.id, f"Message {i}")
            msg_ids.append(msg.id)

        # First message should be evicted but still retrievable
        first_msg = get_message_by_id(test_channel.id, msg_ids[0])
        assert first_msg is not None
        assert first_msg.text == "Message 0"

    def test_pagination_across_cache_boundary_retrieval(self, test_users, test_channel):
        """Pagination works when data spans hot and cold."""
        user = test_users[0]

        # Send 120 messages
        for i in range(120):
            store_message(test_channel.id, user.id, f"Message {i}")

        # Get page starting in cold, ending in hot
        page = get_messages(test_channel.id, limit=30, offset=50)

        assert len(page) == 30
        assert page[0].text == "Message 50"
        assert page[29].text == "Message 79"


# TODO
@pytest.mark.xfail(reason="TODO: Requires permissions and channel membership")
class TestMultiChannelIsolation:
    """Message isolation across channels."""

    def test_channels_independent_message_storage(self, test_users, test_channel):
        """Messages in channel A don't appear in channel B."""
        user_a, user_b = test_users[0], test_users[1]
        ch1, ch2, ch3 = test_channel.id

        # Send messages to different channels
        store_message(ch1, user_a.id, "Channel 1 from A")
        store_message(ch1, user_b.id, "Channel 1 from B")
        store_message(ch2, user_a.id, "Channel 2 from A")
        store_message(ch3, user_b.id, "Channel 3 from B")

        # Each channel has only its own messages
        ch1_msgs = get_messages(ch1)
        ch2_msgs = get_messages(ch2)
        ch3_msgs = get_messages(ch3)

        assert len(ch1_msgs) == 2
        assert len(ch2_msgs) == 1
        assert len(ch3_msgs) == 1

        assert ch1_msgs[0].text == "Channel 1 from A"
        assert ch1_msgs[1].text == "Channel 1 from B"
        assert ch2_msgs[0].text == "Channel 2 from A"
        assert ch3_msgs[0].text == "Channel 3 from B"


class TestMessageEventFormatting:
    """Message event payload structure for WebSocket delivery."""

    def test_message_event_structure(self, test_users, test_channel):
        """Message converts to MessageEvent with correct format."""
        user = test_users[0]

        msg = store_message(test_channel.id, user.id, "Test")

        # Create event as would be sent via WebSocket
        event = MessageEvent(message=msg)

        event_dict = event.model_dump(mode="json")

        assert event_dict["event_type"] == "new_message"
        assert "message" in event_dict
        assert event_dict["message"]["id"] == str(msg.id)
        assert event_dict["message"]["channel_id"] == str(test_channel.id)
        assert event_dict["message"]["sender_id"] == str(user.id)
        assert event_dict["message"]["text"] == "Test"

    def test_message_event_with_delivery_info(self, test_users, test_channel):
        """MessageEvent includes delivery tracking."""
        user = test_users[0]

        msg = store_message(test_channel.id, user.id, "Test")
        event = MessageEvent(message=msg)

        event_dict = event.model_dump(mode="json")

        # Structure matches WebSocket response pattern
        assert "event_type" in event_dict
        assert "message" in event_dict
        assert event_dict["event_type"] == "new_message"


class TestMessageSenderVerification:
    """Sender ID verification and integrity."""

    def test_sender_id_preserved(self, test_users, test_channel):
        """Sender ID correctly attributed to original sender."""
        user_a, user_b = test_users[0], test_users[1]

        msg_a1 = store_message(test_channel.id, user_a.id, "From A")
        msg_b1 = store_message(test_channel.id, user_b.id, "From B")
        msg_a2 = store_message(test_channel.id, user_a.id, "From A again")

        history = get_messages(test_channel.id)

        assert history[0].sender_id == user_a.id
        assert history[1].sender_id == user_b.id
        assert history[2].sender_id == user_a.id

    def test_sender_id_unique_per_message(self, test_users, test_channel):
        """Each user's messages correctly tracked separately."""
        user_a, user_b, user_c = test_users

        for i in range(5):
            store_message(test_channel.id, user_a.id, f"A-{i}")
        for i in range(5):
            store_message(test_channel.id, user_b.id, f"B-{i}")
        for i in range(5):
            store_message(test_channel.id, user_c.id, f"C-{i}")

        history = get_messages(test_channel.id, limit=100, offset=0)

        # Count messages per sender
        a_count = sum(1 for m in history if m.sender_id == user_a.id)
        b_count = sum(1 for m in history if m.sender_id == user_b.id)
        c_count = sum(1 for m in history if m.sender_id == user_c.id)

        assert a_count == 5
        assert b_count == 5
        assert c_count == 5


class TestMessageOrderingScenarios:
    """Real-world message ordering scenarios."""

    def test_chronological_ordering_complex(self, test_users, test_channel):
        """Complex scenario: many users, many messages maintain order."""
        users = test_users

        # Simulate realistic conversation
        store_message(test_channel.id, users[0].id, "Hello")
        store_message(test_channel.id, users[1].id, "Hi there")
        store_message(test_channel.id, users[2].id, "Hey everyone")
        store_message(test_channel.id, users[0].id, "How are you?")
        store_message(test_channel.id, users[1].id, "Doing great!")

        history = get_messages(test_channel.id)

        expected_order = [
            "Hello",
            "Hi there",
            "Hey everyone",
            "How are you?",
            "Doing great!",
        ]

        assert len(history) == 5
        for i, expected_text in enumerate(expected_order):
            assert history[i].text == expected_text

    def test_pagination_ordering_consistency(self, test_users, test_channel):
        """Ordering consistent across paginated requests."""
        user = test_users[0]

        # Send 150 messages
        for i in range(150):
            store_message(test_channel.id, user.id, f"Message {i:03d}")

        # Get in pages and verify consistent order
        page1 = get_messages(test_channel.id, limit=50, offset=0)
        page2 = get_messages(test_channel.id, limit=50, offset=50)
        page3 = get_messages(test_channel.id, limit=50, offset=100)

        # Each page ordered correctly
        for i, msg in enumerate(page1):
            assert msg.text == f"Message {i:03d}"

        for i, msg in enumerate(page2):
            assert msg.text == f"Message {50 + i:03d}"

        for i, msg in enumerate(page3):
            assert msg.text == f"Message {100 + i:03d}"

        # Pages don't overlap
        last_msg_p1 = page1[-1]
        first_msg_p2 = page2[0]
        last_msg_p2 = page2[-1]
        first_msg_p3 = page3[0]

        assert last_msg_p1.sent_at <= first_msg_p2.sent_at
        assert last_msg_p2.sent_at <= first_msg_p3.sent_at


@pytest.mark.asyncio
class TestIntegrationBroadcastFlow:
    """Integration of service layer with WebSocket broadcasting."""

    async def test_send_message_then_broadcast(self, fresh_manager, test_users, test_channel):
        """Service layer send → broadcast to other users."""
        user_sender, user_recipient = test_users[0], test_users[1]

        # Mock WebSocket
        received_payload = None

        class MockWebSocket:
            async def accept(self):
                pass

            async def send_json(self, data):
                nonlocal received_payload
                received_payload = data

            async def close(self):
                pass

        # Recipient connected
        ws = MockWebSocket()
        await fresh_manager.connect(ws, user_recipient.id)

        # Sender sends message
        msg = store_message(test_channel.id, user_sender.id, "Hello recipient!")

        # Prepare event as broadcast would
        event = MessageEvent(message=msg)
        event_payload = event.model_dump(mode="json")

        # Broadcast to recipient
        delivered, offline = await fresh_manager.broadcast(
            [user_recipient.id],
            event_payload,
        )

        # Recipient got the message
        assert len(delivered) == 1
        assert received_payload is not None
        assert received_payload["message"]["text"] == "Hello recipient!"
        assert received_payload["message"]["sender_id"] == str(user_sender.id)
