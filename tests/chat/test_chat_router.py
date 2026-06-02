import uuid

from chat.router import post_message, get_channel_messages, get_single_message, get_online_users


class TestPostMessage:
    def test_post_message_success(self, client, test_channel, test_user, auth_token, path):
        """Successfully send a message to a channel."""
        payload = {"text": "Hello, world!"}

        response = client.post(
            path(post_message, channel_id=test_channel.id),
            json=payload,
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "sent_at" in data

    def test_post_message_invalid_payload(self, client, test_channel, auth_token, path):
        """Fails with 422 Unprocessable Entity if the body doesn't match SendRequest."""
        response = client.post(
            path(post_message, channel_id=test_channel.id),
            json={"wrong_field": "Hello"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 422


class TestGetChannelMessages:
    def test_get_channel_messages_empty(self, client, test_channel, auth_token, path):
        """Returns an empty list for a channel with no messages."""
        response = client.get(
            path(get_channel_messages, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_get_channel_messages_with_pagination(self, client, test_channel, auth_token, path):
        """Successfully paginates messages in reverse chronological order."""
        # Seed 5 messages
        for i in range(5):
            client.post(
                path(post_message, channel_id=test_channel.id),
                json={"text": f"Message {i}"},
                headers={"Authorization": f"Bearer {auth_token}"},
            )

        # Request with limit and offset via query params
        response = client.get(
            path(get_channel_messages, channel_id=test_channel.id),
            params={"limit": 2, "offset": 0},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data) == 2
        # Verify reverse chronological order (newest first)
        assert data[0]["content"] == "Message 4"
        assert data[1]["content"] == "Message 3"

    def test_get_channel_messages_out_of_bounds(self, client, test_channel, auth_token, path):
        """Offset beyond total messages returns an empty list."""
        client.post(
            path(post_message, channel_id=test_channel.id),
            json={"text": "Only message"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        response = client.get(
            path(get_channel_messages, channel_id=test_channel.id),
            params={"limit": 50, "offset": 100},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        assert response.json() == []


class TestGetSingleMessage:
    def test_get_single_message_success(self, client, test_channel, auth_token, path):
        """Successfully retrieves a single message by its UUID."""
        # Seed a message to retrieve
        post_response = client.post(
            path(post_message, channel_id=test_channel.id),
            json={"text": "Target message"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        msg_id = post_response.json()["id"]

        response = client.get(
            path(get_single_message, channel_id=test_channel.id, message_id=msg_id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == msg_id
        assert data["content"] == "Target message"
        assert data["channel_id"] == str(test_channel.id)

    def test_get_single_message_not_found(self, client, test_channel, auth_token, path):
        """Returns 404 when requesting a non-existent message ID."""
        fake_id = uuid.uuid4()
        response = client.get(
            path(get_single_message, channel_id=test_channel.id, message_id=fake_id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Message not found"


class TestGetOnlineUsers:
    def test_get_online_users_empty_or_active(self, client, test_channel, auth_token, path):
        """Returns the structure for online users properly formatted."""
        response = client.get(
            path(get_online_users, channel_id=test_channel.id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "channel_id" in data
        assert data["channel_id"] == str(test_channel.id)
        assert "online_users" in data
        assert isinstance(data["online_users"], list)
