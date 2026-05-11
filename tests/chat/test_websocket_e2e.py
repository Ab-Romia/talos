"""
End-to-end WebSocket tests with real connections.

Tests the full WebSocket flow using TestClient.websocket_connect() to create
actual in-process WebSocket connections, message persistence, and broadcast delivery.

These tests use real authentication tokens and actual WebSocket infrastructure,
avoiding mocks of the connection manager and instead testing the full E2E flow.
"""
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app import app
from backend.auth.utils.jwt import create_token
from backend.auth.utils.session import SessionClaims
from model.identity import Session as UserSession

# Import router module for patching
router_module = sys.modules.get('backend.chat.router')
if not router_module:
    import backend.chat.router as router_module


@pytest.fixture
def auth_websocket_setup(client, db_session, test_users, monkeypatch):
    """Setup authenticated WebSocket environment for all test users."""
    from backend.auth.utils.helpers import active_user
    from backend.auth.utils.session import unverified_session, verified_session
    from backend.auth.utils.jwt import verify_token

    # Create DB sessions and tokens for all test users
    tokens = {}
    for user in test_users:
        session = UserSession(user_id=user.id)
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        claims = SessionClaims(
            sub=user.id,
            jti=session.id,
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        )
        tokens[user.id] = create_token(claims)

    # Mock active_user - takes session_dep and db_dep
    def mock_active_user(session_claims, db):
        if hasattr(session_claims, 'sub'):
            for user in test_users:
                if user.id == session_claims.sub:
                    return user
        return test_users[0]

    # Mock verified_session - takes claims and db
    def mock_verified_session(claims, db):
        return claims

    # Mock unverified_session - generator that yields
    def mock_unverified_session(request, token):
        if token:
            claims = verify_token(token, return_model=SessionClaims)
        else:
            from datetime import timezone, datetime, timedelta
            claims = SessionClaims(exp=datetime.now(timezone.utc) + timedelta(days=30))
        yield claims

    # Override dependencies
    app.dependency_overrides[active_user] = mock_active_user
    app.dependency_overrides[verified_session] = mock_verified_session
    app.dependency_overrides[unverified_session] = mock_unverified_session

    # Patch get_channel_members
    monkeypatch.setattr(
        router_module,
        "get_channel_members",
        lambda cid: [u.id for u in test_users],
    )

    yield {
        "client": client,
        "tokens": tokens,
        "users": test_users,
    }

    # Cleanup
    app.dependency_overrides.clear()


