import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import app as fastapi_app
from auth import Session as UserSession
from auth.utils.session import NewSessionDep


@pytest.fixture(scope="session")
def test_session_path():
    path = "/__test_session_dep"

    def endpoint(session: NewSessionDep, user_id: uuid.UUID):
        session.sub = user_id
        return {"session_id": session.jti.hex, "user_id": user_id.hex}

    fastapi_app.add_api_route(path, endpoint, methods=["GET"])

    return path


class TestNewSessionDep:
    def test_new_session_creates_session_in_db(self, db_session, test_user, test_session_path):
        response = TestClient(fastapi_app).get(f"{test_session_path}?user_id={test_user.id}")
        assert response.status_code == 200

        data = response.json()
        session_id = uuid.UUID(data["session_id"])
        user_id = uuid.UUID(data["user_id"])

        assert user_id == test_user.id

        session_in_db = db_session.scalar(
            select(UserSession)
            .where(UserSession.id == session_id)
        )
        assert session_in_db is not None
        assert session_in_db.user_id == user_id

    def test_new_session_persists_user_id(self, db_session, test_user, test_session_path):
        response = TestClient(fastapi_app).get(f"{test_session_path}?user_id={test_user.id}")
        assert response.status_code == 200

        data = response.json()
        user_id = uuid.UUID(data["user_id"])

        assert user_id == test_user.id
