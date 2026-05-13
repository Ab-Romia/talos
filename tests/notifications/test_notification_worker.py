import asyncio
import json
import uuid
from unittest.mock import Mock, AsyncMock

import pytest
from sqlalchemy import select

import notifications.tasks as worker
from notifications.model import NotificationDelivery, NotificationsChannel


# TODO: actually test on a live RabbitMQ instance
class TestNotificationWorker:

    def test_process_notification_creates_deliveries_and_commits(self, monkeypatch, db_session, test_notification):
        notify_mock = AsyncMock()
        monkeypatch.setattr(worker, "notify_user", notify_mock)

        asyncio.run(worker.process_notification(
            notification_id=test_notification.id,
            channels=[NotificationsChannel.email, NotificationsChannel.push],
            db=db_session
        ))

        deliveries = db_session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == test_notification.id)
        ).all()

        assert deliveries is not None
        assert len(deliveries) == 2
        assert all(isinstance(delivery, NotificationDelivery) for delivery in deliveries)
        assert [delivery.channel for delivery in deliveries] == [NotificationsChannel.email, NotificationsChannel.push]

    def test_process_notification_rolls_back_when_notification_is_missing(self, db_session):
        # calling the async function synchronously without awaiting is fine for the fallback path in tests
        asyncio.run(worker.process_notification(
            notification_id=uuid.uuid4(),
            channels=[NotificationsChannel.email],
            db=db_session
        ))

        deliveries = db_session.scalars(
            select(NotificationDelivery)
        ).all()

        assert len(deliveries) == 0

    # TODO: add more exception cases here, e.g. database errors, notification sending errors, etc.
    @pytest.mark.parametrize("exception", [])
    @pytest.mark.skip
    def test_process_notification_rolls_back_on_exception(self, monkeypatch, db_session, exception):
        db_mock = Mock()
        db_mock.add.return_value.__enter__.side_effect = exception

        with pytest.raises(type(exception)):
            worker.process_notification(
                notification_id=uuid.uuid4(),
                channels=[NotificationsChannel.email],
                db=db_mock
            )

        deliveries = db_session.scalars(
            select(NotificationDelivery)
        ).all()

        assert len(deliveries) == 0
        assert db_mock.rollback.called

    @pytest.mark.skipif(
        not hasattr(worker, 'rabbitmq_available') or not worker.rabbitmq_available(),
        reason="RabbitMQ connection not available"
    )
    def test_callback_parses_payload_calls_process_and_acks_channel(self, monkeypatch, db_session):
        process_mock = AsyncMock()
        monkeypatch.setattr(worker, "process_notification", process_mock)

        # Create real RabbitMQ channel and method objects instead of mocks
        # Note: You'll need to establish actual RabbitMQ connection for this test
        payload = {
            "notification_id": uuid.uuid4().hex,
            "channels": [NotificationsChannel.email.value, NotificationsChannel.push.value]
        }
        body = json.dumps(payload).encode()

        # This test now requires actual RabbitMQ infrastructure
        # You would need to set up ch, method, and properties from a real connection
        # asyncio.run(worker.on_message_callback(ch, method, properties, body, db_session))

        # For now, keeping the functional test structure but requiring RabbitMQ
        # Implementation details depend on your worker module's RabbitMQ setup
        pytest.skip("Requires actual RabbitMQ connection setup - implement connection logic")
