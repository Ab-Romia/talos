import uuid
from datetime import timedelta, datetime
from enum import Enum as PyEnum
from typing import Annotated

import jwt
from fastapi import HTTPException, Depends
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, func
from sqlalchemy.sql.operators import add
from starlette import status
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse

from config import cfg
from model import DatabaseDep
from model.cookie import CookieOptions
from model.identity import TokenType, Session, User
from utils.datetime import utcnow
from utils.optional_dep import optional_dep


# TODO:
#  ✅ cookies,
#  refresh tokens,
#  ✅ sessions,
#  ✅ identity providers other than password
#  ✅ password reset,
#  forgot password,
#  email verification,
#  ✅ logout,
#  multiple account support
#  session management
#   - view active sessions
#  ✅ - revoke sessions
#  2FA (TOTP, WebAuthn, etc.)
#  ✅* sudo mode (re-auth for sensitive actions)
#  anonymous sessions
#  remember me functionality
#  device recognition (e.g. for risk-based authentication)
#  exception handling
#  timezone
#  use starlette middleware session
#  prevent re-signin, and invalidate prev session on resignin


class OAuth2Token(BaseModel):
    # name: str = Field(..., max_length=40)
    token_type: TokenType
    access_token: str = Field(..., max_length=512)
    refresh_token: str = Field(..., max_length=512)
    requires_otp: bool = False
    expires_at: datetime


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
    params = {}

    if save_to_db:
        session_id = create_or_update_session(db=db, user_id=user_id, expires_delta=duration)
        params = {"jti": session_id}

    claims = JWTClaims(
        sub=user_id,
        exp=utcnow() + duration,
        requires_otp=requires_otp,
        **params,
    )

    token = create_oauth2_token(claims)

    if set_cookie:
        set_token_cookie(response,
                         key=cookie_key,
                         value=token,
                         session_cookie=session_cookie)

    return token


class JWTClaims(BaseModel):
    sub: uuid.UUID
    jti: uuid.UUID = Field(default_factory=uuid.uuid4)
    exp: datetime
    requires_otp: bool = False
    sudo: bool = False

    @field_validator("exp", mode="before")
    @classmethod
    def transform(cls, delta) -> datetime:
        if isinstance(delta, timedelta):
            return utcnow() + delta
        return delta

    @classmethod
    def from_jwt_string(cls, claims_str: str):
        # TODO: get algorithm from header
        try:
            claims_dict = jwt.decode(
                jwt=claims_str,
                key=cfg().auth.jwt_secret_key,
                algorithms=[cfg().auth.jwt_algorithm],
                options=cfg().auth.jwt_options or None
            )
            return cls.model_validate(claims_dict)

        except jwt.ExpiredSignatureError as e:
            raise AuthException(detail="Token expired", err_code=AuthErrorCode.EXPIRED_TOKEN) from e
        except jwt.PyJWTError as e:
            raise AuthException(detail="Invalid token", err_code=AuthErrorCode.BAD_TOKEN) from e

    def to_jwt_string(self) -> str:
        payload = self.model_dump(mode="json")
        payload["exp"] = self.exp.timestamp()
        return jwt.encode(
            payload,
            key=cfg().auth.jwt_secret_key,
            algorithm=cfg().auth.jwt_algorithm
        )


def create_oauth2_token(claims: JWTClaims) -> OAuth2Token:
    access_token = claims.to_jwt_string()

    return OAuth2Token(
        access_token=access_token,
        refresh_token="",
        token_type=TokenType.bearer,
        expires_at=claims.exp,
    )


def create_or_update_session(db: DatabaseDep, user_id: uuid.UUID, session_id: uuid.UUID = None,
                             expires_delta=timedelta(days=30)) -> uuid.UUID:
    session = None
    if session_id is not None:
        session = db.scalar(
            select(Session).where(Session.id == session_id)
        )

    if session is not None:
        session.last_used_at = func.now()
    else:
        session = Session(user_id=user_id)
        db.add(session)

    db.flush()

    # update expiry
    session.expires_at = add(session.last_used_at, expires_delta)

    db.commit()

    return session.id


