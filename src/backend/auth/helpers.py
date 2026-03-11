import uuid
from datetime import timedelta, datetime

from sqlalchemy import insert, delete
from starlette.responses import Response

from model import DatabaseDep
from model.cookie import CookieOptions
from model.identity import TokenType, Session
from .dependencies import JWTClaims, OAuth2Token, UserDep


def create_and_save_token(
        response: Response,
        db: DatabaseDep,

        user_id: uuid.UUID,
        duration=timedelta(days=30),
        requires_otp=False,

        cookie_key="access_token",
        session_cookie=False,

        save_to_db=True,
        set_cookie=True,
) -> OAuth2Token:
    claims = JWTClaims(
        sub=user_id,
        exp=datetime.now() + duration,
        requires_otp=requires_otp
    )

    token = create_oauth2_token(claims)

    if save_to_db:
        save_session(user_id=user_id,
                     db=db,
                     session_id=claims.jti,
                     expires_at=claims.exp)

    if set_cookie:
        set_token_cookie(response,
                         key=cookie_key,
                         value=token,
                         session_cookie=session_cookie)

    return token


def create_oauth2_token(claims: JWTClaims) -> OAuth2Token:
    access_token = claims.to_jwt_string()

    return OAuth2Token(
        access_token=access_token,
        refresh_token="",
        token_type=TokenType.bearer,
        expires_at=claims.exp,
    )


def save_session(
        user_id: uuid.UUID,
        db: DatabaseDep,
        session_id: uuid.UUID = None,
        expires_delta=timedelta(days=30),
        expires_at: datetime = None,
) -> uuid.UUID:
    exp = expires_at or (datetime.now() + expires_delta)
    session_id = session_id or uuid.uuid4()
    db.execute(
        insert(Session)
        .values(id=session_id,
                user_id=user_id,
                expires_at=exp)
    )
    db.commit()

    return session_id


async def clear_all_sessions(user: UserDep, db: DatabaseDep):
    db.execute(
        delete(Session)
        .where(Session.user_id == user.id)
    )


def set_token_cookie(
        response: Response,
        key: str,
        value: OAuth2Token,
        session_cookie: bool = False,
):
    # TODO: move to config
    options = CookieOptions(
        path="/",
        secure=False,
        httponly=True,
        samesite="lax",
    )
    max_age = value.expires_at - datetime.now()
    options = options.model_copy(
        update={
            "max_age": int(max_age.total_seconds()),
            "expires": None if session_cookie else value.expires_at,
        }
    )

    response.set_cookie(
        key=key,
        value=value.access_token,
        **options.model_dump()
    )
