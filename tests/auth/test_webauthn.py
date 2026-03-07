"""Tests for WebAuthn/Passkey authentication."""
import json
from unittest.mock import Mock, patch

import jwt
from fastapi import status

from model.identity import IdentityProvider, Issuer


class TestGeneratePasskey:
    """Test passkey generation endpoint."""

    def test_generate_passkey_for_registration(
            self, client, db_session, test_user, auth_token, test_config
    ):
        """Should generate registration options when user is authenticated."""
        response = client.post(
            "/api/auth/passkey/generate",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "options" in data
        assert "jwt_challenge" in data

        # Verify JWT challenge contains user info
        claims = jwt.decode(
            jwt=data["jwt_challenge"],
            key=test_config.auth.jwt_secret_key,
            algorithms=[test_config.auth.jwt_algorithm],
        )
        assert "sub" in claims
        assert "challenge" in claims
        assert str(test_user.id) == claims["sub"]

    def test_generate_passkey_for_authentication(
            self, client, db_session, test_config
    ):
        """Should generate authentication options when user is not authenticated."""
        response = client.post("/api/auth/passkey/generate")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "options" in data
        assert "jwt_challenge" in data

        # Verify JWT challenge does not contain user info
        claims = jwt.decode(
            jwt=data["jwt_challenge"],
            key=test_config.auth.jwt_secret_key,
            algorithms=[test_config.auth.jwt_algorithm],
        )
        assert "sub" not in claims
        assert "challenge" in claims


class TestRegisterPasskey:
    """Test passkey registration endpoint."""

    @patch("backend.auth.webauthn.webauthn.verify_registration_response")
    def test_register_passkey_with_valid_credential(
            self, mock_verify, client, db_session, test_user, sudo_auth_token, test_config
    ):
        """Should register passkey when valid credential is provided."""
        from webauthn.helpers import bytes_to_base64url

        # Mock verification response
        mock_verified = Mock()
        mock_verified.credential_id = b"test-credential-id"
        mock_verified.credential_public_key = b"test-public-key"
        mock_verified.sign_count = 0
        mock_verified.credential_device_type = Mock(value="single_device")
        mock_verified.credential_backed_up = False
        mock_verify.return_value = mock_verified

        # Create JWT challenge
        challenge = b"test-challenge"
        jwt_challenge = jwt.encode(
            payload={
                "sub": str(test_user.id),
                "challenge": bytes_to_base64url(challenge),
            },
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({"id": "test-credential-id", "response": {}})

        response = client.post(
            "/api/auth/passkey/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
                "name": "My Passkey",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

        # Verify passkey identity was created
        identity = db_session.query(IdentityProvider).filter(
            IdentityProvider.user_id == test_user.id,
            IdentityProvider.issuer == Issuer.passkey,
        ).first()
        assert identity is not None
        assert identity.data["name"] == "My Passkey"

    def test_register_passkey_without_sudo_token(
            self, client, db_session, test_user, auth_token, test_config
    ):
        """Should require sudo token for registration."""
        jwt_challenge = jwt.encode(
            payload={"sub": str(test_user.id), "challenge": "test"},
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        response = client.post(
            "/api/auth/passkey/register",
            headers={"Authorization": f"Bearer {auth_token}"},
            params={
                "jwt_challenge": jwt_challenge,
                "credential": "{}",
                "name": "Test",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_passkey_with_invalid_challenge(
            self, client, db_session, test_user, sudo_auth_token
    ):
        """Should reject registration with invalid challenge JWT."""
        response = client.post(
            "/api/auth/passkey/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={
                "jwt_challenge": "invalid-jwt",
                "credential": "{}",
                "name": "Test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("backend.auth.webauthn.webauthn.verify_registration_response")
    def test_register_passkey_with_verification_failure(
            self, mock_verify, client, db_session, test_user, sudo_auth_token, test_config
    ):
        """Should reject registration when verification fails."""
        from webauthn.helpers.exceptions import InvalidRegistrationResponse
        from webauthn.helpers import bytes_to_base64url

        # Mock verification to raise exception
        mock_verify.side_effect = InvalidRegistrationResponse("Verification failed")

        jwt_challenge = jwt.encode(
            payload={
                "sub": str(test_user.id),
                "challenge": bytes_to_base64url(b"test-challenge"),
            },
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({"id": "test-credential-id", "response": {}})

        response = client.post(
            "/api/auth/passkey/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
                "name": "Test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestVerifyPasskey:
    """Test passkey authentication endpoint."""

    @patch("backend.auth.webauthn.webauthn.verify_authentication_response")
    def test_verify_passkey_with_valid_credential(
            self, mock_verify, client, db_session, test_user, test_config
    ):
        """Should authenticate and return token when passkey is valid."""
        from webauthn.helpers import bytes_to_base64url

        # Setup passkey for user
        credential_id = bytes_to_base64url(b"test-credential-id")
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.passkey,
            data={
                "name": "Test Passkey",
                "credential_id": credential_id,
                "credential_public_key": bytes_to_base64url(b"test-public-key"),
                "sign_count": 0,
                "device_type": "single_device",
                "backed_up": False,
            },
        )
        db_session.add(identity)
        db_session.commit()

        # Mock verification response
        mock_verified = Mock()
        mock_verified.new_sign_count = 1
        mock_verify.return_value = mock_verified

        # Create JWT challenge
        jwt_challenge = jwt.encode(
            payload={"challenge": bytes_to_base64url(b"test-challenge")},
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            "/api/auth/passkey/verify",
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

    def test_verify_passkey_with_invalid_challenge(
            self, client, db_session
    ):
        """Should reject authentication with invalid challenge JWT."""
        response = client.post(
            "/api/auth/passkey/verify",
            params={
                "jwt_challenge": "invalid-jwt",
                "credential": "{}",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_verify_passkey_with_nonexistent_credential(
            self, client, db_session, test_config
    ):
        """Should reject authentication when credential not found."""
        from webauthn.helpers import bytes_to_base64url

        jwt_challenge = jwt.encode(
            payload={"challenge": bytes_to_base64url(b"test-challenge")},
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({
            "id": "nonexistent-id",
            "rawId": "nonexistent-id",
            "response": {},
        })

        response = client.post(
            "/api/auth/passkey/verify",
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("backend.auth.webauthn.webauthn.verify_authentication_response")
    def test_verify_passkey_updates_sign_count(
            self, mock_verify, client, db_session, test_user, test_config
    ):
        """Should update sign count after successful authentication."""
        from webauthn.helpers import bytes_to_base64url

        # Setup passkey
        credential_id = bytes_to_base64url(b"test-credential-id")
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.passkey,
            data={
                "name": "Test Passkey",
                "credential_id": credential_id,
                "credential_public_key": bytes_to_base64url(b"test-public-key"),
                "sign_count": 5,
                "device_type": "single_device",
                "backed_up": False,
            },
        )
        db_session.add(identity)
        db_session.commit()
        identity_id = identity.id

        # Mock verification response with new sign count
        mock_verified = Mock()
        mock_verified.new_sign_count = 6
        mock_verify.return_value = mock_verified

        jwt_challenge = jwt.encode(
            payload={"challenge": bytes_to_base64url(b"test-challenge")},
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            "/api/auth/passkey/verify",
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify sign count was updated
        db_session.expire_all()
        updated_identity = db_session.query(IdentityProvider).filter(
            IdentityProvider.id == identity_id
        ).first()
        assert updated_identity.data["sign_count"] == 6

    @patch("backend.auth.webauthn.webauthn.verify_authentication_response")
    def test_verify_passkey_with_verification_failure(
            self, mock_verify, client, db_session, test_user, test_config
    ):
        """Should reject authentication when verification fails."""
        from webauthn.helpers.exceptions import InvalidAuthenticationResponse
        from webauthn.helpers import bytes_to_base64url

        # Setup passkey
        credential_id = bytes_to_base64url(b"test-credential-id")
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.passkey,
            data={
                "name": "Test Passkey",
                "credential_id": credential_id,
                "credential_public_key": bytes_to_base64url(b"test-public-key"),
                "sign_count": 0,
                "device_type": "single_device",
                "backed_up": False,
            },
        )
        db_session.add(identity)
        db_session.commit()

        # Mock verification to raise exception
        mock_verify.side_effect = InvalidAuthenticationResponse("Verification failed")

        jwt_challenge = jwt.encode(
            payload={"challenge": bytes_to_base64url(b"test-challenge")},
            key=test_config.auth.jwt_secret_key,
            algorithm=test_config.auth.jwt_algorithm,
        )

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            "/api/auth/passkey/verify",
            params={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
