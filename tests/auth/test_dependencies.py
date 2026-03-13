import uuid
from datetime import timedelta

import pytest
from starlette.requests import Request

from backend.auth import active_user, helpers
from backend.auth.helpers import AuthErrorCode, AuthException, JWTClaims, jwt_claims, session, sudo_token
from utils.datetime import utcnow


class TestJWTClaims:
    def test_to_jwt_string(self):
        user_id = uuid.uuid4()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        jwt_string = claims.to_jwt_string()

        assert isinstance(jwt_string, str)
        assert len(jwt_string) > 0

    def test_from_jwt_string(self):
        user_id = uuid.uuid4()
        exp = utcnow() + timedelta(hours=1)
        original_claims = JWTClaims(sub=user_id, exp=exp)
        jwt_string = original_claims.to_jwt_string()

        decoded_claims = JWTClaims.from_jwt_string(jwt_string)

        assert decoded_claims == original_claims

    def test_expired_token(self):
        user_id = uuid.uuid4()
        exp = utcnow() - timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)
        jwt_string = claims.to_jwt_string()

        with pytest.raises(AuthException) as exc_info:
            JWTClaims.from_jwt_string(jwt_string)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN

    def test_invalid_token(self):
        with pytest.raises(AuthException) as exc_info:
            JWTClaims.from_jwt_string("invalid.token.here")

        assert exc_info.value.err_code == AuthErrorCode.BAD_TOKEN

    def test_default_values(self):
        user_id = uuid.uuid4()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        assert claims.requires_otp is False
        assert claims.sudo is False
        assert isinstance(claims.jti, uuid.UUID)


class TestJwtClaimsDependency:
    def test_valid_token(self):
        user_id = uuid.uuid4()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)
        token = claims.to_jwt_string()

        result = jwt_claims(token)

        assert result.sub == user_id

    def test_invalid_token(self):
        with pytest.raises(AuthException):
            jwt_claims("invalid-token")


class TestActiveUserDependency:
    def test_valid_session(self, db_session, test_user, test_session):
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        user = active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        assert user.id == test_user.id

    def test_when_otp_required(self, db_session, test_user, test_session):
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
            requires_otp=True,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.OTP_REQUIRED

    def test_when_user_deleted(self, db_session, test_user, test_session):
        test_user.deleted_at = utcnow()
        db_session.commit()

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.USER_DELETED

    def test_when_email_not_verified(self, db_session, test_user, test_session):
        test_user.email_verified = False
        db_session.commit()

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EMAIL_NOT_VERIFIED

    def test_when_session_not_found(self, db_session, test_user):
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),  # Non-existent session
            exp=utcnow() + timedelta(hours=1),
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN

    def test_updates_last_active(self, db_session, test_user, test_session):
        original_time = test_session.last_used_at
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        active_user(raw_user=test_user, jwt_claims=claims, db=db_session)

        db_session.refresh(test_session)
        assert test_session.last_used_at > original_time


class TestGetSessionDependency:
    def test_when_exists(self, db_session, test_user, test_session):
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        session = helpers.session(jwt_claims=claims, db=db_session)

        assert session.id == test_session.id

    def test_when_not_found(self, db_session, test_user):
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=utcnow() + timedelta(hours=1),
        )

        with pytest.raises(AuthException) as exc_info:
            session(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN


class TestSudoTokenDependency:
    def test_sudo_token(self, db_session, test_user, test_session):
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=utcnow() + timedelta(minutes=15),
            sudo=True,
        )

        result = sudo_token(jwt_claims=claims, db=db_session)

        assert result.sudo is True

    def test_when_not_sudo(self, db_session, test_user, test_session):
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=utcnow() + timedelta(hours=1),
            sudo=False,
        )

        with pytest.raises(AuthException) as exc_info:
            sudo_token(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.BAD_TOKEN

    def test_when_session_not_found(self, db_session, test_user):
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=utcnow() + timedelta(minutes=15),
            sudo=True,
        )

        with pytest.raises(AuthException) as exc_info:
            sudo_token(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN
