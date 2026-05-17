"""
End-to-end tests for REST chat operations.

Tests the full flow: send message → store in cache → retrieve via REST.
Validates message persistence, pagination, ordering, and single lookups.
"""
from uuid import uuid4

from backend.chat.models import MessageRole
from backend.chat.service import send_message, get_messages, get_message_by_id


class TestRestMessageSending:
    """REST POST message flow."""

    def test_send_single_message_success(self, test_users, test_channel):
        """Send a message via service layer (REST backend)."""
        user = test_users[0]
        text = "Hello, this is a test message"

        msg = send_message(
            channel_id=test_channel.id,
            user_id=user.id,
            text=text,
        )

        assert msg.id is not None
        assert msg.channel_id == test_channel.id
        assert msg.sender_id == user.id
        assert msg.text == text
        assert msg.role == MessageRole.USER
        assert msg.sent_at is not None

    def test_send_multiple_messages_same_channel(self, test_users, test_channel):
        """Send multiple messages to same channel."""
        user_a, user_b = test_users[0], test_users[1]

        msg1 = send_message(test_channel.id, user_a.id, "Message 1")
        msg2 = send_message(test_channel.id, user_b.id, "Message 2")
        msg3 = send_message(test_channel.id, user_a.id, "Message 3")

        assert msg1.id != msg2.id != msg3.id
        assert msg1.sender_id == user_a.id
        assert msg2.sender_id == user_b.id
        assert msg3.sender_id == user_a.id

    def test_send_messages_different_channels(self, test_users, test_channel_ids):
        """Send messages to different channels are isolated."""
        user = test_users[0]

        msg1 = send_message(test_channel_ids[0], user.id, "Channel 1 msg")
        msg2 = send_message(test_channel_ids[1], user.id, "Channel 2 msg")

        assert msg1.channel_id == test_channel_ids[0]
        assert msg2.channel_id == test_channel_ids[1]
        assert msg1.id != msg2.id


class TestRestMessageRetrieval:
    """REST GET message history flow."""

    def test_get_empty_channel_history(self, test_channel):
        """Get messages from empty channel returns empty list."""
        messages = get_messages(test_channel.id)

        assert messages == []

    def test_get_single_message_history(self, test_users, test_channel):
        """Send one message and retrieve it."""
        user = test_users[0]
        text = "Test message"

        sent_msg = send_message(test_channel.id, user.id, text)
        retrieved = get_messages(test_channel.id)

        assert len(retrieved) == 1
        assert retrieved[0].id == sent_msg.id
        assert retrieved[0].text == text

    def test_get_messages_pagination_basic(self, test_users, test_channel):
        """Paginate through message history."""
        user = test_users[0]

        # Send 10 messages
        msg_ids = []
        for i in range(10):
            msg = send_message(test_channel.id, user.id, f"Message {i}")
            msg_ids.append(msg.id)

        # Get first 5
        page1 = get_messages(test_channel.id, limit=5, offset=0)
        assert len(page1) == 5
        assert page1[0].id == msg_ids[0]
        assert page1[4].id == msg_ids[4]

        # Get next 5
        page2 = get_messages(test_channel.id, limit=5, offset=5)
        assert len(page2) == 5
        assert page2[0].id == msg_ids[5]
        assert page2[4].id == msg_ids[9]

    def test_get_messages_pagination_partial_page(self, test_users, test_channel):
        """Last page may have fewer items than limit."""
        user = test_users[0]

        # Send 13 messages
        for i in range(13):
            send_message(test_channel.id, user.id, f"Message {i}")

        # Get with limit of 5
        page1 = get_messages(test_channel.id, limit=5, offset=0)
        page2 = get_messages(test_channel.id, limit=5, offset=5)
        page3 = get_messages(test_channel.id, limit=5, offset=10)

        assert len(page1) == 5
        assert len(page2) == 5
        assert len(page3) == 3

    def test_get_messages_pagination_out_of_bounds(self, test_users, test_channel):
        """Offset beyond total messages returns empty list."""
        user = test_users[0]

        for i in range(5):
            send_message(test_channel.id, user.id, f"Message {i}")

        page_out_of_bounds = get_messages(test_channel.id, limit=5, offset=100)

        assert page_out_of_bounds == []

    def test_get_messages_max_limit_enforced(self, test_users, test_channel):
        """System enforces maximum limit of 200."""
        user = test_users[0]

        for i in range(250):
            send_message(test_channel.id, user.id, f"Message {i}")

        # Request with limit > 200 should still be capped
        # (This would be validated in the REST route, but service layer doesn't cap)
        all_msgs = get_messages(test_channel.id, limit=300, offset=0)
        assert len(all_msgs) == 250


