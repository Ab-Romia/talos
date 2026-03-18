from fastapi import status

from backend.auth.password import hash_password, verify_password
from model.identity import IdentityProvider, Issuer
from utils.datetime import utcnow


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
            path("password_authenticate"),
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    def test_with_email(self, client, path, db_session, test_user_with_password):
        """Should authenticate using email instead of username."""
        user, password = test_user_with_password

        response = client.post(
            path("password_authenticate"),
            data={"username": user.primary_email, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

    def test_with_invalid_username(self, client, path, db_session):
        response = client.post(
            path("password_authenticate"),
            data={"username": "nonexistent", "password": "password123"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_invalid_password(self, client, path, db_session, test_user_with_password):
        user, _ = test_user_with_password

        response = client.post(
            path("password_authenticate"),
            data={"username": user.username, "password": "wrongpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_unverified_email(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password
        user.email_verified = False
        db_session.commit()

        response = client.post(
            path("password_authenticate"),
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_deleted_user(self, client, path, db_session, test_user_with_password):
        user, password = test_user_with_password
        user.deleted_at = utcnow()
        db_session.commit()

        response = client.post(
            path("password_authenticate"),
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
            path("password_authenticate"),
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        # The token should be short-lived and require OTP


class TestChangePassword:
    def test_with_sudo_token(self, client, path, db_session, test_user_with_password, sudo_auth_token):
        user, old_password = test_user_with_password
        new_password = "NewPassword456!"

        response = client.put(
            path("change_password"),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify old password no longer works
        login_response = client.post(
            path("password_authenticate"),
            data={"username": user.username, "password": old_password},
        )
        assert login_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Verify new password works
        login_response = client.post(
            path("password_authenticate"),
            data={"username": user.username, "password": new_password},
        )
        assert login_response.status_code == status.HTTP_200_OK

    def test_without_sudo_token(self, client, path, db_session, test_user_with_password, auth_token):
        new_password = "NewPassword456!"

        response = client.put(
            path("change_password"),
            headers={"Authorization": f"Bearer {auth_token}"},
            params={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_clears_sessions(self, client, path, db_session, test_user_with_password, sudo_auth_token):
        from backend.auth.helpers import create_or_update_session

        user, _ = test_user_with_password

        # Create multiple sessions
        for _ in range(3):
            create_or_update_session(db=db_session, user_id=user.id)

        response = client.put(
            path("change_password"),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={"new_password": "NewPassword456!"},
        )

        assert response.status_code == status.HTTP_200_OK

        # New token should be returned
        data = response.json()
        assert "access_token" in data
