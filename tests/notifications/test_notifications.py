# python
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import notifications.app.notifications as notifications_mod


class DummyUser:
    def __init__(self, id):
        self.id = id


class FakeDBForReadAll:
    def __init__(self, notifications):
        self._notifications = notifications
        self.committed = False

    class _Q:
        def __init__(self, notifications):
            self._notifications = notifications

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self._notifications

    def query(self, model):
        return FakeDBForReadAll._Q(self._notifications)

    def commit(self):
        self.committed = True


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(notifications_mod.router)
    return app


def _override_deps(app, user=None, db=None):
    if user is not None:
        app.dependency_overrides[notifications_mod.UserDep] = lambda: user
    if db is not None:
        app.dependency_overrides[notifications_mod.DatabaseDep] = lambda: db


def test_get_notifications_returns_serialized_notifications_with_pagination(app, monkeypatch):
    sample_user_id = uuid.uuid4()
    sample = {
        "id": str(uuid.uuid4()),
        "type": "MESSAGE",
        "title": "Hello",
        "body": "Body",
        "data": {"x": 1},
        "is_read": False,
        "created_at": datetime.utcnow().isoformat(),
    }

    def fake_get_user_notifications(db, user_id, limit, offset, unread_only):
        return [sample]

    monkeypatch.setattr(notifications_mod.NotificationService, "get_user_notifications", staticmethod(fake_get_user_notifications))

    _override_deps(app, user=DummyUser(sample_user_id), db=object())

    with TestClient(app) as client:
        r = client.get("/notifications/?limit=10&offset=0")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["id"] == sample["id"]
        assert body[0]["title"] == sample["title"]
        assert body[0]["type"] == sample["type"]


def test_get_notifications_unread_only_filters_correctly(app, monkeypatch):
    captured = {}

    def fake_get_user_notifications(db, user_id, limit, offset, unread_only):
        captured["unread_only"] = unread_only
        return []

    monkeypatch.setattr(notifications_mod.NotificationService, "get_user_notifications", staticmethod(fake_get_user_notifications))
    _override_deps(app, user=DummyUser(uuid.uuid4()), db=object())

    with TestClient(app) as client:
        r = client.get("/notifications/?unread_only=true")
        assert r.status_code == 200
        assert captured.get("unread_only") is True


def test_mark_as_read_returns_404_for_nonexistent_notification(app, monkeypatch):
    monkeypatch.setattr(notifications_mod.NotificationService, "mark_as_read", staticmethod(lambda db, notification_id, user_id: False))
    _override_deps(app, user=DummyUser(uuid.uuid4()), db=object())

    with TestClient(app) as client:
        r = client.post("/notifications/read", params={"notification_id": str(uuid.uuid4())})
        assert r.status_code == 404


def test_mark_as_read_marks_and_returns_ok_for_existing(app, monkeypatch):
    monkeypatch.setattr(notifications_mod.NotificationService, "mark_as_read", staticmethod(lambda db, notification_id, user_id: True))
    _override_deps(app, user=DummyUser(uuid.uuid4()), db=object())

    with TestClient(app) as client:
        r = client.post("/notifications/read", params={"notification_id": str(uuid.uuid4())})
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_get_unread_count_endpoint_returns_correct_value(app, monkeypatch):
    monkeypatch.setattr(notifications_mod.NotificationService, "get_unread_count", staticmethod(lambda db, user_id: 7))
    _override_deps(app, user=DummyUser(uuid.uuid4()), db=object())

    with TestClient(app) as client:
        r = client.get("/notifications/unread-count")
        assert r.status_code == 200
        assert r.json() == {"unread_count": 7}


def test_mark_all_as_read_updates_all_unread_and_returns_ok(app):
    # prepare two fake notification objects
    class N:
        def __init__(self):
            self.is_read = False

    notifs = [N(), N()]
    fake_db = FakeDBForReadAll(notifs)
    _override_deps(app, user=DummyUser(uuid.uuid4()), db=fake_db)

    with TestClient(app) as client:
        r = client.post("/notifications/read-all")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        # all notifications should be marked read and commit called
        assert all(getattr(n, "is_read", None) is True for n in notifs)
        assert fake_db.committed is True
