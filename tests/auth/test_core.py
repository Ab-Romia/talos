"""Tests for core authentication endpoints."""
import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import cfg
from model.identity import User, Session as UserSession


class TestSignup:
    def test_create_user_success(self, client, db_session: Session):
        from faker import Faker
        faker = Faker()
        user_data = {
            "username": "test_" + faker.user_name(),
            "primary_email": faker.email(),
            "password": faker.password(),
            "name": faker.name(),
        }

        response = client.post("/api/auth/signup", data=user_data)

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

    def test_create_user_with_missing_fields(self, client, db_session):
        """Should reject signup with missing required fields."""
        user_data = {
            "username": "newuser",
            # Missing email, password, name
        }

        response = client.post("/api/auth/signup", json=user_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestLogout:

    def test_logout_deletes_session(self, client, db_session, test_user, test_session, auth_token):
        session_id = test_session.id

        jwt_claims = jwt.decode(auth_token,
                                key=cfg().auth.jwt_secret_key,
                                algorithms=[cfg().auth.jwt_algorithm], )
        assert jwt_claims["sub"] == str(test_user.id)
        assert jwt_claims["jti"] == str(session_id)
        assert jwt_claims["exp"] > datetime.now().timestamp()

        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, session_id)
        assert session is None

    def test_logout_without_token(self, client, db_session):
        """Should handle logout without authentication gracefully."""
        response = client.post("/api/auth/logout")

        # Should not fail even without token
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]


class TestSudo:
    """Test sudo mode endpoint."""

    def test_sudo_creates_short_lived_token(self, client, db_session, test_user, test_session, auth_token):
        """Should create a short-lived sudo token."""
        from backend.auth.dependencies import JWTClaims

        response = client.post(
            "/api/auth/sudo",
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
        exp_delta = claims.exp - datetime.now()
        assert exp_delta < timedelta(minutes=20)  # Should be ~15 minutes

    def test_sudo_without_authentication(self, client, db_session):
        """Should require authentication."""
        response = client.post(
            "/api/auth/sudo",
            json={"password": "test"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRevokeToken:
    """Test token revocation endpoint."""

    def test_revoke_session_with_sudo_token(
            self, client, db_session, test_user, sudo_auth_token
    ):
        """Should allow revoking a session with sudo token."""
        from backend.auth.helpers import save_session

        # Create a session to revoke
        session_id = save_session(user_id=test_user.id, db=db_session)

        response = client.post(
            "/api/auth/revoke",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"session_id": str(session_id)},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify session was deleted
        session = db_session.get(UserSession, session_id)
        assert session is None

    def test_revoke_without_sudo_token(self, client, db_session, auth_token):
        """Should require sudo token for revocation."""
        session_id = uuid.uuid4()

        response = client.post(
            "/api/auth/revoke",
            headers={"Authorization": f"Bearer {auth_token}"},
            data={"session_id": str(session_id)},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRefreshToken:
    """Test token refresh endpoint."""

    def test_refresh_extends_session(
            self, client, db_session, test_user, test_session, auth_token
    ):
        """Should extend session expiration and return new token."""
        from backend.auth.dependencies import JWTClaims

        original_expiration = test_session.expires_at

        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

        # Verify session expiration was extended
        db_session.refresh(test_session)
        assert test_session.expires_at != original_expiration

        # Verify token has same session ID
        new_token = data["access_token"]
        claims = JWTClaims.from_jwt_string(new_token)
        assert claims.jti == test_session.id

    def test_refresh_without_authentication(self, client, db_session):
        """Should require authentication to refresh."""
        response = client.post("/api/auth/refresh")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_with_expired_token(self, client, db_session, expired_token):
        """Should reject refresh with expired token."""
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_updates_expiration_to_30_days(
            self, client, db_session, test_user, test_session, auth_token
    ):
        """Should set new expiration to 30 days from now."""
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        db_session.refresh(test_session)
        expected_expiration = datetime.now() + timedelta(days=30)
        # TODO: apply tzinfo in actual code
        expires_at = test_session.expires_at.replace()
        time_diff = abs((expires_at - expected_expiration).total_seconds())

        # Allow 5 second tolerance for test execution time
        assert time_diff < 5
