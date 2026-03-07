import pyotp
import jwt
from fastapi import status
from jinja2.utils import url_quote
from sqlalchemy import select

from backend.auth.totp import create_totp_helper
from model.identity import IdentityProvider, Issuer
from config import cfg


class TestTOTP:
    def test_generate_totp(self, client, db_session, test_user, auth_token):
        response = client.post(
            "/api/auth/totp/generate",
            headers={"Authorization": f"bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        uri = data["uri"]
        jwt_totp = data["jwt_totp"]

        jwt_claims = jwt.decode(
            jwt_totp,
            key=cfg().auth.jwt_secret_key,
            algorithms=[cfg().auth.jwt_algorithm],
        )
        assert jwt_claims["sub"] == str(test_user.id)
        totp_secret = jwt_claims["totp_secret"]

        assert uri.startswith("otpauth://totp/")
        assert f"secret={totp_secret}" in data["uri"]
        url_escaped = url_quote(test_user.primary_email)
        assert url_escaped in uri

    def test_register_totp_with_valid_otp(self, client, db_session, test_user, sudo_auth_token):
        from src.backend.auth.totp import create_totp_helper
        jwt_totp, totp = create_totp_helper(test_user)
        current_otp = totp.now()

        response = client.post(
            "/api/auth/totp/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": current_otp, "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

        # Verify TOTP identity was created
        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == test_user.id)
        )
        assert identity is not None
        assert identity.data["secret"] == totp.secret

    def test_register_totp_with_invalid_otp(self, client, db_session, test_user, sudo_auth_token):
        jwt_totp, totp = create_totp_helper(test_user)

        response = client.post(
            "/api/auth/totp/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": "000000", "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False

    def test_register_totp_without_sudo_token(self, client, db_session, test_user, auth_token):
        totp_secret = pyotp.random_base32()
        totp = pyotp.TOTP(totp_secret)
        current_otp = totp.now()

        jwt_totp = jwt.encode(
            payload={"sub": str(test_user.id), "totp_secret": totp_secret},
            key=cfg().auth.jwt_secret_key,
            algorithm=cfg().auth.jwt_algorithm,
        )

        response = client.post(
            "/api/auth/totp/register",
            headers={"Authorization": f"Bearer {auth_token}"},
            params={"otp": current_otp, "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_totp_when_already_registered(self, client, db_session, test_user, sudo_auth_token):
        existing_identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": "existing-secret"},
        )
        db_session.add(existing_identity)
        db_session.commit()

        jwt_totp, totp = create_totp_helper(test_user)
        current_otp = totp.now()

        response = client.post(
            "/api/auth/totp/register",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": current_otp, "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_verify_totp_with_valid_code(
            self, client, db_session, test_user, test_session
    ):
        """Should verify valid TOTP and create session token."""
        from backend.auth.dependencies import JWTClaims
        from datetime import datetime, timezone, timedelta

        # Setup TOTP for user
        totp_secret = pyotp.random_base32()
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": totp_secret},
        )
        db_session.add(identity)
        db_session.commit()

        # Generate current OTP
        totp = pyotp.TOTP(totp_secret)
        current_otp = totp.now()

        # Create token requiring OTP
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            requires_otp=True,
        )
        token = claims.to_jwt_string()

        response = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": current_otp},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data

    def test_verify_totp_with_invalid_code(
            self, client, db_session, test_user, test_session
    ):
        """Should reject invalid TOTP code."""
        from backend.auth.dependencies import JWTClaims
        from datetime import datetime, timezone, timedelta

        # Setup TOTP for user
        totp_secret = pyotp.random_base32()
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": totp_secret},
        )
        db_session.add(identity)
        db_session.commit()

        # Create token requiring OTP
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            requires_otp=True,
        )
        token = claims.to_jwt_string()

        response = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": "000000"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_verify_totp_when_not_setup(self, client, db_session, test_user, test_session):
        """Should reject verification when TOTP not set up."""
        from backend.auth.dependencies import JWTClaims
        from datetime import datetime, timezone, timedelta

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            requires_otp=True,
        )
        token = claims.to_jwt_string()

        response = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": "123456"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_totp_removes_identity(self, client, db_session, test_user, auth_token):
        """Should remove TOTP identity provider."""
        # Setup TOTP for user
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": "test-secret"},
        )
        db_session.add(identity)
        db_session.commit()

        response = client.post(
            "/api/auth/totp/delete",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify TOTP was deleted
        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == test_user.id)
        )
        assert identity is None

    def test_delete_totp_when_not_setup(self, client, db_session, test_user, auth_token):
        """Should handle deletion gracefully when TOTP not setup."""
        response = client.post(
            "/api/auth/totp/delete",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