def clear_all_sessions(user: UserDep, db: DatabaseDep):
    db.execute(
        delete(Session)
        .where(Session.user_id == user.id)
    )
    db.commit()


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
    max_age = value.expires_at - utcnow()
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


class AuthErrorCode(PyEnum):
    OTP_REQUIRED = "otp_required"
    USER_DELETED = "user_deleted"
    EMAIL_NOT_VERIFIED = "email_not_verified"
    BAD_TOKEN = "bad_token"
    EXPIRED_TOKEN = "expired_token"


class AuthException(HTTPException):
    def __init__(self, detail: str, err_code: AuthErrorCode):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
        self.err_code = err_code


async def auth_exception_handler(request: Request, exc: AuthException):
    # TODO: return JSON response for non-browser requests (e.g. API clients) instead of redirecting to login page
    # Check if the request is a browser GET request (accepts text/html)
    if request.method.upper() != "GET" or "text/html" not in request.headers.get("accept", ""):
        return await fastapi_http_exception_handler(request, exc)

    match exc.err_code:
        case AuthErrorCode.OTP_REQUIRED:
            return RedirectResponse(url="/login/2fa")
        case AuthErrorCode.USER_DELETED:
            return RedirectResponse(url="/user-deleted")
        case AuthErrorCode.EMAIL_NOT_VERIFIED:
            return RedirectResponse(url="/login/verify-email")
        case _:
            return RedirectResponse(url="/login")


def token(request: Request):
    token = (
            request.cookies.get("sudo_token")
            or request.cookies.get("access_token")
            or request.headers.get("Authorization")
    )
    if token is None:
        return token

    return token.removeprefix("Bearer ").removeprefix("bearer ")


def jwt_claims(token: Annotated[str, Depends(optional_dep(token))]):
    if not token:
        raise AuthException(detail="Invalid token", err_code=AuthErrorCode.BAD_TOKEN)

    token = token.removeprefix("Bearer ").strip()

    return JWTClaims.from_jwt_string(token)


def _raw_user(jwt_claims: Annotated[JWTClaims, Depends(optional_dep(jwt_claims))], db: DatabaseDep):
    user = db.scalar(select(User)
                     .where(User.id == jwt_claims.sub)
                     .where(User.deleted_at.is_(None))
                     )
    if user is None:
        raise AuthException(detail="User not found", err_code=AuthErrorCode.USER_DELETED)

    return user


def active_user(raw_user: Annotated[User, Depends(optional_dep(_raw_user))],
                jwt_claims: Annotated[JWTClaims, Depends(optional_dep(jwt_claims))],
                db: DatabaseDep):
    if jwt_claims is None or raw_user is None:
        raise AuthException(detail="Invalid token", err_code=AuthErrorCode.BAD_TOKEN)

    session = db.scalar(
        select(Session)
        .where(Session.id == jwt_claims.jti,
               Session.user_id == raw_user.id)
    )

    if jwt_claims.requires_otp:
        raise AuthException(detail="OTP verification required",
                            err_code=AuthErrorCode.OTP_REQUIRED)

    if raw_user.deleted_at is not None:
        raise AuthException(detail="User account has been deleted", err_code=AuthErrorCode.USER_DELETED)

    if not raw_user.email_verified:
        raise AuthException(detail="Email not verified", err_code=AuthErrorCode.EMAIL_NOT_VERIFIED)

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    create_or_update_session(db=db, user_id=raw_user.id, session_id=session.id, expires_delta=timedelta(days=30))

    return raw_user


UserDep = Annotated[User, Depends(active_user)]
OptionalUserDep = Annotated[User, Depends(optional_dep(active_user))]


def session(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DatabaseDep):
    session = db.scalar(
        select(Session)
        .where(Session.id == jwt_claims.jti, Session.user_id == jwt_claims.sub)
    )

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    return session


def sudo_token(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DatabaseDep):
    session = db.scalar(
        select(Session)
        .where(Session.id == jwt_claims.jti, Session.user_id == jwt_claims.sub)
    )

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    if not jwt_claims.sudo:
        raise AuthException(detail="Sudo token required", err_code=AuthErrorCode.BAD_TOKEN)

    return jwt_claims


SessionDep = Annotated[Session, Depends(session)]
JWTDep = Annotated[JWTClaims, Depends(jwt_claims)]
