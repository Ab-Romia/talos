from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pywebpush import WebPushException
from taskiq.brokers.inmemory_broker import InMemoryBroker

import notifications.tasks as tasks
from notifications.model import (
    DeliveryStatus,
    NotificationDelivery,
    NotificationsChannel,
    NotificationSchema,
    PushSubscriptionSchema,
)


@pytest.fixture(autouse=True)
def assert_in_memory():
    from broker import broker
    assert isinstance(broker, InMemoryBroker), "Expected InMemoryBroker for testing"


@pytest.fixture
def test_delivery(db_session, test_notification, test_subscription):
    delivery = NotificationDelivery(
        notification=test_notification,
        channel=NotificationsChannel.PUSH,
        subscription_id=test_subscription.id
    )
    db_session.add(delivery)
    db_session.commit()
    return delivery


class TestNotificationWorker:
    async def test_web_push_delivery_success(self, db_session, test_user, test_notification, test_subscription,
                                             monkeypatch, test_delivery):
        webpush = AsyncMock(return_value=None)
        monkeypatch.setattr(tasks, "webpush_async", webpush)

        await tasks.webpush.kiq(
            NotificationSchema.model_validate(test_notification),
            PushSubscriptionSchema.model_validate(test_subscription)
        )

        db_session.refresh(test_delivery)
        assert webpush.await_count == 1
        assert test_delivery.status == DeliveryStatus.SENT
        assert test_delivery.sent_at is not None

    async def test_web_push_delivery_failed(self, test_notification, test_subscription,
                                            monkeypatch, test_delivery, db_session):
        webpush = AsyncMock(
            return_value=None,
            side_effect=WebPushException(message="temporary")
        )
        monkeypatch.setattr(tasks, "webpush_async", webpush)

        await tasks.webpush.kiq(
            NotificationSchema.model_validate(test_notification),
            PushSubscriptionSchema.model_validate(test_subscription)
        )

        db_session.refresh(test_delivery)
        assert webpush.await_count == tasks.webpush.labels.get("max_retries")
        assert test_delivery.status == DeliveryStatus.FAILED

    async def test_web_push_marks_delivery_sent_on_success(
            self, db_session, monkeypatch,
            test_notification, test_subscription, test_delivery):
        webpush = AsyncMock(
            side_effect=[
                WebPushException(
                    "temporary",
                    response=SimpleNamespace(status=503, json=lambda: {"errno": 0}),
                ),
                None,
            ]
        )
        monkeypatch.setattr(tasks, "webpush_async", webpush)

        # Convert to schemas for the new signature
        notification_schema = NotificationSchema.model_validate(test_notification)
        subscription_schema = PushSubscriptionSchema.model_validate(test_subscription)

        await tasks.webpush.kiq(notification_schema, subscription_schema)

        db_session.refresh(test_delivery)
        assert webpush.await_count == 2
        assert test_delivery.status == DeliveryStatus.SENT
        assert test_delivery.sent_at is not None
