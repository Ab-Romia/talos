import re
import uuid
from datetime import timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.core import activate_sudo, logout, revoke_token, create_user, verify_email
from backend.auth.utils.jwt import verify_token
from backend.auth.utils.session import SessionClaims
from model.identity import User, Session as UserSession, IdentityProvider, Issuer


class TestSignup:
    def test_success(self, client, path, db_session, capsys):
        suffix = uuid.uuid4().hex
        user_data = {
            "username": f"test-{suffix}",
            "email": f"{suffix}@example.com",
            "password": "TestPassword123!",
        }

        response = client.post(path(create_user), data=user_data)

        assert response.status_code == status.HTTP_200_OK

        user = db_session.scalar(
            select(User)
            .where(User.username == user_data["username"])
        )
        assert user is None

        stdout = capsys.readouterr().out
        match = re.search(r"token=([^\n]+)", stdout)
        assert match is not None
        verify_token_value = match.group(1).strip()

        verify_response = client.get(f"{path(verify_email)}?token={verify_token_value}", follow_redirects=False)
        assert verify_response.status_code == status.HTTP_302_FOUND

        user = db_session.scalar(
            select(User)
            .where(User.username == user_data["username"])
        )
        assert user is not None
        assert user.primary_email == user_data["email"]

        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == user.id,
                   IdentityProvider.issuer == Issuer.password)
        )
        assert identity is not None
        assert "hash" in identity.data

    def test_signup_duplicate_username_or_email(self, client, path, test_user):
        response = client.post(
            path(create_user),
            data={
                "username": test_user.username,
                "email": test_user.primary_email,
                "password": "Password123!",
            }
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_verify_duplicate_user_returns_conflict(self, client, path, db_session: Session, capsys, test_user):
        response = client.post(
            path(create_user),
            data={
                "username": "new-user-for-verify",
                "email": "new_user_for_verify@example.com",
                "password": "Password123!",
            }
        )
        assert response.status_code == status.HTTP_200_OK

        stdout = capsys.readouterr().out
        match = re.search(r"token=([^\n]+)", stdout)
        assert match is not None
        verify_token_value = match.group(1).strip()

        # Insert a conflicting user before verify to mimic race condition.
        conflict = User(
            username="new-user-for-verify",
            primary_email="different_email@example.com",
            name="Conflict",
            data={},
            roles=[],
        )
        db_session.add(conflict)
        db_session.commit()

        verify_response = client.get(f"{path(verify_email)}?token={verify_token_value}")
        assert verify_response.status_code == status.HTTP_409_CONFLICT


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
