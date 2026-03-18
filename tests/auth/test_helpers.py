import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from starlette.responses import Response

from backend.auth.helpers import (
    create_and_save_token,
    create_oauth2_token,
    create_or_update_session,
    clear_all_sessions,
    set_token_cookie, JWTClaims,
)
from model.identity import Session, TokenType
from utils.datetime import utcnow


class TestCreateOAuth2Token:
    def test_fields(self):
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)

        token = create_oauth2_token(claims)

        assert token.access_token is not None
        assert token.token_type == TokenType.bearer
        assert token.expires_at == exp
        assert token.refresh_token == ""

    def test_decodable(self):
        user_id = uuid.uuid4()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=user_id, exp=exp)

        token = create_oauth2_token(claims)
        decoded_claims = JWTClaims.from_jwt_string(token.access_token)

        assert decoded_claims.sub == user_id
        assert decoded_claims.jti == claims.jti


class TestSaveSession:
    def test_saves(self, db_session, test_user):
        user_id = test_user.id

        session_id = create_or_update_session(db=db_session, user_id=user_id)

        saved_session = db_session.get_one(Session, session_id)
        assert saved_session.user_id == user_id
        assert saved_session.expires_at > utcnow()

    def test_custom_expiration(self, db_session, test_user):
        session_id = create_or_update_session(db=db_session, user_id=test_user.id, expires_delta=timedelta(days=7))

        saved_session = db_session.query(Session) \
            .filter(Session.id == session_id).first()

        time_diff = abs((
                                saved_session.expires_at
                                - (utcnow() + timedelta(days=7))
                        ).total_seconds())
        assert time_diff < 1

    def test_updates_existing(self, db_session, test_user):
        delta = timedelta(days=30)
        session_id = create_or_update_session(db_session,
                                              user_id=test_user.id,
                                              expires_delta=timedelta(days=1))

        create_or_update_session(db_session,
                                 user_id=test_user.id,
                                 session_id=session_id,
                                 expires_delta=delta)
        session = db_session.scalar(select(Session).where(Session.user_id == test_user.id))

        assert session is not None
        assert session.id == session_id
        assert session.expires_at - utcnow() - delta < timedelta(seconds=1)
        assert session.last_used_at - utcnow() < timedelta(seconds=1)

    def test_updates_last_used_on_upsert(self, db_session, test_user):
        session_id = create_or_update_session(db=db_session, user_id=test_user.id)
        db_session.expire_all()
        first_used = db_session.query(Session).filter(Session.id == session_id).first().last_used_at

        create_or_update_session(db=db_session, user_id=test_user.id, session_id=session_id)
        db_session.expire_all()
        second_used = db_session.query(Session).filter(Session.id == session_id).first().last_used_at

        assert second_used >= first_used


class TestClearAllSessions:
    @pytest.mark.asyncio
    async def test_deletes_all(self, db_session, test_user):
        # Create multiple sessions
        for _ in range(3):
            create_or_update_session(db=db_session, user_id=test_user.id)

        initial_count = db_session.query(Session).filter(
            Session.user_id == test_user.id
        ).count()
        assert initial_count == 3

        clear_all_sessions(user=test_user, db=db_session)

        final_count = db_session.query(Session).filter(
            Session.user_id == test_user.id
        ).count()
        assert final_count == 0


class TestSetTokenCookie:
    def test_attributes(self):
        response = Response()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)
        token = create_oauth2_token(claims)

        set_token_cookie(response, key="access_token", value=token)

        # Check cookie was set (this is implementation-dependent)
        assert "access_token" in response.headers.get("set-cookie", "")

    def test_session_cookie(self):
        response = Response()
        exp = utcnow() + timedelta(hours=1)
        claims = JWTClaims(sub=uuid.uuid4(), exp=exp)
        token = create_oauth2_token(claims)

        set_token_cookie(response, key="access_token", value=token, session_cookie=True)

        cookie_header = response.headers.get("set-cookie", "")
        assert "access_token" in cookie_header


class TestCreateAndSaveToken:
    def test_creates_token_and_session(self, db_session, test_user):
        response = Response()

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
        )

        assert token.access_token is not None
        assert token.token_type == TokenType.bearer

        decoded = JWTClaims.from_jwt_string(token.access_token)
        saved_session = db_session.get_one(Session, decoded.jti)

        assert saved_session.user_id == test_user.id

    def test_otp_required_token(self, db_session, test_user):
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

    def test_save_to_db_flag(self, db_session, test_user):
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

    def test_custom_duration(self, db_session, test_user):
        response = Response()
        custom_duration = timedelta(days=7)

        token = create_and_save_token(
            response=response,
            db=db_session,
            user_id=test_user.id,
            duration=custom_duration,
        )

        decoded = JWTClaims.from_jwt_string(token.access_token)
        time_diff = (decoded.exp - utcnow()).total_seconds()
        expected_diff = custom_duration.total_seconds()

        # Allow 1 second tolerance
        assert abs(time_diff - expected_diff) < 1
