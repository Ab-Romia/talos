from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from backend.auth.utils.jwt import create_token
from backend.auth.utils.session import SessionClaims
from model.identity import Session as UserSession


@pytest.fixture
def auth_tokens(db_session, test_users):
    """Create valid auth tokens for all test users using real DB sessions."""
    tokens = {}
    for user in test_users:
        # Create a real session in DB for each user
        session = UserSession(user_id=user.id)
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        # Create token with real SessionClaims
        claims = SessionClaims(
            sub=user.id,
            jti=session.id,
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        )
        tokens[user.id] = create_token(claims)

    return tokens


@contextmanager
def connect_users(client, tokens, user_list):
    exit_stack = ExitStack()
    try:
        websockets = {}
        for user in user_list:
            ws = exit_stack.enter_context(
                client.websocket_connect(
                    "/api/chat/ws",
                    headers={"Authorization": f"Bearer {tokens[user.id]}"}
                )
            )
            websockets[user.id] = ws

        # Yield dict keyed by user ID for clean access
        yield {user.id: websockets[user.id] for user in user_list}
    finally:
        exit_stack.close()


class TestWebSocketE2E:
    def test_send_and_receive_message_sync(self, client, auth_tokens, test_users, test_channel):
        """Baseline sync test using existing TestClient connections."""
        sender, recipient = test_users[0], test_users[1]

        with connect_users(client, auth_tokens, [sender, recipient]) as ws:
            ws[sender.id].send_json({"channel_id": str(test_channel.id),
                                     "text": "Hello from sender!"})
            received = ws[recipient.id].receive_json()

            assert received["event_type"] == "new_message"
            assert received["message"]["text"] == "Hello from sender!"
            assert received["message"]["sender_id"] == str(sender.id)

    def test_broadcast_to_multiple_users(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        sender, recipient1, recipient2 = users[0], users[1], users[2]

        with connect_users(client, tokens, [sender, recipient1, recipient2]) as ws:
            payload = {
                "channel_id": str(test_channel_id),
                "text": "Broadcast message!",
            }
            ws[sender.id].send_json(payload)

            # Both recipients receive
            msg1 = ws[recipient1.id].receive_json()
            assert msg1["message"]["text"] == "Broadcast message!"

            msg2 = ws[recipient2.id].receive_json()
            assert msg2["message"]["text"] == "Broadcast message!"

            # Sender receives ACK
            ack = ws[sender.id].receive_json()
            assert ack["delivered"] is True
            delivered_to_ids = [UUID(uid) for uid in ack["delivered_to"]]
            assert recipient1.id in delivered_to_ids
            assert recipient2.id in delivered_to_ids

    def test_partial_delivery_tracks_offline_users(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        sender, recipient, offline_user = users[0], users[1], users[2]

        with connect_users(client, tokens, [sender, recipient]) as ws:
            payload = {
                "channel_id": str(test_channel_id),
                "text": "Test partial delivery",
            }
            ws[sender.id].send_json(payload)
            ws[recipient.id].receive_json()

            ack = ws[sender.id].receive_json()
            assert ack["delivered"] is True
            offline_ids = [UUID(uid) for uid in ack["offline_users"]]
            assert offline_user.id in offline_ids

    def test_message_content_preserved(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        sender, recipient = users[0], users[1]
        special_text = "Hello 👋 Café 中文 $pecial!"

        with connect_users(client, tokens, [sender, recipient]) as ws:
            payload = {
                "channel_id": str(test_channel_id),
                "text": special_text,
            }
            ws[sender.id].send_json(payload)
            received = ws[recipient.id].receive_json()
            assert received["message"]["text"] == special_text

    def test_invalid_payload_returns_error(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        user = users[0]

        with connect_users(client, tokens, [user]) as ws:
            invalid = {"channel_id": str(test_channel_id)}
            ws[user.id].send_json(invalid)
            response = ws[user.id].receive_json()
            assert response.get("event") == "error" or "detail" in response


class TestWebSocketSender:
    def test_sender_receives_ack_on_send(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        sender, recipient = users[0], users[1]

        with connect_users(client, tokens, [sender, recipient]) as ws:
            payload = {"channel_id": str(test_channel_id), "text": "Test ACK"}
            ws[sender.id].send_json(payload)
            ws[recipient.id].receive_json()

            ack = ws[sender.id].receive_json()
            assert ack["event_type"] == "new_message"
            assert ack["delivered"] is True
            assert "delivered_to" in ack
            assert "offline_users" in ack

    def test_sender_sees_offline_users_in_broadcast(self, client, auth_tokens, test_users, test_channel_id):
        tokens = auth_tokens
        users = test_users
        sender, online_user = users[0], users[1]
        offline_user = users[2]

        with connect_users(client, tokens, [sender, online_user]) as ws:
            payload = {"channel_id": str(test_channel_id), "text": "Broadcast with offline"}
            ws[sender.id].send_json(payload)
            ws[online_user.id].receive_json()

            ack = ws[sender.id].receive_json()
            delivered_ids = [UUID(uid) for uid in ack["delivered_to"]]
            offline_ids = [UUID(uid) for uid in ack["offline_users"]]

            assert online_user.id in delivered_ids
            assert offline_user.id in offline_ids
