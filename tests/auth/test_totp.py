import jwt
from fastapi import status
from jinja2.utils import url_quote
from sqlalchemy import select

from backend.auth.totp import create_totp_helper
from config import cfg
from model.identity import IdentityProvider, Issuer


class TestTOTP:
    def test_generate_totp(self, client, db_session, test_user, auth_token):
        response = client.post(
            "/api/auth/totp/create",
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
            "/api/auth/totp",
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
            "/api/auth/totp",
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": "000000", "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False

    def test_verify_totp(self, client, db_session, test_user, test_session):
        from backend.auth.dependencies import JWTClaims
        from datetime import datetime, timedelta

        # Setup TOTP for user
        jwt_totp, totp = create_totp_helper(test_user)
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": totp.secret},
        )
        db_session.add(identity)
        db_session.commit()

        current_otp = totp.now()
        prev_otp = totp.at(datetime.now() - timedelta(seconds=30))

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now() + timedelta(minutes=5),
            requires_otp=True,
        )
        token = claims.to_jwt_string()

        res1 = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": current_otp},
        )

        res2 = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": prev_otp},
        )

        res3 = client.post(
            "/api/auth/totp/verify",
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": "000000"},
        )

        assert res1.status_code == status.HTTP_200_OK
        assert res2.status_code == status.HTTP_200_OK
        assert res3.status_code == status.HTTP_401_UNAUTHORIZED

    def test_verify_totp_when_not_setup(self, client, db_session, test_user, test_session):
        from backend.auth.dependencies import JWTClaims
        from datetime import datetime, timedelta

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now() + timedelta(minutes=5),
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

        response = client.delete(
            "/api/auth/totp",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify TOTP was deleted
        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == test_user.id)
        )
        assert identity is None

    def test_delete_totp_when_not_setup(self, client, auth_token):
        response = client.delete(
            "/api/auth/totp",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
