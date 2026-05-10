import uuid
from unittest.mock import Mock

from sqlalchemy import select

from notifications.model import Notification, NotificationsChannel, NotificationsType
from notifications.notification_service import push_notification, push_bulk_notification, mark_as_read, \
    get_user_notifications, get_unread_count


class TestNotificationService:
    def test_create_notification_persists_and_enqueues(self, db_session, mock_publish, test_user):
        notification = push_notification(
            db=db_session,
            user_id=test_user.id,
            notif_type=NotificationsType.message,
            title="Title",
            body="Body",
            data={"x": 1},
            channels=None,
        )

        assert notification.user_id == test_user.id
        assert notification.title == "Title"
        assert notification.body == "Body"

        # assert notification is in database
        db_notification = db_session.scalar(
            select(Notification)
            .where(Notification.id == notification.id)
        )
        assert db_notification is not None
        assert db_notification.id == notification.id

        mock_publish.assert_called_once()
        payload = mock_publish.call_args.args[0]
        assert payload["notification_id"] == notification.id
        assert payload["user_id"] == test_user.id
        assert payload["channels"] == [NotificationsChannel.in_app.value]

    def test_create_bulk_notifications_persists_all_and_enqueues_each(self, db_session, mock_publish, test_user):
        user_ids = [test_user.id]
        notifications = push_bulk_notification(
            db=db_session,
            user_ids=user_ids,
            type_=NotificationsType.message,
            title="Bulk",
            body="Body",
            data=None,
            channels=[NotificationsChannel.email, NotificationsChannel.push],
        )

        assert len(notifications) == len(user_ids)
        assert [n.user_id for n in notifications] == user_ids

        for notification in notifications:
            db_notification = db_session.scalar(
                select(Notification)
                .where(Notification.id == notification.id)
            )
            assert db_notification is not None
            assert db_notification.id == notification.id

        assert mock_publish.call_count == len(user_ids)
        for call, notification in zip(mock_publish.call_args_list, notifications, strict=True):
            payload = call.args[0]
            assert payload["notification_id"] == notification.id
            assert payload["user_id"] == notification.user_id
            assert payload["channels"] == [NotificationsChannel.email.value, NotificationsChannel.push.value]

    def test_mark_as_read(self, db_session, notification):
        notif = notification(is_read=False)
        db_session.add(notif)
        db_session.commit()

        result = mark_as_read(
            db=db_session,
            notification_id=notif.id,
            user_id=notif.user_id,
        )

        # refresh from db to check if updated
        db_session.refresh(notif)

        assert result is True
        assert notif.is_read is True

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

    def test_get_user_notifications_returns_ordered_slice(self, test_user, db_session):
        notifications = push_bulk_notification(
            db=db_session,
            user_ids=[test_user.id] * 20,
            type_=NotificationsType.message,
            title="Title",
            body="Body",
            data=None,
            channels=None,
        )

        result = get_user_notifications(
            db=db_session,
            user_id=test_user.id,
            limit=10,
            offset=5,
            unread_only=True,
        )

        assert set(n.id for n in result) == set(n.id for n in notifications[5:15])

    def test_get_unread_count_returns_correct_value(self, db_session, notification, test_user):
        notification1 = notification(is_read=False)
        notification2 = notification(is_read=False)
        notification3 = notification(is_read=True)

        db_session.add_all([notification1, notification2, notification3])
        db_session.commit()

        count = get_unread_count(db=db_session, user_id=test_user.id, )

        assert count == 2
