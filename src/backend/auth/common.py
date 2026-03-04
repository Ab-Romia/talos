import uuid
from datetime import timedelta, datetime, timezone
from enum import Enum as PyEnum
from typing import Annotated
from uuid import UUID
from xmlrpc.client import DateTime

from fastapi import HTTPException, Depends, Request, status, Response
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2
from jose import jwt, JWTError, ExpiredSignatureError
from pydantic import BaseModel
from sqlalchemy.orm import Mapped
from starlette.middleware.base import BaseHTTPMiddleware

from config import config
from model.base import DepDB
from model.identity import User, OAuth2Token, TokenType, Session

# TODO:
#  ✅ cookies,
#  refresh tokens,
#  ✅ sessions,
#  ✅ identity providers other than password
#  password reset,
#  forgot password,
#  email verification,
#  logout,
#  multiple account support
#  session management
#   - view active sessions
#   - revoke sessions
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
    sub: UUID
    jti: UUID
    exp: datetime
    requires_otp: bool = False
    sudo: bool = False


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


def _raw_user(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DepDB):
    user = db.query(User).filter(User.id == jwt_claims.sub).one_or_none()
    if user is None:
        raise AuthException(detail="User not found", err_code=AuthErrorCode.USER_DELETED)

    return user


def jwt_claims(token: Annotated[str, Depends(oauth2_bearer)]):
    try:
        jwt_claims = decode_token(token)
    except ExpiredSignatureError:
        raise AuthException(detail="Token expired", err_code=AuthErrorCode.EXPIRED_TOKEN)
    except JWTError:
        raise AuthException(detail="Invalid token", err_code=AuthErrorCode.BAD_TOKEN)

    return jwt_claims


def active_user(user: Annotated[User, Depends(_raw_user)],
                jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)],
                db: DepDB):
    query = db.query(Session) \
        .filter(Session.id == jwt_claims.jti, Session.user_id == user.id)
    session = query.one_or_none()

    if jwt_claims.requires_otp:
        raise AuthException(detail="OTP verification required", err_code=AuthErrorCode.OTP_REQUIRED)

    if user.deleted_at is not None:
        raise AuthException(detail="User account has been deleted", err_code=AuthErrorCode.USER_DELETED)

    if not user.email_verified:
        raise AuthException(detail="Email not verified", err_code=AuthErrorCode.EMAIL_NOT_VERIFIED)

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    query.update({Session.last_used_at: datetime.now()})
    db.commit()

    return user


def get_session(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DepDB):
    session = db.get(Session, jwt_claims.jti)

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    return session


def sudo_token(jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)], db: DepDB):
    session = db.get(Session, jwt_claims.jti)

    if session is None:
        raise AuthException(detail="Session expired", err_code=AuthErrorCode.EXPIRED_TOKEN)

    if not jwt_claims.sudo:
        raise AuthException(detail="Sudo token required", err_code=AuthErrorCode.BAD_TOKEN)

    return jwt_claims


DepSession = Annotated[Session, Depends(get_session)]
DepUser = Annotated[User, Depends(active_user)]


def decode_token(token: str):
    # TODO: use authlib.jwt, get algorithm from header
    claims = jwt.decode(token, config().auth.jwt_secret_key)
    claims = JWTClaims.model_validate(claims)

    return claims


def create_token(user_id, exp, jti, requires_otp=False) -> OAuth2Token:
    """Create a JWT token with the given user ID, expiration time, and session ID (jti)."""
    claims = JWTClaims(sub=user_id,
                       exp=exp,
                       jti=jti,
                       requires_otp=requires_otp)

    access_token = jwt.encode(claims.model_dump(mode="json"),
                              config().auth.jwt_secret_key,
                              algorithm=config().auth.jwt_algorithm)
    return OAuth2Token(
        access_token=access_token,
        refresh_token="",
        token_type=TokenType.bearer,
        expires_at=exp,
    )


def create_session(
        user_id: UUID | Mapped[UUID],
        db,
        expires_delta=timedelta(days=30),
        expires_at: DateTime = None,
        session_id: UUID = None,
) -> OAuth2Token:
    # TODO: handle case where token is provided (factory?)
    expires = expires_at or (datetime.now(timezone.utc) + expires_delta)
    session_id = session_id or uuid.uuid4()
    db.add(Session(id=session_id, user_id=user_id))

    return create_token(user_id, exp=expires, jti=session_id)


async def clear_all_sessions(db: DepDB, user: Annotated[User, Depends(active_user)]):
    db.delete(db.query(Session).filter(Session.user_id == user.id))


# TODO: generalize this to handle all cookies
def set_cookie(response: Response, name: str, value: OAuth2Token, session_cookie: bool = False):
    max_age = int(value.expires_at.timestamp() - datetime.now(timezone.utc).timestamp())

    response.set_cookie(
        key=name,
        value=value.access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        expires=value.expires_at if session_cookie else None,
    )
    return value
