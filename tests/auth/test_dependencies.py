import uuid
from datetime import timedelta

import pytest
from starlette.requests import Request

from app import app as fastapi_app
from backend.auth.utils import helpers
from backend.auth.utils.helpers import UserDep
from backend.auth.utils.jwt import create_token
from backend.auth.utils.session import SessionClaims, verified_session, unverified_session


@pytest.fixture(scope="session")
def active_user_path():
    path = "/__test_active_user"

    def endpoint(user: UserDep):
        return {"id": str(user.id)}

    if not any(route.path == path for route in fastapi_app.routes):
        fastapi_app.add_api_route(path, endpoint, methods=["GET"])

    return path


class TestActiveUserEndpoint:
    def test_valid_session(self, client, test_user, auth_token, active_user_path):
        resp = client.get(active_user_path, cookies={"user_session": auth_token})

        assert resp.status_code == 200
        assert resp.json()["id"] == str(test_user.id)

    def test_when_otp_required(self, client, test_session, active_user_path):
        test_session.requires_otp = True
        auth_token = create_token(test_session)

        resp = client.get(active_user_path,
                          headers={"Authorization": f"Bearer {auth_token}"},
                          cookies={"user_session": auth_token})

        assert resp.status_code == 401

    def test_when_user_deleted(self, client, db_session, test_user, test_session, auth_token, active_user_path):
        from datetime import timezone, datetime
        test_user.deleted_at = datetime.now(timezone.utc)
        db_session.commit()

        resp = client.get(active_user_path, headers={"Authorization": f"Bearer {auth_token}"},
                          cookies={"user_session": auth_token})

        assert resp.status_code == 404

    def test_when_email_not_verified(self, client, db_session, test_user, test_session, auth_token, active_user_path):
        test_user.email_verified = False
        db_session.commit()

        resp = client.get(active_user_path, headers={"Authorization": f"Bearer {auth_token}"},
                          cookies={"user_session": auth_token})

        assert resp.status_code == 401

    def test_when_session_not_found(self, client, test_user, active_user_path):
        from datetime import timezone, datetime
        claims = SessionClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),  # Non-existent session
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        token = create_token(claims)

        resp = client.get(active_user_path, cookies={"user_session": token})

        assert resp.status_code == 401

    # def test_updates_last_active(self, db_session, test_user, test_session):
    #     from sqlalchemy import select
    #     from model.identity import Session
    #     session = db_session.scalar(
    #         select(Session)
    #         .where(Session.id == test_session.jti))
    #
    #     original_time = session.last_used_at
    #
    #     active_user(test_user, test_session)
    #
    #     db_session.refresh(session)
    #
    #     assert session.last_used_at > original_time


class TestGetSessionDependency:
    def test_when_exists(self, db_session, test_user, test_session):
        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=test_session.exp,
        )

        # create a token and call the session dependency directly
        token = create_token(claims)

        req = Request({"type": "http", "state": {}})
        req.state.set_session = None  # Initialize

        unverified_sess = unverified_session(req, token)
        gen = verified_session(next(unverified_sess), db_session)
        result = next(gen)

        assert result.jti == test_session.jti

    def test_when_not_found(self, db_session, test_user):
        from datetime import timezone, datetime
        from starlette.requests import Request

        claims = SessionClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        token = create_token(claims)

        req = Request({"type": "http", "state": {}})

        with pytest.raises(Exception):
            gen = verified_session(req, db_session, token)
            next(gen)


class TestSudoTokenDependency:
    def test_sudo_token(self, db_session, test_user, test_session):
        from datetime import timezone, datetime
        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=datetime.now(timezone.utc) + timedelta(minutes=15),
            sudo_exp=datetime.now(timezone.utc) + timedelta(minutes=1),
        )

        helpers.sudo(claims)

    def test_when_not_sudo(self, db_session, test_user, test_session):
        from datetime import timezone, datetime
        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
            sudo_exp=None,
        )

        with pytest.raises(Exception):
            helpers.sudo(claims)

    def test_when_session_not_found(self, db_session, test_user):
        from datetime import timezone, datetime
        from starlette.requests import Request

        claims = SessionClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=datetime.now(timezone.utc) + timedelta(minutes=15),
            sudo_exp=None,
        )

        token = create_token(SessionClaims(sub=test_user.id, jti=claims.jti, exp=claims.exp))
        req = Request({"type": "http", "state": {}})

        with pytest.raises(Exception):
            gen = verified_session(req, db_session, token)
            next(gen)
