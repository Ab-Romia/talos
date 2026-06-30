import uuid
from datetime import timedelta

import pytest
from starlette.requests import Request

from app import app as fastapi_app
from auth import dependencies
from auth.dependencies import UserDep, OptionalUserDep
from auth.utils import errors
from auth.utils.jwt import create_token
from auth.utils.session import SessionClaims, verified_session, unverified_session


@pytest.fixture(scope="session")
def active_user_path():
    path = "/__test_active_user"

    def endpoint(user: UserDep):
        return {"id": str(user.id)}

    fastapi_app.add_api_route(path, endpoint, methods=["GET"])

    return path


@pytest.fixture(scope="session")
def opt_active_user_path():
    path = "/__opt_test_active_user"

    def endpoint(user: OptionalUserDep):
        return {"id": str(user.id)} if user else None

    fastapi_app.add_api_route(path, endpoint, methods=["GET"])

    return path


class TestActiveUserEndpoint:
    @staticmethod
    def _set_session_cookie(client, token: str):
        client.cookies.clear()
        client.cookies.set("user_session", token)

    def test_valid_session(self, client, test_user, auth_token, active_user_path):
        self._set_session_cookie(client, auth_token)
        resp = client.get(active_user_path)

        assert resp.status_code == 200
        assert resp.json()["id"] == str(test_user.id)

    def test_when_otp_required(self, client, test_session, active_user_path):
        test_session.requires_otp = True
        auth_token = create_token(test_session)
        self._set_session_cookie(client, auth_token)

        resp = client.get(active_user_path,
                          headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 401

    def test_when_user_deleted(self, client, db_session, test_user, test_session, auth_token, active_user_path):
        from datetime import timezone, datetime
        test_user.deleted_at = datetime.now(timezone.utc)
        db_session.commit()
        self._set_session_cookie(client, auth_token)

        resp = client.get(active_user_path, headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 401

    def test_when_email_not_verified(self, client, db_session, test_user, test_session, auth_token, active_user_path):
        test_user.signup_complete = False
        db_session.commit()
        self._set_session_cookie(client, auth_token)

        resp = client.get(active_user_path, headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 401

    def test_when_session_not_found(self, client, test_user, active_user_path):
        from datetime import timezone, datetime
        claims = SessionClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),  # Non-existent session
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        token = create_token(claims)
        self._set_session_cookie(client, token)

        resp = client.get(active_user_path)

        assert resp.status_code == 401

    def test_optional_user_invalid(self, client, active_user_path, opt_active_user_path):
        client.cookies.clear()
        resp1 = client.get(active_user_path)
        resp2 = client.get(opt_active_user_path)

        assert resp1.status_code == 401
        assert resp2.status_code == 200
        assert resp2.json() is None

    def test_optional_user_valid(self, client, auth_token, active_user_path, opt_active_user_path):
        self._set_session_cookie(client, auth_token)
        resp1 = client.get(active_user_path)
        resp2 = client.get(opt_active_user_path)

        assert resp2.status_code == 200
        assert resp1.status_code == 200

        assert resp1.json() == resp2.json()


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

        unverified_sess = unverified_session(token, req)
        result = verified_session(next(unverified_sess), db_session)

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
            gen = verified_session(next(unverified_session(req, token)), db_session)
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

        dependencies.sudo(claims)

    def test_when_not_sudo(self, db_session, test_user, test_session):
        from datetime import timezone, datetime
        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
            sudo_exp=None,
        )

        with pytest.raises(errors.SudoRequired):
            dependencies.sudo(claims)

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
            gen = verified_session(next(unverified_session(req, token)), db_session)
            next(gen)
