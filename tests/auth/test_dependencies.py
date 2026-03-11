"""Tests for auth dependencies and middleware."""
import uuid
from datetime import datetime, timedelta

import pytest

from backend.auth.dependencies import (
    JWTClaims,
    jwt_claims,
    active_user,
    session,
    sudo_token,
    AuthException,
    AuthErrorCode,
)


class TestJWTClaims:
    """Test JWTClaims model."""

    def test_to_jwt_string_creates_valid_token(self):
        """Should encode claims to JWT string."""
        user_id = uuid.uuid4()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        jwt_string = claims.to_jwt_string()

        assert isinstance(jwt_string, str)
        assert len(jwt_string) > 0

    def test_from_jwt_string_decodes_valid_token(self):
        """Should decode JWT string to claims."""
        user_id = uuid.uuid4()
        exp = datetime.now() + timedelta(hours=1)
        original_claims = JWTClaims(sub=user_id, exp=exp)
        jwt_string = original_claims.to_jwt_string()

        decoded_claims = JWTClaims.from_jwt_string(jwt_string)

        assert decoded_claims == original_claims

    def test_from_jwt_string_raises_on_expired_token(self):
        """Should raise AuthException for expired tokens."""
        user_id = uuid.uuid4()
        exp = datetime.now() - timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)
        jwt_string = claims.to_jwt_string()

        with pytest.raises(AuthException) as exc_info:
            JWTClaims.from_jwt_string(jwt_string)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN

    def test_from_jwt_string_raises_on_invalid_token(self):
        """Should raise AuthException for malformed tokens."""
        with pytest.raises(AuthException) as exc_info:
            JWTClaims.from_jwt_string("invalid.token.here")

        assert exc_info.value.err_code == AuthErrorCode.BAD_TOKEN

    def test_default_values(self):
        """Should set default values correctly."""
        user_id = uuid.uuid4()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        assert claims.requires_otp is False
        assert claims.sudo is False
        assert isinstance(claims.jti, uuid.UUID)


class TestJwtClaimsDependency:
    """Test jwt_claims dependency function."""

    def test_returns_claims_for_valid_token(self):
        """Should extract and return JWT claims from token."""
        user_id = uuid.uuid4()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)
        token = claims.to_jwt_string()

        result = jwt_claims(token)

        assert result.sub == user_id

    def test_raises_on_invalid_token(self):
        """Should raise exception for invalid token."""
        with pytest.raises(AuthException):
            jwt_claims("invalid-token")


class TestActiveUserDependency:
    """Test active_user dependency function."""

    def test_returns_user_for_valid_session(self, db_session, test_user, test_session):
        """Should return user when all checks pass."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        user = active_user(user=test_user, jwt_claims=claims, db=db_session)

        assert user.id == test_user.id

    def test_raises_when_otp_required(self, db_session, test_user, test_session):
        """Should raise exception when OTP is required."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
            requires_otp=True,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.OTP_REQUIRED

    def test_raises_when_user_deleted(self, db_session, test_user, test_session):
        """Should raise exception when user is deleted."""
        test_user.deleted_at = datetime.now()
        db_session.commit()

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.USER_DELETED

    def test_raises_when_email_not_verified(self, db_session, test_user, test_session):
        """Should raise exception when email not verified."""
        test_user.email_verified = False
        db_session.commit()

        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EMAIL_NOT_VERIFIED

    def test_raises_when_session_not_found(self, db_session, test_user):
        """Should raise exception when session doesn't exist."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),  # Non-existent session
            exp=datetime.now() + timedelta(hours=1),
        )

        with pytest.raises(AuthException) as exc_info:
            active_user(user=test_user, jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN

    def test_updates_session_last_active(self, db_session, test_user, test_session):
        """Should update session last_active_at timestamp."""
        original_time = test_session.last_used_at
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        active_user(user=test_user, jwt_claims=claims, db=db_session)

        db_session.refresh(test_session)
        assert test_session.last_used_at > original_time


class TestGetSessionDependency:
    """Test get_session dependency function."""

    def test_returns_session_when_exists(self, db_session, test_user, test_session):
        """Should return session for valid claims."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=test_session.expires_at,
        )

        session = session(jwt_claims=claims, db=db_session)

        assert session.id == test_session.id

    def test_raises_when_session_not_found(self, db_session, test_user):
        """Should raise exception when session doesn't exist."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=datetime.now() + timedelta(hours=1),
        )

        with pytest.raises(AuthException) as exc_info:
            session(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN


class TestSudoTokenDependency:
    """Test sudo_token dependency function."""

    def test_returns_claims_for_sudo_token(self, db_session, test_user, test_session):
        """Should return claims when sudo flag is true."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now() + timedelta(minutes=15),
            sudo=True,
        )

        result = sudo_token(jwt_claims=claims, db=db_session)

        assert result.sudo is True

    def test_raises_when_not_sudo_token(self, db_session, test_user, test_session):
        """Should raise exception when sudo flag is false."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=test_session.id,
            exp=datetime.now() + timedelta(hours=1),
            sudo=False,
        )

        with pytest.raises(AuthException) as exc_info:
            sudo_token(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.BAD_TOKEN

    def test_raises_when_session_not_found(self, db_session, test_user):
        """Should raise exception when session doesn't exist."""
        claims = JWTClaims(
            sub=test_user.id,
            jti=uuid.uuid4(),
            exp=datetime.now() + timedelta(minutes=15),
            sudo=True,
        )

        with pytest.raises(AuthException) as exc_info:
            sudo_token(jwt_claims=claims, db=db_session)

        assert exc_info.value.err_code == AuthErrorCode.EXPIRED_TOKEN


