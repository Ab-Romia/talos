import json
from datetime import timedelta, datetime, timezone
from unittest.mock import Mock, patch

from fastapi import status

from backend.auth.model import IdentityProvider, Issuer
from backend.auth.utils.jwt import create_token, verify_token
from backend.auth.webauthn import WebAuthnChallengeClaims, generate_passkey_new, verify_passkey, register_passkey, \
    generate_passkey_for_auth


class TestGeneratePasskey:
    def test_for_registration(self, client, path, db_session, test_user, sudo_auth_token):
        response = client.post(
            path(generate_passkey_new),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "options" in data
        assert "jwt_challenge" in data

        # Verify JWT challenge contains user info
        claims = verify_token(data["jwt_challenge"], return_model=WebAuthnChallengeClaims)
        assert claims.sub is not None
        assert claims.challenge is not None
        assert test_user.id == claims.sub

    def test_for_authentication(self, client, path, db_session):
        response = client.post(path(generate_passkey_for_auth))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "options" in data
        assert "jwt_challenge" in data

        # Verify JWT challenge does not contain user info
        claims = verify_token(data["jwt_challenge"], return_model=WebAuthnChallengeClaims)
        assert claims.sub is None
        assert claims.challenge is not None


class TestRegisterPasskey:
    @patch("backend.auth.webauthn.webauthn.verify_registration_response")
    def test_register(self, mock_verify, client, path, db_session, test_user, sudo_auth_token):
        from webauthn.helpers import bytes_to_base64url

        # Mock verification response
        mock_verified = Mock()
        mock_verified.credential_id = b"test-credential-id"
        mock_verified.credential_public_key = b"test-public-key"
        mock_verified.sign_count = 0
        mock_verified.credential_device_type = Mock(value="single_device")
        mock_verified.credential_backed_up = False
        mock_verify.return_value = mock_verified

        challenge = b"test-challenge"
        jwt_challenge = create_token(WebAuthnChallengeClaims(
            sub=test_user.id,
            challenge=bytes_to_base64url(challenge),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({"id": "test-credential-id", "response": {}})

        response = client.post(
            path(register_passkey),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
                "name": "My Passkey",
            },
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify passkey identity was created
        identity = db_session.query(IdentityProvider).filter(
            IdentityProvider.user_id == test_user.id,
            IdentityProvider.issuer == Issuer.passkey,
        ).first()
        assert identity is not None
        assert identity.data["name"] == "My Passkey"

    def test_with_invalid_challenge(self, client, path, db_session, test_user, sudo_auth_token):
        response = client.post(
            path(register_passkey),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={
                "jwt_challenge": "invalid-jwt",
                "credential": "{}",
                "name": "Test",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("backend.auth.webauthn.webauthn.verify_registration_response")
    def test_with_verification_failure(self, mock_verify, client, path, db_session, test_user,
                                       sudo_auth_token):
        from webauthn.helpers.exceptions import InvalidRegistrationResponse
        from webauthn.helpers import bytes_to_base64url

        # Mock verification to raise exception
        mock_verify.side_effect = InvalidRegistrationResponse("Verification failed")

        jwt_challenge = create_token(WebAuthnChallengeClaims(
            sub=test_user.id,
            challenge=bytes_to_base64url(b"test-challenge"),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({"id": "test-credential-id", "response": {}})

        response = client.post(
            path(register_passkey),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
                "name": "Test",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestVerifyPasskey:
    @patch("backend.auth.webauthn.webauthn.verify_authentication_response")
    def test_with_valid_credential(self, mock_verify, client, path, db_session, test_user):
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

        jwt_challenge = create_token(WebAuthnChallengeClaims(
            challenge=bytes_to_base64url(b"test-challenge"),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            path(verify_passkey),
            data={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_200_OK

    def test_with_invalid_challenge(
            self, client, path, db_session
    ):
        response = client.post(
            path(verify_passkey),
            data={
                "jwt_challenge": "invalid-jwt",
                "credential": "{}",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_with_nonexistent_credential(self, client, path, db_session):
        from webauthn.helpers import bytes_to_base64url

        jwt_challenge = create_token(WebAuthnChallengeClaims(
            challenge=bytes_to_base64url(b"test-challenge"),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({
            "id": "nonexistent-id",
            "rawId": "nonexistent-id",
            "response": {},
        })

        response = client.post(
            path(verify_passkey),
            data={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("backend.auth.webauthn.webauthn.verify_authentication_response")
    def test_updates_sign_count(self, mock_verify, client, path, db_session, test_user):
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

        mock_verified = Mock()
        mock_verified.new_sign_count = 6
        mock_verify.return_value = mock_verified

        jwt_challenge = create_token(WebAuthnChallengeClaims(
            challenge=bytes_to_base64url(b"test-challenge"),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            path(verify_passkey),
            data={
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
    def test_with_verification_failure(self, mock_verify, client, path, db_session, test_user):
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

        jwt_challenge = create_token(WebAuthnChallengeClaims(
            challenge=bytes_to_base64url(b"test-challenge"),
            exp=datetime.now(timezone.utc) + timedelta(minutes=5)
        ))

        credential = json.dumps({
            "id": credential_id,
            "rawId": credential_id,
            "response": {},
        })

        response = client.post(
            path(verify_passkey),
            data={
                "jwt_challenge": jwt_challenge,
                "credential": credential,
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