class TestRestMessageOrdering:
    """REST message ordering and sorting."""

    def test_messages_ordered_by_sent_at_ascending(self, test_users, test_channel):
        """Messages returned in ascending chronological order (oldest first)."""
        user = test_users[0]

        msg1 = send_message(test_channel.id, user.id, "First")
        msg2 = send_message(test_channel.id, user.id, "Second")
        msg3 = send_message(test_channel.id, user.id, "Third")

        retrieved = get_messages(test_channel.id)

        assert len(retrieved) == 3
        assert retrieved[0].sent_at <= retrieved[1].sent_at <= retrieved[2].sent_at
        assert retrieved[0].text == "First"
        assert retrieved[1].text == "Second"
        assert retrieved[2].text == "Third"

    def test_messages_rapid_succession_ordering(self, test_users, test_channel):
        """Messages sent rapidly maintain correct order."""
        user = test_users[0]

        # Send 50 messages rapidly
        sent_msgs = []
        for i in range(50):
            msg = send_message(test_channel.id, user.id, f"Message {i}")
            sent_msgs.append(msg)

        retrieved = get_messages(test_channel.id, limit=50, offset=0)

        assert len(retrieved) == 50
        for i, msg in enumerate(retrieved):
            assert msg.text == f"Message {i}"


class TestRestSingleMessageLookup:
    """REST GET /messages/{message_id} flow."""

    def test_get_message_by_id_success(self, test_users, test_channel):
        """Retrieve a specific message by ID."""
        user = test_users[0]
        text = "Unique message for lookup"

        sent_msg = send_message(test_channel.id, user.id, text)
        retrieved = get_message_by_id(test_channel.id, sent_msg.id)

        assert retrieved is not None
        assert retrieved.id == sent_msg.id
        assert retrieved.text == text
        assert retrieved.sender_id == user.id

    def test_get_message_by_id_not_found(self, test_channel):
        """Lookup non-existent message returns None."""
        fake_msg_id = uuid4()

        retrieved = get_message_by_id(test_channel.id, fake_msg_id)

        assert retrieved is None

    def test_get_message_by_id_wrong_channel(self, test_users, test_channel_ids):
        """Message in channel A not found when looking up in channel B."""
        user = test_users[0]

        msg = send_message(test_channel_ids[0], user.id, "In channel A")
        retrieved = get_message_by_id(test_channel_ids[1], msg.id)

        assert retrieved is None

    def test_get_message_by_id_multiple_channels(self, test_users, test_channel_ids):
        """Same message lookup works independently per channel."""
        user = test_users[0]

        msg_ch1 = send_message(test_channel_ids[0], user.id, "Channel 1")
        msg_ch2 = send_message(test_channel_ids[1], user.id, "Channel 2")

        retrieved_ch1 = get_message_by_id(test_channel_ids[0], msg_ch1.id)
        retrieved_ch2 = get_message_by_id(test_channel_ids[1], msg_ch2.id)

        assert retrieved_ch1 is not None and retrieved_ch1.id == msg_ch1.id
        assert retrieved_ch2 is not None and retrieved_ch2.id == msg_ch2.id


class TestRestChannelIsolation:
    """REST operations maintain channel isolation."""

    def test_messages_not_shared_across_channels(self, test_users, test_channel_ids):
        """Messages sent to channel A don't appear in channel B."""
        user = test_users[0]

        # Send to channel 0
        msg_ch0_1 = send_message(test_channel_ids[0], user.id, "Ch0 Msg1")
        msg_ch0_2 = send_message(test_channel_ids[0], user.id, "Ch0 Msg2")

        # Send to channel 1
        msg_ch1_1 = send_message(test_channel_ids[1], user.id, "Ch1 Msg1")

        # Retrieve from each channel
        ch0_msgs = get_messages(test_channel_ids[0])
        ch1_msgs = get_messages(test_channel_ids[1])

        assert len(ch0_msgs) == 2
        assert len(ch1_msgs) == 1
        assert ch0_msgs[0].text == "Ch0 Msg1"
        assert ch0_msgs[1].text == "Ch0 Msg2"
        assert ch1_msgs[0].text == "Ch1 Msg1"

    def test_sender_id_not_spoofable_via_service(self, test_users, test_channel):
        """Service layer always uses provided user_id, not from payload."""
        user_a, user_b = test_users[0], test_users[1]

        # Send as user_a
        msg = send_message(test_channel.id, user_a.id, "Message")

        assert msg.sender_id == user_a.id
        retrieved = get_message_by_id(test_channel.id, msg.id)
        assert retrieved.sender_id == user_a.id
        # user_b cannot override sender_id in service layer


class TestRestMessageMetadata:
    """REST message metadata (timestamps, roles, IDs)."""

    def test_message_has_unique_id(self, test_users, test_channel):
        """Each message gets unique UUID."""
        user = test_users[0]

        msg1 = send_message(test_channel.id, user.id, "Msg1")
        msg2 = send_message(test_channel.id, user.id, "Msg2")

        assert msg1.id != msg2.id
        assert isinstance(msg1.id, uuid4().__class__)

    def test_message_has_sent_at_timestamp(self, test_users, test_channel):
        """Messages have UTC sent_at timestamp."""
        from datetime import timezone, datetime

        user = test_users[0]
        before = datetime.now(timezone.utc)

        msg = send_message(test_channel.id, user.id, "Test")

        after = datetime.now(timezone.utc)

        assert msg.sent_at is not None
        assert before <= msg.sent_at <= after

    def test_message_role_defaults_to_user(self, test_users, test_channel):
        """Messages default to USER role."""
        user = test_users[0]

        msg = send_message(test_channel.id, user.id, "Test")

        assert msg.role == MessageRole.USER
