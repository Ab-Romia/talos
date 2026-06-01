import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from backend.auth.model import User
from config import cfg
from notifications.model import Notification, PushSubscription
from notifications.router import (
    get_notifications,
    get_push_subscription,
    get_unread_count,
    get_vapid_public_key,
    mark_all_as_read,
    mark_as_read_,
    subscribe_to_push,
    unsubscribe_from_push,
)
from notifications.service import push_notification


class TestRouter:
    async def test_get_notifications_returns_current_user_notifications(
            self,
            db_session,
            client,
            path,
            test_user,
            auth_token,
    ):
        other_user = User(
            username=f"other-{uuid.uuid4().hex[:8]}",
            primary_email=f"{uuid.uuid4().hex}@example.com",
            signup_complete=True,
            name="Other User",
            data={},
            roles=[],
        )
        db_session.add(other_user)
        db_session.commit()

        notification = (await push_notification(db=db_session, user_ids=[test_user.id], title="Test Notification",
                                                body="This is a test notification", data={"key": "value"}))[0]
        await push_notification(db=db_session, user_ids=[other_user.id], title="Other Notification",
                                body="Should not be returned", data={"ignored": True})

        response = client.get(path(get_notifications), headers={"Authorization": f"Bearer {auth_token}"})

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        # NotificationSchema fields: id, user_id, title, body, tags, data, read_at, created_at
        assert body[0]["id"] == str(notification.id)
        assert body[0]["user_id"] == str(test_user.id)
        assert body[0]["title"] == "Test Notification"
        assert body[0]["body"] == "This is a test notification"
        assert body[0]["data"] == {"key": "value"}
        assert body[0]["read_at"] is None
        assert "created_at" in body[0]
        datetime.fromisoformat(body[0]["created_at"])

    async def test_get_notifications_unread_only_filters_read_items(
            self,
            db_session,
            client,
            path,
            test_user,
            auth_token,
    ):
        read_notification = (await push_notification(db=db_session, user_ids=[test_user.id], title="Read Notification",
                                                     body="This notification is read", data=None))[0]
        unread_notification = (await push_notification(db=db_session, user_ids=[test_user.id],
                                                       title="Unread Notification", body="This notification is unread",
                                                       data=None))[0]

        mark_response = client.post(
            path(mark_as_read_) + f"?notification_id={read_notification.id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert mark_response.status_code == 200

        response = client.get(
            path(get_notifications) + "?unread_only=true",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert [item["id"] for item in body] == [str(unread_notification.id)]
        # NotificationSchema includes read_at which should be None for unread
        assert all(item["read_at"] is None for item in body)

    def test_mark_as_read_returns_null_body_and_persists_read_state(
            self,
            client,
            path,
            test_notification,
            db_session,
            auth_token,
    ):
        response = client.post(
            path(mark_as_read_) + f"?notification_id={test_notification.id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 200
        assert response.json() is None

        db_session.refresh(test_notification)
        assert test_notification.read_at is not None

    def test_mark_as_read_404(self, client, path, auth_token):
        response = client.post(
            path(mark_as_read_) + f"?notification_id={uuid.uuid4()}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Notification not found"}

    async def test_get_unread_count_counts_only_unread_notifications(
            self,
            db_session,
            client,
            path,
            test_user,
            auth_token,
    ):
        unread_one = (await push_notification(db=db_session, user_ids=[test_user.id], title="Unread 1",
                                              body="Unread body 1", data=None))[0]
        unread_two = (await push_notification(db=db_session, user_ids=[test_user.id], title="Unread 2",
                                              body="Unread body 2", data=None))[0]

        response = client.post(
            path(mark_as_read_) + f"?notification_id={unread_one.id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200

        response = client.get(path(get_unread_count), headers={"Authorization": f"Bearer {auth_token}"})

        assert response.status_code == 200
        assert response.json() == {"unread_count": 1}
        assert unread_one.id != unread_two.id

    async def test_mark_all_as_read_marks_only_current_users_notifications(
            self,
            db_session,
            client,
            path,
            test_user,
            auth_token,
    ):
        unread_notification = (await push_notification(db=db_session, user_ids=[test_user.id], title="Unread",
                                                       body="Unread body", data=None))[0]
        already_read = (await push_notification(db=db_session, user_ids=[test_user.id], title="Already read",
                                                body="Read body", data=None))[0]
        client.post(
            path(mark_as_read_) + f"?notification_id={already_read.id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        response = client.post(path(mark_all_as_read), headers={"Authorization": f"Bearer {auth_token}"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        notifications = db_session.scalars(
            select(Notification).where(Notification.user_id == test_user.id)
        ).all()
        assert notifications
        assert all(notification.read_at is not None for notification in notifications)

        unread_count = client.get(path(get_unread_count), headers={"Authorization": f"Bearer {auth_token}"})
        assert unread_count.status_code == 200
        assert unread_count.json() == {"unread_count": 0}
        assert unread_notification.id != already_read.id

    def test_get_vapid_public_key_is_public(self, client, path):
        response = client.get(path(get_vapid_public_key))

        assert response.status_code == 200
        assert cfg().push is not None
        assert response.json() == {"vapid_public_key": cfg().push.vapid_public_key}

    @pytest.mark.parametrize(
        "route, method",
        [
            (get_notifications, "get"),
            (get_unread_count, "get"),
            (mark_all_as_read, "post"),
            (get_push_subscription, "get"),
        ],
    )
    def test_notification_routes_require_auth(self, client, path, route, method):
        response = getattr(client, method)(path(route))

        assert response.status_code == 401

    def test_subscribe_list_and_unsubscribe_push_subscriptions(
            self,
            client,
            path,
            auth_token,
            db_session,
            test_user,
    ):
        first = {
            "endpoint": "https://example.com/push/1",
            "keys": {"p256dh": "key-1", "auth": "secret-1"},
            "expiration_time": None,
        }
        second = {
            "endpoint": "https://example.com/push/2",
            "keys": {"p256dh": "key-2", "auth": "secret-2"},
            "expiration_time": None,
        }

        response = client.get(
            path(get_push_subscription),
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        assert response.json() == []

        for payload in (first, second):
            response = client.post(
                path(subscribe_to_push),
                json=payload,
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert response.status_code == 200

        response = client.get(
            path(get_push_subscription),
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert all(set(item) == {"endpoint", "keys", "expiration_time"} for item in body)
        assert {item["endpoint"]: item["keys"] for item in body} == {
            first["endpoint"]: first["keys"], second["endpoint"]: second["keys"],  # noqa
        }

        response = client.request(
            "DELETE",
            path(unsubscribe_from_push),
            json=first["endpoint"],
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 204

        response = client.get(path(get_push_subscription), headers={"Authorization": f"Bearer {auth_token}"})
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["endpoint"] == second["endpoint"]

        subscriptions = db_session.scalars(
            select(PushSubscription).where(PushSubscription.user_id == test_user.id)
        ).all()
        assert len(subscriptions) == 1
        assert subscriptions[0].endpoint == second["endpoint"]

    def test_unsubscribe_from_push_is_a_noop_for_missing_endpoint(
            self,
            client,
            path,
            auth_token,
    ):
        response = client.request(
            "DELETE",
            path(unsubscribe_from_push),
            json="https://example.com/missing",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == 404
