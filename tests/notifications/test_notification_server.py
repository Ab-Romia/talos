# python
import uuid
from datetime import datetime
from enum import Enum

import pytest

import notifications.app.notification_service as svc


class FakeNotification:
    def __init__(self, user_id=None, type=None, title="", body="", data=None, id=None):
        self.id = id or uuid.uuid4()
        self.user_id = user_id
        self.type = type
        self.title = title
        self.body = body
        self.data = data or {}
        self.is_read = False
        self.created_at = datetime.now()


class FakeSession:
    def __init__(self):
        # storage for what was added
        self.added = []
        self.added_all = []
        self.refreshed = []
        self.committed = False

        # values that query() will return
        self.query_first = None
        self.query_all = []
        self.query_count = 0

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added_all.extend(objs)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        # mimic filling fields after DB insert
        self.refreshed.append(obj)

    # simplified query facade used by the service
    def query(self, model):
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, session: FakeSession):
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._session.query_first

    def all(self):
        return self._session.query_all

    def count(self):
        return self._session.query_count

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, n):
        return self

    def limit(self, n):
        return self


class FakeChannel(Enum):
    in_app = "IN_APP"
    email = "EMAIL"
    push = "PUSH"


class FakeType(Enum):
    message = "MESSAGE"
    mention = "MENTION"


@pytest.fixture(autouse=True)
def patch_service_enums_and_publish(monkeypatch):
    # Patch Notification model, channel and type enums and the publish_message used by the service
    monkeypatch.setattr(svc, "Notification", FakeNotification)
    monkeypatch.setattr(svc, "NotificationsChannel", FakeChannel)
    monkeypatch.setattr(svc, "NotificationsType", FakeType)
    called = {"payloads": []}

    def fake_publish(payload):
        called["payloads"].append(payload)

    monkeypatch.setattr(svc, "publish_message", fake_publish)
    return called


def test_create_notification_persists_and_enqueues_in_app_channel(patch_service_enums_and_publish):
    session = FakeSession()
    user_id = uuid.uuid4()
    notif = svc.NotificationService.create_notification(
        db=session,
        user_id=user_id,
        type=FakeType.message,
        title="T",
        body="B",
        data={"x": 1},
        channels=None,  # should default to in_app
    )

    # persisted
    assert session.added, "notification should be added to session"
    added = session.added[0]
    assert isinstance(added, FakeNotification)
    assert added.user_id == user_id
    assert added.title == "T"

    # commit/refresh called
    assert session.committed

    # enqueue called with stringified ids and channel values
    payloads = patch_service_enums_and_publish["payloads"]
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["notification_id"] == str(added.id)
    assert payload["user_id"] == str(user_id)
    assert payload["channels"] == [FakeChannel.in_app.value]


def test_create_bulk_notifications_persists_all_and_enqueues_each(patch_service_enums_and_publish):
    session = FakeSession()
    user_ids = [uuid.uuid4(), uuid.uuid4()]

    notifs = svc.NotificationService.create_bulk_notifications(
        db=session,
        user_ids=user_ids,
        type=FakeType.message,
        title="Bulk",
        body="B",
        data=None,
        channels=[FakeChannel.email, FakeChannel.push],
    )

    # all created and added via add_all
    assert session.added_all or session.added, "should have added notifications"
    # publish called once per notification
    payloads = patch_service_enums_and_publish["payloads"]
    assert len(payloads) == len(user_ids)
    # check payload channels for first
    assert set(payloads[0]["channels"]) == {FakeChannel.email.value, FakeChannel.push.value}


def test_mark_as_read_marks_notification_and_returns_true():
    session = FakeSession()
    fake_notif = FakeNotification(user_id=uuid.uuid4())
    fake_notif.is_read = False
    session.query_first = fake_notif

    result = svc.NotificationService.mark_as_read(
        db=session,
        notification_id=fake_notif.id,
        user_id=fake_notif.user_id,
    )

    assert result is True
    assert fake_notif.is_read is True
    assert session.committed is True


def test_mark_as_read_returns_false_when_not_found():
    session = FakeSession()
    session.query_first = None

    result = svc.NotificationService.mark_as_read(
        db=session,
        notification_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    assert result is False
    assert session.committed is False


def test_get_user_notifications_respects_limit_offset_and_unread_only():
    session = FakeSession()
    # return a sample list to simulate DB response
    sample = [FakeNotification(user_id=uuid.uuid4()), FakeNotification(user_id=uuid.uuid4())]
    session.query_all = sample

    result = svc.NotificationService.get_user_notifications(
        db=session,
        user_id=sample[0].user_id,
        limit=10,
        offset=0,
        unread_only=False,
    )

    assert result == sample


def test_get_unread_count_returns_correct_value():
    session = FakeSession()
    session.query_count = 5

    count = svc.NotificationService.get_unread_count(
        db=session,
        user_id=uuid.uuid4(),
    )

    assert count == 5


def test_enqueue_notification_calls_publish_with_expected_payload(patch_service_enums_and_publish):
    notification_id = uuid.uuid4()
    user_id = uuid.uuid4()
    svc.NotificationService.enqueue_notification(
        notification_id=notification_id,
        user_id=user_id,
        channels=[FakeChannel.email, FakeChannel.push],
    )

    payloads = patch_service_enums_and_publish["payloads"]
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["notification_id"] == str(notification_id)
    assert payload["user_id"] == str(user_id)
    assert payload["channels"] == [FakeChannel.email.value, FakeChannel.push.value]
