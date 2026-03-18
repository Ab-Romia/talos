import uuid
from datetime import timedelta

import jwt
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import cfg
from model.identity import User, Session as UserSession
from utils.datetime import utcnow


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

        response = client.post(path("create_user"), data=user_data)

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
        session_id = test_session.id

        jwt_claims = jwt.decode(auth_token,
                                key=cfg().auth.jwt_secret_key,
                                algorithms=[cfg().auth.jwt_algorithm], )
        assert jwt_claims["sub"] == str(test_user.id)
        assert jwt_claims["jti"] == str(session_id)
        assert jwt_claims["exp"] > utcnow().timestamp()

        response = client.post(
            path("logout"),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, session_id)
        assert session is None

    def test_without_token(self, client, path, db_session):
        response = client.post(path("logout"))

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]


class TestSudo:
    def test_creates_short_lived_token(self, client, path, db_session, test_user, test_session, auth_token):
        from backend.auth.helpers import JWTClaims

        response = client.post(
            path("sudo"),
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"password": "test"},  # TODO: Implementation needed
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

        # Verify token has sudo flag
        token = data["access_token"]
        claims = JWTClaims.from_jwt_string(token)
        assert claims.sudo is True

        # Verify short expiration
        exp_delta = claims.exp - utcnow()
        assert exp_delta < timedelta(minutes=20)  # Should be ~15 minutes

    def test_without_authentication(self, client, path, db_session):
        response = client.post(
            path("sudo"),
            json={"password": "test"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRevokeToken:
    def test_session_with_sudo_token(self, client, path, db_session, test_user, sudo_auth_token):
        from backend.auth.helpers import create_or_update_session

        # Create a session to revoke
        session_id = create_or_update_session(db=db_session, user_id=test_user.id)

        response = client.post(
            path("revoke_token"),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"session_id": str(session_id)},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, session_id)
        assert session is None

    def test_without_sudo_token(self, client, path, db_session, auth_token):
        session_id = uuid.uuid4()

        response = client.post(
            path("revoke_token"),
            headers={"Authorization": f"Bearer {auth_token}"},
            data={"session_id": str(session_id)},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
