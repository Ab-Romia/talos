from typing import Callable

import pytest
from faker import Faker

from notifications.model import Notification, NotificationTag


@pytest.fixture
def notification(test_user, db_session) -> Callable[..., Notification]:
    def factory(
            tags=None,
            title=None,
            body=None,
            data=None,
    ):
        faker = Faker()
        title = title or faker.sentence()
        body = body or faker.paragraph()
        if tags is None:
            tags = [NotificationTag.SYSTEM]
        return Notification(
            user_id=test_user.id,
            tags=tags,
            title=title,
            body=body,
            data=data or {},
        )

    return factory


@pytest.fixture
def test_notification(notification, db_session):
    n = notification()
    db_session.add(n)
    db_session.commit()

    yield n

    db_session.delete(n)
    db_session.commit()


@pytest.fixture
def test_subscription(test_user, db_session):
    from notifications.model import PushSubscription
    subscription = PushSubscription(
        user_id=test_user.id,
        endpoint="https://example.com/push",
        keys={"p256dh": "key", "auth": "secret"},
    )
    db_session.add(subscription)
    db_session.commit()
    yield subscription

    db_session.delete(subscription)
    db_session.commit()
