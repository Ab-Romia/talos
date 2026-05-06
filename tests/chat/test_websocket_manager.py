"""
End-to-end tests for WebSocket connection manager and broadcasting.

Tests connection lifecycle, delivery tracking, presence updates,
and multi-user broadcasting flows.
"""
from uuid import uuid4
import pytest

from backend.chat.manager import ChannelConnectionManager


@pytest.mark.asyncio
class TestConnectionManager:
    """WebSocket connection manager lifecycle."""
    
    async def test_connect_and_disconnect(self, fresh_manager, test_users):
        """Connect a user and disconnect."""
        user = test_users[0]
        
        # Mock WebSocket for testing
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                pass
            
            async def close(self):
                pass
        
        ws = MockWebSocket()
        
        # Connect
        await fresh_manager.connect(ws, user.id)
        
        # Verify online
        online = fresh_manager.get_online_users([user.id])
        assert user.id in online
        
        # Disconnect
        fresh_manager.disconnect(user.id)
        
        # Verify offline
        online = fresh_manager.get_online_users([user.id])
        assert user.id not in online
    
    async def test_reconnection_closes_old_socket(self, fresh_manager, test_users):
        """Connecting same user twice closes first connection."""
        user = test_users[0]
        
        class MockWebSocket:
            def __init__(self):
                self.closed = False
                self.accepted = False
            
            async def accept(self):
                self.accepted = True
            
            async def send_json(self, data):
                pass
            
            async def close(self):
                self.closed = True
        
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        # First connection
        await fresh_manager.connect(ws1, user.id)
        assert ws1.accepted
        
        # Second connection replaces first
        await fresh_manager.connect(ws2, user.id)
        
        # First should be closed
        assert ws1.closed
        # Second is active
        assert ws2.accepted
        online = fresh_manager.get_online_users([user.id])
        assert user.id in online
    
    async def test_multiple_users_connected(self, fresh_manager, test_users):
        """Multiple users can have simultaneous connections."""
        
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                pass
            
            async def close(self):
                pass
        
        # Connect all three users
        for user in test_users:
            ws = MockWebSocket()
            await fresh_manager.connect(ws, user.id)
        
        # All should be online
        online = fresh_manager.get_online_users([u.id for u in test_users])
        
        assert len(online) == 3
        for user in test_users:
            assert user.id in online


@pytest.mark.asyncio
class TestPresenceTracking:
    """Online presence detection."""
    
    async def test_get_online_users_empty(self, fresh_manager, test_users):
        """No users connected returns empty list."""
        online = fresh_manager.get_online_users([u.id for u in test_users])
        
        assert online == []
    
    async def test_get_online_users_partial(self, fresh_manager, test_users):
        """Get online users filters to only connected ones."""
        class MockWebSocket:
            async def accept(self):
                pass
            async def send_json(self, data):
                pass
            async def close(self):
                pass
        
        # Connect only first two users
        for user in test_users[:2]:
            ws = MockWebSocket()
            await fresh_manager.connect(ws, user.id)
        
        # Query all three
        online = fresh_manager.get_online_users([u.id for u in test_users])
        
        assert len(online) == 2
        assert test_users[0].id in online
        assert test_users[1].id in online
        assert test_users[2].id not in online
    
    async def test_get_online_users_after_disconnect(self, fresh_manager, test_users):
        """Online list updates after disconnects."""
        class MockWebSocket:
            async def accept(self):
                pass
            async def send_json(self, data):
                pass
            async def close(self):
                pass
        
        user_a, user_b = test_users[0], test_users[1]
        
        ws_a = MockWebSocket()
        ws_b = MockWebSocket()
        
        await fresh_manager.connect(ws_a, user_a.id)
        await fresh_manager.connect(ws_b, user_b.id)
        
        online_before = fresh_manager.get_online_users([user_a.id, user_b.id])
        assert len(online_before) == 2
        
        # Disconnect one
        fresh_manager.disconnect(user_a.id)
        
        online_after = fresh_manager.get_online_users([user_a.id, user_b.id])
        assert len(online_after) == 1
        assert user_b.id in online_after