class TestWebSocketE2E:
    """End-to-end WebSocket tests with real connections."""

    def test_send_and_receive_message(self, auth_websocket_setup, test_channel_id):
        """Send message from one user and receive on another."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        recipient = users[1]

        # Connect sender and recipient
        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[recipient.id]}"}
            ) as recipient_ws:
                # Send message
                payload = {
                    "channel_id": str(test_channel_id),
                    "text": "Hello from sender!",
                }
                sender_ws.send_json(payload)

                # Recipient should receive the message
                received = recipient_ws.receive_json()
                assert received["event_type"] == "new_message"
                assert received["message"]["text"] == "Hello from sender!"
                assert received["message"]["sender_id"] == str(sender.id)

    def test_broadcast_to_multiple_users(self, auth_websocket_setup, test_channel_id):
        """Message is broadcast to all connected users."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        recipient1 = users[1]
        recipient2 = users[2]

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[recipient1.id]}"}
            ) as recipient1_ws:
                with client.websocket_connect(
                        "/api/chat/ws",
                        headers={"Authorization": f"Bearer {tokens[recipient2.id]}"}
                ) as recipient2_ws:
                    # Send message
                    payload = {
                        "channel_id": str(test_channel_id),
                        "text": "Broadcast message!",
                    }
                    sender_ws.send_json(payload)

                    # Both recipients should receive
                    msg1 = recipient1_ws.receive_json()
                    assert msg1["message"]["text"] == "Broadcast message!"

                    msg2 = recipient2_ws.receive_json()
                    assert msg2["message"]["text"] == "Broadcast message!"

                    # Sender should receive ACK
                    ack = sender_ws.receive_json()
                    assert ack["delivered"] is True
                    delivered_to_ids = [UUID(uid) if isinstance(uid, str) else uid for uid in ack["delivered_to"]]
                    assert recipient1.id in delivered_to_ids
                    assert recipient2.id in delivered_to_ids

    def test_partial_delivery_tracks_offline_users(self, auth_websocket_setup, test_channel_id):
        """Offline users are tracked when sender broadcasts."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        recipient = users[1]
        offline_user = users[2]  # Won't connect

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[recipient.id]}"}
            ) as recipient_ws:
                # Send message
                payload = {
                    "channel_id": str(test_channel_id),
                    "text": "Test partial delivery",
                }
                sender_ws.send_json(payload)

                # Recipient receives
                recipient_ws.receive_json()

                # Sender gets ACK with offline users
                ack = sender_ws.receive_json()
                assert ack["delivered"] is True
                # offline_user should be in offline_users list
                offline_ids = [UUID(uid) if isinstance(uid, str) else uid for uid in ack["offline_users"]]
                assert offline_user.id in offline_ids

    def test_message_content_preserved(self, auth_websocket_setup, test_channel_id):
        """Message content with special characters is preserved."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        recipient = users[1]

        special_text = "Hello 👋 Café 中文 $pecial!"

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[recipient.id]}"}
            ) as recipient_ws:
                # Send message with special characters
                payload = {
                    "channel_id": str(test_channel_id),
                    "text": special_text,
                }
                sender_ws.send_json(payload)

                # Verify exact content
                received = recipient_ws.receive_json()
                assert received["message"]["text"] == special_text

    def test_invalid_payload_returns_error(self, auth_websocket_setup, test_channel_id):
        """Invalid payloads are rejected with error."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        user = users[0]

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[user.id]}"}
        ) as ws:
            # Send invalid payload (missing 'text' field)
            invalid = {"channel_id": str(test_channel_id)}
            ws.send_json(invalid)

            # Should receive error
            response = ws.receive_json()
            assert response.get("event") == "error" or "detail" in response


class TestWebSocketSender:
    """Sender-side WebSocket behavior."""

    def test_sender_receives_ack_on_send(self, auth_websocket_setup, test_channel_id):
        """Sender receives ACK message after sending."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        recipient = users[1]

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[recipient.id]}"}
            ) as recipient_ws:
                # Send message
                payload = {
                    "channel_id": str(test_channel_id),
                    "text": "Test ACK",
                }
                sender_ws.send_json(payload)

                # Recipient receives
                recipient_ws.receive_json()

                # Sender receives ACK with delivery info
                ack = sender_ws.receive_json()
                assert ack["event_type"] == "new_message"
                assert ack["delivered"] is True
                assert "delivered_to" in ack
                assert "offline_users" in ack

    def test_sender_sees_offline_users_in_broadcast(self, auth_websocket_setup, test_channel_id):
        """Sender sees which users are offline when broadcasting."""
        client = auth_websocket_setup["client"]
        tokens = auth_websocket_setup["tokens"]
        users = auth_websocket_setup["users"]

        sender = users[0]
        online_user = users[1]
        # users[2] stays offline

        with client.websocket_connect(
                "/api/chat/ws",
                headers={"Authorization": f"Bearer {tokens[sender.id]}"}
        ) as sender_ws:
            with client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[online_user.id]}"}
            ) as online_ws:
                # Send to all users
                payload = {
                    "channel_id": str(test_channel_id),
                    "text": "Broadcast with offline",
                }
                sender_ws.send_json(payload)

                # Online user receives
                online_ws.receive_json()

                # Sender receives delivery status
                ack = sender_ws.receive_json()
                delivered_ids = [UUID(uid) if isinstance(uid, str) else uid for uid in ack["delivered_to"]]
                offline_ids = [UUID(uid) if isinstance(uid, str) else uid for uid in ack["offline_users"]]

                assert online_user.id in delivered_ids
                assert users[2].id in offline_ids
