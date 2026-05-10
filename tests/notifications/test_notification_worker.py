# python
import json
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

import notifications.app.notification_worker as worker


class FakeNotification:
    def __init__(self, id=None, user_id=None, title="T", body="B", type_obj=None):
        self.id = id or uuid.uuid4()
        self.user_id = user_id or uuid.uuid4()
        self.title = title
        self.body = body
        # type must have .value used by notify_user
        self.type = type_obj or Mock(value="MESSAGE")


class FakeNotificationDelivery:
    def __init__(self, notification_id=None, channel=None, is_sent=False):
        self.notification_id = notification_id
        self.channel = channel
        self.is_sent = is_sent


class FakeSession:
    def __init__(self, query_first=None, raise_on_query=False):
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._query_first = query_first
        self._raise_on_query = raise_on_query

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def query(self, model):
        if self._raise_on_query:
            raise RuntimeError("forced query error")
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, session: FakeSession):
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._session._query_first


@pytest.fixture(autouse=True)
def patch_worker_deps(monkeypatch):
    # Provide sane defaults for Notification/Delivery/Channel so tests can override as needed
    monkeypatch.setattr(worker, "NotificationDelivery", FakeNotificationDelivery)
    # NotificationsChannel is used as a callable: NotificationsChannel(channel_name)
    monkeypatch.setattr(worker, "NotificationsChannel", lambda v: v)
    # ensure Notification name exists even if not used by our fakes
    monkeypatch.setattr(worker, "Notification", FakeNotification)


def test_process_notification_creates_deliveries_and_commits(monkeypatch):
    # Prepare a fake notification returned by DB query
    fake_notif = FakeNotification()
    session = FakeSession(query_first=fake_notif)

    # Ensure SessionLocal returns our session instance so we can inspect it after call
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    # Prevent notify_user from running asyncio; replace with simple mock
    notify_mock = Mock()
    monkeypatch.setattr(worker, "notify_user", notify_mock)

    payload = {
        "notification_id": str(fake_notif.id),
        "channels": ["EMAIL", "PUSH"],
    }

    # Run the processing
    worker.process_notification(payload)

    # Two deliveries should be created and added to DB
    assert len(session.added) == 2
    assert all(isinstance(a, FakeNotificationDelivery) for a in session.added)
    # commit should have been called
    assert session.committed is True
    # notify_user should have been called once per channel (implementation calls it per delivery)
    assert notify_mock.call_count == len(payload["channels"])


def test_process_notification_handles_missing_notification_gracefully(monkeypatch):
    # DB returns no notification
    session = FakeSession(query_first=None)
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    payload = {
        "notification_id": str(uuid.uuid4()),
        "channels": ["IN_APP"],
    }

    # Should not raise
    worker.process_notification(payload)

    # Nothing added, no commit
    assert session.added == []
    assert session.committed is False
    # session should be closed even on early return
    assert session.closed is True


def test_process_notification_rolls_back_on_exception(monkeypatch):
    # Force an exception during query
    session = FakeSession(raise_on_query=True)
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    payload = {
        "notification_id": str(uuid.uuid4()),
        "channels": ["EMAIL"],
    }

    # Should not propagate; internal rollback should be called
    worker.process_notification(payload)

    assert session.rolled_back is True
    assert session.closed is True


def test_notify_user_uses_manager_send_to_user_via_asyncio_run(monkeypatch):
    # Prepare a fake notification with a type that has .value
    fake_type = Mock(value="MESSAGE")
    fake_notif = FakeNotification(type_obj=fake_type)

    # Replace manager with an object whose send_to_user is an AsyncMock
    fake_manager = Mock()
    fake_manager.send_to_user = AsyncMock()
    monkeypatch.setattr(worker, "manager", fake_manager)

    # Call notify_user (it uses asyncio.run internally)
    worker.notify_user(fake_notif)

    # Ensure send_to_user was awaited with the expected args
    fake_manager.send_to_user.assert_awaited_once()
    called_args = fake_manager.send_to_user.call_args[0]
    # first arg is user_id as string, second is payload dict
    assert called_args[0] == str(fake_notif.user_id)
    payload = called_args[1]
    assert payload["id"] == str(fake_notif.id)
    assert payload["title"] == fake_notif.title
    assert payload["body"] == fake_notif.body
    assert payload["type"] == fake_type.value


def test_callback_parses_payload_calls_process_and_acks_channel(monkeypatch):
    # Patch process_notification to capture the payload
    process_mock = Mock()
    monkeypatch.setattr(worker, "process_notification", process_mock)

    # Create fake channel and method with delivery_tag
    ch = Mock()
    method = Mock()
    method.delivery_tag = 123

    payload = {"notification_id": str(uuid.uuid4()), "channels": ["IN_APP"]}
    body = json.dumps(payload).encode()

    # Call callback
    worker.callback(ch, method, None, body)

    # process_notification should have been called with parsed payload
    process_mock.assert_called_once_with(payload)
    # channel.basic_ack must be called with the same delivery tag
    ch.basic_ack.assert_called_once_with(delivery_tag=method.delivery_tag)
