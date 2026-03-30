import uuid
from datetime import timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.core import activate_sudo, logout, revoke_token, create_user
from backend.auth.utils.jwt import verify_token
from backend.auth.utils.session import SessionClaims
from model.identity import User, Session as UserSession


class TestSignup:
    def test_success(self, client, path, db_session: Session):
        from faker import Faker
        faker = Faker()
        user_data = {
            "username": "test_" + faker.user_name(),
            "primary_email": faker.email(),
            "password": faker.password(),
            "name": faker.name(),
        }

        response = client.post(path(create_user), data=user_data)

        assert response.status_code == status.HTTP_201_CREATED

        # Verify user was created
        user = db_session.scalar(
            select(User)
            .where(User.username == user_data["username"])
        )
        assert user is not None
        assert user.primary_email == user_data["primary_email"]
        assert user.name == user_data["name"]
        assert user.email_verified is True  # TODO marked in code


class TestLogout:
    def test_deletes_session(self, client, path, db_session, test_user, test_session, auth_token):
        session_id = test_session.jti

        jwt_claims = verify_token(auth_token, return_model=SessionClaims)
        assert jwt_claims.sub == test_user.id
        assert jwt_claims.jti == session_id
        from datetime import timezone, datetime
        assert jwt_claims.exp > datetime.now(timezone.utc)

        response = client.post(
            path(logout),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, session_id)
        assert session is None

    def test_without_token(self, client, path, db_session):
        response = client.post(path(logout))

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]


class TestSudo:
    def test_creates_short_lived_token(self, client, path, db_session, test_user, test_session, auth_token):
        response = client.post(
            path(activate_sudo),
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"password": "test"},  # TODO: Implementation needed
        )

        assert response.status_code == status.HTTP_200_OK
        # Implementation returns the token in the cookie by default when Accept header is not application/json
        # and response body is empty.
        token = response.cookies.get("user_session")
        if token is None:
            token = response.headers.get("X-Session-Token")

        assert token is not None

        # Verify token has sudo flag
        claims = verify_token(token, return_model=SessionClaims)
        assert claims.sudo_exp is not None

        # Verify short sudo expiration
        from datetime import timezone, datetime
        sudo_delta = claims.sudo_exp - datetime.now(timezone.utc)
        assert sudo_delta < timedelta(minutes=20)  # Should be ~15 minutes
        assert sudo_delta > timedelta(seconds=0)

    def test_without_authentication(self, client, path, db_session):
        response = client.post(
            path(activate_sudo),
            json={"password": "test"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRevokeToken:
    def test_session_with_sudo_token(self, client, path, db_session, test_session, sudo_auth_token):
        response = client.delete(
            path(revoke_token, session_id=test_session.jti),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, test_session.jti)
        assert session is None

    def test_without_sudo_token(self, client, path, db_session, auth_token):
        session_id = uuid.uuid4()

        response = client.delete(
            path(revoke_token, session_id=session_id),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