@pytest.mark.asyncio
class TestBroadcasting:
    """Broadcasting to multiple users."""
    
    async def test_send_to_user_success(self, fresh_manager, test_users):
        """Send message to single connected user."""
        user = test_users[0]
        
        received_data = None
        
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                nonlocal received_data
                received_data = data
            
            async def close(self):
                pass
        
        ws = MockWebSocket()
        await fresh_manager.connect(ws, user.id)
        
        payload = {"event": "test", "data": "hello"}
        success = await fresh_manager.send_to_user(user.id, payload)
        
        assert success is True
        assert received_data == payload
    
    async def test_send_to_user_offline(self, fresh_manager, test_users):
        """Send to offline user returns False."""
        user = test_users[0]
        
        payload = {"event": "test"}
        success = await fresh_manager.send_to_user(user.id, payload)
        
        assert success is False
    
    async def test_send_to_user_connection_failure(self, fresh_manager, test_users):
        """Send fails and removes connection on socket error."""
        user = test_users[0]
        
        class FailingWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                raise Exception("Socket error")
            
            async def close(self):
                pass
        
        ws = FailingWebSocket()
        await fresh_manager.connect(ws, user.id)
        
        # Try to send
        payload = {"event": "test"}
        success = await fresh_manager.send_to_user(user.id, payload)
        
        assert success is False
        
        # User should be disconnected after failure
        online = fresh_manager.get_online_users([user.id])
        assert user.id not in online
    
    async def test_broadcast_to_multiple_users(self, fresh_manager, test_users):
        """Broadcast message to multiple recipients."""
        user_a, user_b, user_c = test_users
        
        received = {}
        
        class MockWebSocket:
            def __init__(self, user_id):
                self.user_id = user_id
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                received[self.user_id] = data
            
            async def close(self):
                pass
        
        # Connect all three
        ws_a = MockWebSocket(user_a.id)
        ws_b = MockWebSocket(user_b.id)
        ws_c = MockWebSocket(user_c.id)
        
        await fresh_manager.connect(ws_a, user_a.id)
        await fresh_manager.connect(ws_b, user_b.id)
        await fresh_manager.connect(ws_c, user_c.id)
        
        # Broadcast to all three
        payload = {"event": "message", "text": "Hello all"}
        delivered, offline = await fresh_manager.broadcast(
            [user_a.id, user_b.id, user_c.id],
            payload,
        )
        
        assert len(delivered) == 3
        assert len(offline) == 0
        assert received[user_a.id] == payload
        assert received[user_b.id] == payload
        assert received[user_c.id] == payload
    
    async def test_broadcast_partial_delivery(self, fresh_manager, test_users):
        """Broadcast tracks delivered and offline users."""
        user_a, user_b, user_c = test_users
        
        received = {}
        
        class MockWebSocket:
            def __init__(self, user_id):
                self.user_id = user_id
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                received[self.user_id] = data
            
            async def close(self):
                pass
        
        # Connect only user_a and user_b
        ws_a = MockWebSocket(user_a.id)
        ws_b = MockWebSocket(user_b.id)
        
        await fresh_manager.connect(ws_a, user_a.id)
        await fresh_manager.connect(ws_b, user_b.id)
        # user_c not connected
        
        # Broadcast to all three
        payload = {"event": "message"}
        delivered, offline = await fresh_manager.broadcast(
            [user_a.id, user_b.id, user_c.id],
            payload,
        )
        
        assert len(delivered) == 2
        assert len(offline) == 1
        assert user_a.id in delivered
        assert user_b.id in delivered
        assert user_c.id in offline
    
    async def test_broadcast_with_exclude_user(self, fresh_manager, test_users):
        """Broadcast can exclude sender."""
        user_a, user_b, user_c = test_users
        
        received = {}
        
        class MockWebSocket:
            def __init__(self, user_id):
                self.user_id = user_id
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                received[self.user_id] = data
            
            async def close(self):
                pass
        
        ws_a = MockWebSocket(user_a.id)
        ws_b = MockWebSocket(user_b.id)
        ws_c = MockWebSocket(user_c.id)
        
        await fresh_manager.connect(ws_a, user_a.id)
        await fresh_manager.connect(ws_b, user_b.id)
        await fresh_manager.connect(ws_c, user_c.id)
        
        # Broadcast excluding user_a
        payload = {"event": "message"}
        delivered, offline = await fresh_manager.broadcast(
            [user_a.id, user_b.id, user_c.id],
            payload,
            exclude_user=user_a.id,
        )
        
        assert len(delivered) == 2
        assert user_a.id not in delivered
        assert user_b.id in delivered
        assert user_c.id in delivered
        assert user_a.id not in received  # user_a didn't receive
        assert user_b.id in received
        assert user_c.id in received
    
    async def test_broadcast_partial_failure(self, fresh_manager, test_users):
        """Broadcast handles some failing sockets gracefully."""
        user_a, user_b, user_c = test_users
        
        received = {}
        
        class MockWebSocket:
            def __init__(self, user_id, fail=False):
                self.user_id = user_id
                self.fail = fail
            
            async def accept(self):
                pass
            
            async def send_json(self, data):
                if self.fail:
                    raise Exception("Socket error")
                received[self.user_id] = data
            
            async def close(self):
                pass
        
        ws_a = MockWebSocket(user_a.id, fail=False)
        ws_b = MockWebSocket(user_b.id, fail=True)  # This one fails
        ws_c = MockWebSocket(user_c.id, fail=False)
        
        await fresh_manager.connect(ws_a, user_a.id)
        await fresh_manager.connect(ws_b, user_b.id)
        await fresh_manager.connect(ws_c, user_c.id)
        
        # Broadcast
        payload = {"event": "message"}
        delivered, offline = await fresh_manager.broadcast(
            [user_a.id, user_b.id, user_c.id],
            payload,
        )
        
        assert len(delivered) == 2
        assert len(offline) == 1
        assert user_a.id in delivered
        assert user_c.id in delivered
        assert user_b.id in offline
        # user_b should be disconnected after failure
        online = fresh_manager.get_online_users([user_b.id])
        assert user_b.id not in online


@pytest.mark.asyncio
class TestBroadcastPayloadFormats:
    """Broadcasting with different payload formats."""
    
    async def test_broadcast_with_message_event(self, fresh_manager, test_users):
        """Broadcast with MessageEvent structure."""
        user_a, user_b = test_users[0], test_users[1]
        
        received_data = None
        
        class MockWebSocket:
            async def accept(self):
                pass
            
            async def send_json(self, data):
                nonlocal received_data
                received_data = data
            
            async def close(self):
                pass
        
        ws = MockWebSocket()
        await fresh_manager.connect(ws, user_b.id)
        
        # Message event with complex structure
        payload = {
            "event_type": "new_message",
            "message": {
                "id": str(uuid4()),
                "channel_id": str(uuid4()),
                "sender_id": str(user_a.id),
                "text": "Test message",
                "sent_at": "2026-05-06T12:00:00Z",
            },
            "delivered": True,
            "offline_users": [],
        }
        
        delivered, offline = await fresh_manager.broadcast([user_b.id], payload)
        
        assert len(delivered) == 1
        assert received_data == payload
