from notifications.model import NotificationsType
from notifications.notification_service import push_notification
from notifications.router import get_notifications, mark_as_read_


class TestRouter:
    def test_get_notifications(self, db_session, client, path, test_user, auth_token):
        notification = push_notification(
            db=db_session,
            user_id=test_user.id,
            notif_type=NotificationsType.message,
            title="Test Notification",
            body="This is a test notification",
            data={"key": "value"},
            channels=None,
        )

        r = client.get(
            path(get_notifications) + "?limit=10&offset=0",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["id"] == str(notification.id)
        assert body[0]["title"] == notification.title
        assert body[0]["type"] == notification.type.value
        assert body[0]["data"] == notification.data
        assert body[0]["is_read"] is False

    def test_get_notifications_unread_only(self, db_session, client, path, test_user, notification, auth_token):
        read_notif = push_notification(
            db=db_session,
            user_id=test_user.id,
            notif_type=NotificationsType.message,
            title="Read Notification",
            body="This notification is read",
            data=None,
            channels=None,
        )
        unread_notif = push_notification(
            db=db_session,
            user_id=test_user.id,
            notif_type=NotificationsType.message,
            title="Unread Notification",
            body="This notification is unread",
            data=None,
            channels=None,
        )

        client.post(
            path(mark_as_read_) + f"?notification_id={read_notif.id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        r = client.get(
            path(get_notifications) + "?limit=10&offset=0&unread_only=true",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["id"] == str(unread_notif.id)
        assert body[0]["is_read"] is False

    def test_mark_as_read(self, client, path, test_user, test_notification, db_session, auth_token):
        r = client.post(
            path(mark_as_read_) + f"?notification_id={test_notification.id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert r.status_code == 200

        db_session.refresh(test_notification)
        assert test_notification.is_read is True

    def test_mark_as_read_404(self):
        pass

    def test_get_preferences(self):
        pass

    def test_update_preferences_endpoint_calls_service_and_returns_ok(self):
        pass
