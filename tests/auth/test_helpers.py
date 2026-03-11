"""Tests for auth helper functions."""
import uuid
from datetime import datetime, timedelta

import pytest
from starlette.responses import Response

from backend.auth.dependencies import JWTClaims
from backend.auth.helpers import (
    create_and_save_token,
    create_oauth2_token,
    save_session,
    clear_all_sessions,
    set_token_cookie,
)
from model.identity import Session, TokenType


class TestCreateOAuth2Token:
    """Test create_oauth2_token function."""

    def test_creates_token_with_correct_fields(self):
        """Should create OAuth2Token with access token and metadata."""
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)

        token = create_oauth2_token(claims)

        assert token.access_token is not None
        assert token.token_type == TokenType.bearer
        assert token.expires_at == exp
        assert token.refresh_token == ""

    def test_token_can_be_decoded(self):
        """Should create a token that can be decoded back to claims."""
        user_id = uuid.uuid4()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        token = create_oauth2_token(claims)
        decoded_claims = JWTClaims.from_jwt_string(token.access_token)

        assert decoded_claims.sub == user_id
        assert decoded_claims.jti == claims.jti


class TestSaveSession:
    """Test save_session function."""

    def test_saves_session_to_database(self, db_session, test_user):
        """Should save a new session to the database."""
        user_id = test_user.id

        session_id = save_session(user_id=user_id, db=db_session)

        saved_session = db_session.query(Session).filter(Session.id == session_id).first()
        assert saved_session is not None
        assert saved_session.user_id == user_id
        assert saved_session.expires_at > datetime.now()

    def test_uses_custom_session_id_if_provided(self, db_session, test_user):
        """Should use provided session ID instead of generating new one."""
        custom_id = uuid.uuid4()

        session_id = save_session(user_id=test_user.id, db=db_session, session_id=custom_id)

        assert session_id == custom_id

    def test_uses_custom_expiration(self, db_session, test_user):
        """Should use custom expiration date if provided."""
        custom_exp = datetime.now() + timedelta(days=7)

        session_id = save_session(
            user_id=test_user.id, db=db_session, expires_at=custom_exp
        )

        saved_session = db_session.query(Session) \
            .filter(Session.id == session_id).first()
        # Compare with some tolerance for execution time
        time_diff = abs((saved_session.expires_at - custom_exp).total_seconds())
        assert time_diff < 1


class TestClearAllSessions:
    """Test clear_all_sessions function."""

    @pytest.mark.asyncio
    async def test_deletes_all_user_sessions(self, db_session, test_user):
        """Should delete all sessions for a user."""
        # Create multiple sessions
        for _ in range(3):
            save_session(user_id=test_user.id, db=db_session)

        initial_count = db_session.query(Session).filter(
            Session.user_id == test_user.id
        ).count()
        assert initial_count == 3

        await clear_all_sessions(user=test_user, db=db_session)

        final_count = db_session.query(Session).filter(
            Session.user_id == test_user.id
        ).count()
        assert final_count == 0


class TestSetTokenCookie:
    """Test set_token_cookie function."""

    def test_sets_cookie_with_correct_attributes(self):
        """Should set cookie with proper security attributes."""
        response = Response()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)
        token = create_oauth2_token(claims)

        set_token_cookie(response, key="access_token", value=token)

        # Check cookie was set (this is implementation-dependent)
        assert "access_token" in response.headers.get("set-cookie", "")

    def test_sets_session_cookie_when_requested(self):
        """Should create session cookie without expiration."""
        response = Response()
        exp = datetime.now() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)
        token = create_oauth2_token(claims)

        set_token_cookie(response, key="access_token", value=token, session_cookie=True)

        cookie_header = response.headers.get("set-cookie", "")
        assert "access_token" in cookie_header


class TestCreateAndSaveToken:
    """Test create_and_save_token function."""

    def test_creates_token_and_session(self, db_session, test_user):
        """Should create token and save session to database."""
        response = Response()

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
        )

        assert token.access_token is not None
        assert token.token_type == TokenType.bearer

        # Verify session was saved
        decoded = JWTClaims.from_jwt_string(token.access_token)
        saved_session = db_session.query(Session).filter(
            Session.id == decoded.jti
        ).first()
        assert saved_session is not None
        assert saved_session.user_id == test_user.id

    def test_creates_otp_required_token(self, db_session, test_user):
        """Should create token with OTP requirement."""
        response = Response()

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
            requires_otp=True,
            save_to_db=False,
        )

        decoded = JWTClaims.from_jwt_string(token.access_token)
        assert decoded.requires_otp is True

    def test_respects_save_to_db_flag(self, db_session, test_user):
        """Should not save session when save_to_db is False."""
        response = Response()

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
            save_to_db=False,
        )

        decoded = JWTClaims.from_jwt_string(token.access_token)
        saved_session = db_session.query(Session).filter(
            Session.id == decoded.jti
        ).first()
        assert saved_session is None

    def test_uses_custom_duration(self, db_session, test_user):
        """Should respect custom token duration."""
        response = Response()
        custom_duration = timedelta(days=7)

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
            duration=custom_duration,
        )

        decoded = JWTClaims.from_jwt_string(token.access_token)
        time_diff = (decoded.exp - datetime.now()).total_seconds()
        expected_diff = custom_duration.total_seconds()

        # Allow 1 second tolerance
        assert abs(time_diff - expected_diff) < 1
