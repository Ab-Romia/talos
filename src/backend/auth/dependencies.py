import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Annotated

from fastapi import HTTPException, Depends, Request, status
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from starlette.middleware.base import BaseHTTPMiddleware

from config import config
from model.base import DatabaseDep
from model.identity import User, Session, TokenType

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


oauth2_bearer = OAuth2()


class SessionCookieToHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if ("Authorization" in request.headers
                or "access_token" not in request.cookies
                and "sudo_token" not in request.cookies):
            return await call_next(request)

        token = request.cookies.get("sudo_token") \
                or request.cookies.get("access_token")

        headers = request.headers.mutablecopy()
        headers.append("Authorization", f"Bearer {token}")
        request.scope["headers"] = headers.raw

        return await call_next(request)


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


class JWTClaims(BaseModel):
    sub: uuid.UUID
    jti: uuid.UUID = Field(default_factory=uuid.uuid4)
    exp: datetime
    requires_otp: bool = False
    sudo: bool = False

    @classmethod
    def from_jwt_string(cls, claims_str: str):
        from jose import JWTError, ExpiredSignatureError, jwt
        # TODO: get algorithm from header
        try:
            claims_dict = jwt.decode(
                token=claims_str,
                key=config().auth.jwt_secret_key,
                algorithms=config().auth.jwt_algorithm,
                options=config().auth.jwt_options or None
            )
            return cls.model_validate(claims_dict)
        except ExpiredSignatureError as e:
            raise AuthException(detail="Token expired", err_code=AuthErrorCode.EXPIRED_TOKEN) from e
        except JWTError as e:
            raise AuthException(detail="Invalid token", err_code=AuthErrorCode.BAD_TOKEN) from e

    def to_jwt_string(self):
        from jose import jwt
        return jwt.encode(
            claims=self.model_dump(mode="json"),
            key=config().auth.jwt_secret_key,
            algorithm=config().auth.jwt_algorithm
        )


class OAuth2Token(BaseModel):
    # name: str = Field(..., max_length=40)
    token_type: TokenType
    access_token: str = Field(..., max_length=512)
    refresh_token: str = Field(..., max_length=512)
    requires_otp: bool = False
    expires_at: datetime


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


def jwt_claims(token: Annotated[str, Depends(oauth2_bearer)]):
    return JWTClaims.from_jwt_string(token)


def _raw_user(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DatabaseDep):
    user = db.scalar(select(User).where(User.id == jwt_claims.sub))
    if user is None:
        raise AuthException(detail="User not found", err_code=AuthErrorCode.USER_DELETED)

    return user


def active_user(user: Annotated[User, Depends(_raw_user)],
                jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)],
                db: DatabaseDep):
    session = db.scalar(
        select(Session)
        .where(Session.id == jwt_claims.jti, Session.user_id == user.id)
    )

    if jwt_claims.requires_otp:
        raise AuthException(detail="OTP verification required", err_code=AuthErrorCode.OTP_REQUIRED)

    if user.deleted_at is not None:
        raise AuthException(detail="User account has been deleted", err_code=AuthErrorCode.USER_DELETED)

    if not user.email_verified:
        raise AuthException(detail="Email not verified", err_code=AuthErrorCode.EMAIL_NOT_VERIFIED)

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    db.execute(
        update(Session)
        .where(Session.id == session.id)
        .values(last_active_at=datetime.now(timezone.utc))
    )

    db.commit()

    return user


def get_session(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DatabaseDep):
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


SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(active_user)]
