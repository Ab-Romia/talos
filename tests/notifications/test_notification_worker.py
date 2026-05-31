from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import notifications.tasks as tasks
from notifications.model import (
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationsChannel,
    PushSubscription,
)


@contextmanager
def session_scope(session):
    yield session


class TestNotificationWorker:
    def _mock_push_dependencies(self, monkeypatch, db_session, webpush):
        monkeypatch.setattr(tasks, "webpush_async", webpush)
        monkeypatch.setattr(
            tasks,
            "cfg",
            lambda: SimpleNamespace(
                push=SimpleNamespace(
                    vapid_private_key="private-key",
                    vapid_subject="mailto:test@example.com",
                )
            ),
        )
        monkeypatch.setattr(
            tasks,
            "SessionLocal",
            lambda: session_scope(db_session),
        )

    async def test_web_push_marks_delivery_sent_when_subscription_succeeds(
        self,
        db_session,
        test_user,
        monkeypatch,
    ):
        notification = Notification(
            user_id=test_user.id,
            tags=["system"],
            title="Title",
            body="Body",
            data={"url": "/notif"},
        )
        delivery = NotificationDelivery(
            notification=notification,
            channel=NotificationsChannel.PUSH,
        )
        subscription = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push",
            keys={"p256dh": "key", "auth": "secret"},
        )
        db_session.add_all([notification, delivery, subscription])
        db_session.commit()

        webpush = AsyncMock(return_value=None)
        self._mock_push_dependencies(monkeypatch, db_session, webpush)

        await tasks.web_push(notification.id)

        db_session.refresh(delivery)
        assert webpush.await_count == 1
        assert delivery.status == DeliveryStatus.SENT
        assert delivery.sent_at is not None

    async def test_web_push_marks_delivery_failed_without_subscription(
        self,
        db_session,
        test_user,
        monkeypatch,
    ):
        notification = Notification(
            user_id=test_user.id,
            tags=["system"],
            title="Title",
            body="Body",
            data={"url": "/notif"},
        )
        delivery = NotificationDelivery(
            notification=notification,
            channel=NotificationsChannel.PUSH,
        )
        db_session.add_all([notification, delivery])
        db_session.commit()

        webpush = AsyncMock(return_value=None)
        self._mock_push_dependencies(monkeypatch, db_session, webpush)

        await tasks.web_push(notification.id)

        db_session.refresh(delivery)
        assert webpush.await_count == 0
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.sent_at is None

    async def test_web_push_raises_retryable_error_and_keeps_delivery_pending_when_all_fail_retryably(
        self,
        db_session,
        test_user,
        monkeypatch,
    ):
        notification = Notification(
            user_id=test_user.id,
            tags=["system"],
            title="Title",
            body="Body",
            data={"url": "/notif"},
        )
        delivery = NotificationDelivery(
            notification=notification,
            channel=NotificationsChannel.PUSH,
        )
        subscription = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push",
            keys={"p256dh": "key", "auth": "secret"},
        )
        db_session.add_all([notification, delivery, subscription])
        db_session.commit()

        webpush = AsyncMock(
            side_effect=tasks.WebPushException(
                "temporary",
                response=SimpleNamespace(status=503, json=lambda: {"errno": 0}),
            )
        )
        self._mock_push_dependencies(monkeypatch, db_session, webpush)

        with pytest.raises(tasks.RetryableWebPushError):
            await tasks.web_push(notification.id)

        db_session.refresh(delivery)
        assert webpush.await_count == 1
        assert delivery.status == DeliveryStatus.PENDING
        assert delivery.sent_at is None

    async def test_web_push_marks_delivery_sent_when_one_subscription_succeeds(
        self,
        db_session,
        test_user,
        monkeypatch,
    ):
        notification = Notification(
            user_id=test_user.id,
            tags=["system"],
            title="Title",
            body="Body",
            data={"url": "/notif"},
        )
        delivery = NotificationDelivery(
            notification=notification,
            channel=NotificationsChannel.PUSH,
        )
        failed_subscription = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push-failed",
            keys={"p256dh": "key", "auth": "secret"},
        )
        successful_subscription = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push-success",
            keys={"p256dh": "key-2", "auth": "secret-2"},
        )
        db_session.add_all([notification, delivery, failed_subscription, successful_subscription])
        db_session.commit()

        webpush = AsyncMock(
            side_effect=[
                tasks.WebPushException(
                    "temporary",
                    response=SimpleNamespace(status=503, json=lambda: {"errno": 0}),
                ),
                None,
            ]
        )
        self._mock_push_dependencies(monkeypatch, db_session, webpush)

        await tasks.web_push(notification.id)

        db_session.refresh(delivery)
        assert webpush.await_count == 2
        assert delivery.status == DeliveryStatus.SENT
        assert delivery.sent_at is not None
