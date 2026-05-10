from typing import Callable
from unittest.mock import Mock

import pytest
from faker import Faker

from notifications import Notification, NotificationsType, notification_service


@pytest.fixture(autouse=True)
def mock_publish(monkeypatch):
    from notifications.notification_worker import publish_message
    publish = Mock()
    monkeypatch.setattr(notification_service, publish_message.__name__, publish)
    return publish


@pytest.fixture
def notification(test_user, db_session) -> Callable[..., Notification]:
    def factory(
            type_=NotificationsType.message,
            title=None,
            body=None,
            is_read=False,
            data=None,
    ):
        faker = Faker()
        title = title or faker.sentence()
        body = body or faker.paragraph()
        return Notification(
            user_id=test_user.id,
            type=type_,
            title=title,
            body=body,
            data=data or {},
            is_read=is_read,
        )

    return factory


@pytest.fixture
def test_notification(notification, db_session):
    n = notification()
    db_session.add(n)
    db_session.commit()

    return n
