from datetime import timedelta

from fastapi import status
from jinja2.utils import url_quote
from sqlalchemy import select

from backend.auth.model import IdentityProvider, Issuer
from backend.auth.totp import create_totp_helper, TotpSetupClaims, delete_totp, register_totp, verify_totp, \
    generate_totp
from backend.auth.utils.jwt import create_token, verify_token
from backend.auth.utils.session import SessionClaims


class TestTOTP:
    def test_generate(self, client, path, db_session, test_user, auth_token):
        response = client.post(
            path(generate_totp),
            headers={"Authorization": f"bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        uri = data["uri"]
        jwt_totp = data["jwt_totp"]

        jwt_claims = verify_token(jwt_totp, return_model=TotpSetupClaims)
        assert jwt_claims.sub == test_user.id
        totp_secret = jwt_claims.totp_secret

        assert uri.startswith("otpauth://totp/")
        assert f"secret={totp_secret}" in data["uri"]
        url_escaped = url_quote(test_user.primary_email)
        assert url_escaped in uri

    def test_register_with_valid_otp(self, client, path, db_session, test_user, sudo_auth_token):
        jwt_totp, totp = create_totp_helper(test_user.id)
        current_otp = totp.now()

        response = client.post(
            path(register_totp),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": current_otp, "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify TOTP identity was created
        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == test_user.id)
        )
        assert identity is not None
        assert identity.data["secret"] == totp.secret

    def test_register_with_invalid_otp(self, client, path, db_session, test_user, sudo_auth_token):
        jwt_totp, totp = create_totp_helper(test_user.id)

        response = client.post(
            path(register_totp),
            headers={"Authorization": f"Bearer {sudo_auth_token}"},
            data={"otp": "000000", "jwt_totp_claims": jwt_totp},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_verify(self, client, path, db_session, test_user, test_session):
        # Setup TOTP for user
        jwt_totp, totp = create_totp_helper(test_user.id)
        identity = IdentityProvider(
            user_id=test_user.id,
            issuer=Issuer.totp,
            data={"secret": totp.secret},
        )
        db_session.add(identity)
        db_session.commit()

        current_otp = totp.now()
        from datetime import timezone, datetime
        prev_otp = totp.at(datetime.now(timezone.utc) - timedelta(seconds=30))

        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            requires_otp=True,
        )
        token = create_token(claims)

        res1 = client.post(
            path(verify_totp),
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": current_otp},
        )

        res2 = client.post(
            path(verify_totp),
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": prev_otp},
        )

        res3 = client.post(
            path(verify_totp),
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": "000000"},
        )

        assert res1.status_code == status.HTTP_200_OK
        assert res2.status_code == status.HTTP_200_OK
        assert res3.status_code == status.HTTP_401_UNAUTHORIZED

    def test_verify_when_not_setup(self, client, path, db_session, test_user, test_session):
        from backend.auth.utils.session import SessionClaims
        from datetime import timedelta, timezone, datetime

        claims = SessionClaims(
            sub=test_user.id,
            jti=test_session.jti,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
            requires_otp=True,
        )
        token = create_token(claims)

        response = client.post(
            path(verify_totp),
            headers={"Authorization": f"Bearer {token}"},
            data={"totp": "123456"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_removes_identity(self, client, path, db_session, test_user, auth_token):
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
            path(delete_totp),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify TOTP was deleted
        identity = db_session.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == test_user.id)
        )
        assert identity is None

    def test_delete_when_not_setup(self, client, path, auth_token):
        response = client.delete(
            path(delete_totp),
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
