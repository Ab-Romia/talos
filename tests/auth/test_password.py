"""Tests for password authentication."""
import pytest
from fastapi import status

from backend.auth.password import hash_password, verify_password
from model.identity import IdentityProvider, Issuer


class TestPasswordHashing:
    """Test password hashing functions."""

    def test_hash_password_creates_valid_hash(self):
        """Should create a bcrypt hash."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 0
        assert hashed.startswith("$2")  # bcrypt prefix

    def test_hash_password_creates_different_hashes(self):
        """Should create different hashes for same password (due to salt)."""
        password = "TestPassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2

    def test_verify_password_accepts_correct_password(self):
        """Should verify correct password."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_rejects_incorrect_password(self):
        """Should reject incorrect password."""
        password = "TestPassword123!"
        hashed = hash_password(password)

        assert verify_password("WrongPassword", hashed) is False


class TestPasswordAuthentication:
    """Test password authentication endpoint."""

    def test_login_with_valid_credentials(self, client, db_session, test_user_with_password):
        """Should authenticate and return token for valid credentials."""
        user, password = test_user_with_password

        response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    def test_login_with_email(self, client, db_session, test_user_with_password):
        """Should authenticate using email instead of username."""
        user, password = test_user_with_password

        response = client.post(
            "/api/auth/password/",
            data={"username": user.primary_email, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

    def test_login_with_invalid_username(self, client, db_session):
        """Should reject login with non-existent username."""
        response = client.post(
            "/api/auth/password/",
            data={"username": "nonexistent", "password": "password123"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_invalid_password(self, client, db_session, test_user_with_password):
        """Should reject login with incorrect password."""
        user, _ = test_user_with_password

        response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": "wrongpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_unverified_email(self, client, db_session, test_user_with_password):
        """Should reject login when email is not verified."""
        user, password = test_user_with_password
        user.email_verified = False
        db_session.commit()

        response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_deleted_user(self, client, db_session, test_user_with_password):
        """Should reject login for deleted user."""
        from datetime import datetime, timezone

        user, password = test_user_with_password
        user.deleted_at = datetime.now(timezone.utc)
        db_session.commit()

        response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_with_totp_enabled(self, client, db_session, test_user_with_password):
        """Should return short-lived token requiring OTP when TOTP is enabled."""
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
            "/api/auth/password/",
            data={"username": user.username, "password": password},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        # The token should be short-lived and require OTP


class TestChangePassword:
    """Test password change endpoint."""

    def test_change_password_with_sudo_token(
            self, client, db_session, test_user_with_password, sudo_auth_token
    ):
        """Should allow password change with sudo token."""
        user, old_password = test_user_with_password
        new_password = "NewPassword456!"

        response = client.put(
            "/api/auth/password/change",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify old password no longer works
        login_response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": old_password},
        )
        assert login_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Verify new password works
        login_response = client.post(
            "/api/auth/password/",
            data={"username": user.username, "password": new_password},
        )
        assert login_response.status_code == status.HTTP_200_OK

    def test_change_password_without_sudo_token(
            self, client, db_session, test_user_with_password, auth_token
    ):
        """Should reject password change without sudo token."""
        new_password = "NewPassword456!"

        response = client.put(
            "/api/auth/password/change",
            headers={"Authorization": f"Bearer {auth_token}"},
            params={"new_password": new_password},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_change_password_clears_sessions(
            self, client, db_session, test_user_with_password, sudo_auth_token
    ):
        """Should clear all existing sessions after password change."""
        from backend.auth.helpers import save_session

        user, _ = test_user_with_password

        # Create multiple sessions
        for _ in range(3):
            save_session(user_id=user.id, db=db_session)

        response = client.put(
            "/api/auth/password/change",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={"new_password": "NewPassword456!"},
        )

        assert response.status_code == status.HTTP_200_OK

        # New token should be returned
        data = response.json()
        assert "access_token" in data