class TestSessionCookieToHeaderMiddleware:
    """Test SessionCookieToHeaderMiddleware."""

    @staticmethod
    def _create_test_endpoint(client, endpoint_path: str, response_fields: dict):
        from fastapi import Request

        @client.app.get(endpoint_path)
        def test_endpoint(request: Request):
            return {
                field: extractor(request)
                for field, extractor in response_fields.items()
            }

    @staticmethod
    def _make_request(client, path: str, cookies: dict = None, headers: dict = None):
        response = client.get(path, cookies=cookies or {}, headers=headers or {})
        return response.status_code, response.json()

    def test_moves_access_token_cookie_to_header(self, client, test_user, test_session, auth_token):
        endpoint = "/test-middleware-auth"

        self._create_test_endpoint(client, endpoint, {
            "auth_header": lambda req: req.headers.get("Authorization"),
            "has_cookie": lambda req: "access_token" in req.cookies
        })

        status, data = self._make_request(
            client, endpoint,
            cookies={"access_token": auth_token}
        )

        assert status == 200
        assert data["auth_header"] == f"Bearer {auth_token}"
        assert data["has_cookie"] is True

    def test_prefers_sudo_token_over_access_token(self, client, test_user, test_session, auth_token, sudo_auth_token):
        """Should use sudo_token if both cookies exist."""
        endpoint = "/test-middleware-sudo"

        self._create_test_endpoint(client, endpoint, {
            "auth_header": lambda req: req.headers.get("Authorization")
        })

        status, data = self._make_request(
            client, endpoint,
            cookies={"access_token": auth_token, "sudo_token": sudo_auth_token}
        )

        assert status == 200
        assert data["auth_header"] == f"Bearer {sudo_auth_token}"

    def test_skips_if_authorization_header_exists(self, client, test_user, test_session, auth_token):
        endpoint = "/test-middleware-skip"
        existing_token = "existing-header-token"

        self._create_test_endpoint(client, endpoint, {
            "auth_header": lambda req: req.headers.get("Authorization")
        })

        status, data = self._make_request(
            client, endpoint,
            headers={"Authorization": f"Bearer {existing_token}"},
            cookies={"access_token": auth_token}
        )

        assert status == 200
        assert data["auth_header"] == f"Bearer {existing_token}"

    def test_no_cookie_no_modification(self, client):
        endpoint = "/test-middleware-none"

        self._create_test_endpoint(client, endpoint, {
            "auth_header": lambda req: req.headers.get("Authorization"),
            "has_access_cookie": lambda req: "access_token" in req.cookies,
            "has_sudo_cookie": lambda req: "sudo_token" in req.cookies
        })

        status, data = self._make_request(client, endpoint)

        assert status == 200
        assert data["auth_header"] is None
        assert data["has_access_cookie"] is False
        assert data["has_sudo_cookie"] is False
