from typing import Callable

import pytest
from faker import Faker

from notifications.model import Notification, NotificationsType


@pytest.fixture
def notification(test_user, db_session) -> Callable[..., Notification]:
    def factory(
            type_=NotificationsType.MESSAGE,
            title=None,
            body=None,
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
        )

    return factory


@pytest.fixture
def test_notification(notification, db_session):
    n = notification()
    db_session.add(n)
    db_session.commit()

    return n
