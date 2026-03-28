import re
import uuid
from datetime import timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.core import activate_sudo, logout, revoke_token, initiate_signup, complete_signup
from backend.auth.utils.jwt import verify_token
from backend.auth.utils.session import SessionClaims
from model.identity import User, Session as UserSession, IdentityProvider, Issuer


class TestSignup:
    def test_success(self, client, path, db_session, capsys):
        suffix = uuid.uuid4().hex
        email_data = {"email": f"{suffix}@example.com"}

        response = client.post(path(initiate_signup), data=email_data)
        
        if response.status_code != 202:
            print("ERROR", response.json())

        assert response.status_code == status.HTTP_202_ACCEPTED

        stdout = capsys.readouterr().out
        match = re.search(r"token=([^\n]+)", stdout)
        assert match is not None
        verify_token_value = match.group(1).strip()
        
        user_data = {
            "email_token": verify_token_value,
            "username": f"test-{suffix}",
            "auth_type": "password",
            "password": "TestPassword123!",
        }

        verify_response = client.post(path(complete_signup), data=user_data, follow_redirects=False)
        assert verify_response.status_code == status.HTTP_302_FOUND

        user = db_session.scalar(
            select(User)
            .where(User.username == user_data["username"])
        )
        assert user is not None
        assert user.primary_email == email_data["email"]

        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == user.id,
                   IdentityProvider.issuer == Issuer.password)
        )
        assert identity is not None
        assert "hash" in identity.data

    def test_signup_duplicate_username_or_email(self, client, path, test_user):
        response = client.post(
            path(initiate_signup),
            data={"email": test_user.primary_email}
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_verify_duplicate_user_returns_conflict(self, client, path, db_session: Session, capsys, test_user):
        response = client.post(
            path(initiate_signup),
            data={"email": "new_user_for_verify@example.com"}
        )
        assert response.status_code == status.HTTP_202_ACCEPTED

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

        verify_response = client.post(
            path(complete_signup),
            data={
                "email_token": verify_token_value,
                "username": "new-user-for-verify",
                "auth_type": "password",
                "password": "Password123!"
            }
        )
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
