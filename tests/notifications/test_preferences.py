# python
import uuid
from fastapi import FastAPI
from fastapi.testclient import TestClient

import notifications.app.preferences as preferences_mod


class DummyUser:
    def __init__(self, id):
        self.id = id


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(preferences_mod.router)
    return app


def _override_deps(app, user=None, db=None):
    if user is not None:
        app.dependency_overrides[preferences_mod.UserDep] = lambda: user
    if db is not None:
        app.dependency_overrides[preferences_mod.DatabaseDep] = lambda: db


def test_get_preferences_returns_serialized_preferences(app, monkeypatch):
    sample_user_id = uuid.uuid4()

    # create a lightweight object with attributes expected by Pydantic (from_attributes=True)
    fake_pref = type("P", (), {
        "channel": preferences_mod.NotificationsChannel.email,
        "enabled": False
    })()

    monkeypatch.setattr(
        preferences_mod.PreferencesService,
        "get_preferences",
        staticmethod(lambda db, user_id: [fake_pref])
    )

    _override_deps(app, user=DummyUser(sample_user_id), db=object())

    with TestClient(app) as client:
        r = client.get("/preferences/")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["channel"] == preferences_mod.NotificationsChannel.email.value
        assert body[0]["enabled"] is False


def test_update_preferences_calls_service_and_returns_ok(app, monkeypatch):
    sample_user_id = uuid.uuid4()
    captured = {}

    def fake_update(db, user_id, preferences):
        captured["db"] = db
        captured["user_id"] = user_id
        captured["preferences"] = preferences

    monkeypatch.setattr(
        preferences_mod.PreferencesService,
        "update_preferences",
        staticmethod(fake_update)
    )

    _override_deps(app, user=DummyUser(sample_user_id), db=object())

    payload = [{"channel": preferences_mod.NotificationsChannel.push.value, "enabled": True}]

    with TestClient(app) as client:
        r = client.put("/preferences/", json=payload)
        assert r.status_code == 200
        assert r.json() == {"status": "updated"}

    # ensure service was called with the overridden db and correct user id
    assert "user_id" in captured and captured["user_id"] == sample_user_id
    assert "preferences" in captured and isinstance(captured["preferences"], list)
