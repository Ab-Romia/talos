import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

from sqlalchemy import select

import notifications.tasks as tasks
from backend.auth.model import User
from notifications.model import (
    Notification,
    NotificationSchema,
    NotificationTag,
    PushSubscription,
    PushSubscriptionSchema,
)
from notifications.service import get_unread_count, get_user_notifications, mark_as_read, push_notification
from utils.datetime import utcnow


class TestNotificationService:
    async def test_create_notification_with_no_subscriptions(self, db_session, test_user, monkeypatch):
        web_push_kiq = AsyncMock(return_value=None)
        monkeypatch.setattr(tasks.webpush, "kiq", web_push_kiq)

        notifications = await push_notification(db=db_session, user_ids=test_user.id, title="Title", body="Body",
                                                data=None)
        notification = notifications[0]

        assert notification.user_id == test_user.id
        assert notification.title == "Title"
        assert notification.body == "Body"
        assert notification.data == {}
        # No deliveries created since no subscriptions exist
        assert len(notification.deliveries) == 0

        db_notification = db_session.scalar(
            select(Notification).where(Notification.id == notification.id)
        )
        assert db_notification is not None
        assert db_notification.id == notification.id
        assert db_notification.data == {}
        web_push_kiq.assert_not_awaited()

    async def test_create_notification_enqueues_per_subscription(
            self,
            db_session,
            test_user,
            monkeypatch,
    ):
        # Create subscriptions
        sub1 = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push1",
            keys={"p256dh": "key1", "auth": "secret1"},
        )
        sub2 = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push2",
            keys={"p256dh": "key2", "auth": "secret2"},
        )
        db_session.add_all([sub1, sub2])
        db_session.commit()

        web_push_kiq = AsyncMock(return_value=None)
        monkeypatch.setattr(tasks.webpush, "kiq", web_push_kiq)

        notifications = await push_notification(db=db_session, user_ids=test_user.id, title="Title", body="Body",
                                                data=None)
        notification = notifications[0]

        # Should have 2 deliveries (one per subscription)
        assert len(notification.deliveries) == 2
        assert web_push_kiq.await_count == 2

        # Verify deliveries have subscription_id set
        delivery_sub_ids = {d.subscription_id for d in notification.deliveries}
        assert delivery_sub_ids == {sub1.id, sub2.id}

    async def test_create_bulk_notifications_persists_all_and_enqueues_each(
            self,
            db_session,
            test_user,
            monkeypatch,
    ):
        other_user = User(
            username=f"notif-{uuid.uuid4().hex[:8]}",
            primary_email=f"notif-{uuid.uuid4().hex[:8]}@example.com",
            signup_complete=True,
            name="Other User",
            data={},
            roles=[],
        )
        db_session.add(other_user)
        db_session.commit()
        db_session.refresh(other_user)

        # Create subscription for first user
        sub1 = PushSubscription(
            user_id=test_user.id,
            endpoint="https://example.com/push1",
            keys={"p256dh": "key1", "auth": "secret1"},
        )
        # Create subscription for second user
        sub2 = PushSubscription(
            user_id=other_user.id,
            endpoint="https://example.com/push2",
            keys={"p256dh": "key2", "auth": "secret2"},
        )
        db_session.add_all([sub1, sub2])
        db_session.commit()

        web_push_kiq = AsyncMock(return_value=None)
        monkeypatch.setattr(tasks.webpush, "kiq", web_push_kiq)

        user_ids = [test_user.id, other_user.id]
        notifications = await push_notification(db=db_session, user_ids=user_ids, title="Bulk", body="Body", data=None)

        assert len(notifications) == len(user_ids)
        assert [n.user_id for n in notifications] == user_ids
        # 2 notifications * 1 subscription each = 2 enqueued tasks
        assert web_push_kiq.await_count == 2

        for notification in notifications:
            db_notification = db_session.scalar(
                select(Notification).where(Notification.id == notification.id)
            )
            assert db_notification is not None
            assert db_notification.id == notification.id

    def test_mark_as_read(self, db_session, notification):
        notif = notification()
        db_session.add(notif)
        db_session.commit()

        result = mark_as_read(
            db=db_session,
            notification_id=notif.id,
            user_id=notif.user_id,
        )

        db_session.refresh(notif)

        assert result is True
        assert notif.read_at is not None

    def test_mark_as_read_returns_false_for_other_user(self, db_session, notification):
        notif = notification()
        db_session.add(notif)
        db_session.commit()

        result = mark_as_read(
            db=db_session,
            notification_id=notif.id,
            user_id=uuid.uuid4(),
        )

        db_session.refresh(notif)

        assert result is False
        assert notif.read_at is None

    def test_mark_as_read_returns_false_when_not_found(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = mark_as_read(
            db=db,
            notification_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )

        assert result is False
        db.commit.assert_not_called()

    async def test_get_user_notifications_returns_ordered_slice(self, test_user, db_session):
        notifications = []
        for index in range(4):
            notifications.extend(
                await push_notification(db=db_session, user_ids=test_user.id, title=f"Title {index}", body="Body",
                                        data=None)
            )

        base_time = utcnow()
        for index, notification in enumerate(notifications):
            notification.created_at = base_time + timedelta(minutes=index)
        notifications[1].read_at = utcnow()
        db_session.commit()

        result = get_user_notifications(db=db_session, user_id=test_user.id, limit=2, offset=1, unread_only=True)

        assert [n.id for n in result] == [notifications[2].id, notifications[0].id]
        assert all(n.read_at is None for n in result)

    def test_get_unread_count_returns_correct_value(self, db_session, notification, test_user):
        notification1 = notification()
        notification2 = notification()
        notification3 = notification()
        notification3.read_at = utcnow()

        db_session.add_all([notification1, notification2, notification3])
        db_session.commit()

        count = get_unread_count(db=db_session, user_id=test_user.id)

        assert count == 2
