from fastapi import status
from sqlalchemy import select

from auth.model import IdentityProvider, Issuer
from auth.password import hash_password, verify_password, password_authenticate, change_password
from auth.utils.session import Session as UserSession


class TestPasswordHashing:
    def test_hash_password(self):
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 0
        assert hashed.startswith("$2")  # bcrypt prefix

    def test_hash_password_is_salted(self):
        password = "TestPassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2

    def test_verify_password_accepts_correct(self):
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_rejects_incorrect(self):
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert verify_password("WrongPassword", hashed) is False


class TestPasswordAuthentication:
    def test_with_valid_credentials(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password

        response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": password},
            headers={"Accept": "text/html"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "user_session" in response.cookies

    def test_with_email(self, client, path, db_session, test_user_with_password):
        """Should authenticate using email instead of username."""
        user, password = test_user_with_password

        response = client.post(
            path(password_authenticate),
            data={"username": user.primary_email, "password": password},
            headers={"Accept": "text/html"},
        )

        assert response.status_code == status.HTTP_200_OK
        # data = response.json()
        # assert "session_token" in data
        assert "user_session" in response.cookies

    def test_with_invalid_username(self, client, path, db_session):
        response = client.post(
            path(password_authenticate),
            data={"username": "nonexistent", "password": "password123"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_invalid_password(self, client, path, db_session, test_user_with_password):
        user, _ = test_user_with_password

        response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": "wrong_password"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_unverified_email(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password
        user.signup_complete = False
        db_session.commit()

        response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_deleted_user(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password
        from datetime import timezone, datetime
        user.deleted_at = datetime.now(timezone.utc)
        db_session.commit()

        response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_totp_enabled(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password

        # Add TOTP identity provider
        totp_identity = IdentityProvider(
            user_id=user.id,
            issuer=Issuer.totp,
            data={"secret": "test-secret"},
        )
        db_session.add(totp_identity)
        db_session.commit()

        response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": password},
            headers={"Accept": "text/html"},
        )

        assert response.status_code == status.HTTP_200_OK
        # data = response.json()
        # assert "access_token" in data
        assert "user_session" in response.cookies
        # The token should be short-lived and require OTP


class TestChangePassword:
    def test_with_sudo_token(self, client, path, db_session, test_user_with_password, sudo_auth_token):
        user, old_password = test_user_with_password
        new_password = "NewPassword456!"

        response = client.put(
            path(change_password),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify old password no longer works
        login_response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": old_password},
        )
        assert login_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Verify the new password
        login_response = client.post(
            path(password_authenticate),
            data={"username": user.username, "password": new_password},
        )
        assert login_response.status_code == status.HTTP_200_OK

    def test_without_sudo_token(self, client, path, db_session, test_user_with_password, auth_token):
        new_password = "NewPassword456!"

        response = client.put(
            path(change_password),
            headers={"Authorization": f"Bearer {auth_token}"},
            data={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_clears_sessions(self, client, path, db_session, test_user_with_password, sudo_auth_token):
        user, _ = test_user_with_password

        # Create multiple sessions
        for _ in range(3):
            session = UserSession(user_id=user.id)
            db_session.add(session)
        db_session.commit()

        response = client.put(
            path(change_password),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"new_password": "NewPassword456!"},
        )

        assert response.status_code == status.HTTP_200_OK

        # New token should be returned
        # data = response.json()
        # assert "access_token" in data

        # Verify other sessions are cleared
        sessions = db_session.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars().all()
        # Should be 1 session remaining (the current one)
        assert len(sessions) == 1
