from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse

from model import DatabaseDep
from model.identity import TokenType, User
from . import errors
from .session import SessionDep, session, auth_token, get_current_session


# TODO:
#  ✅ sessions,
#  forgot password,
#  email verification,
#  ✅ logout,
#  multiple account support
#  session management
#   - view active sessions
#  ✅ - revoke sessions
#  ✅* sudo mode (re-auth for sensitive actions)
#  anonymous sessions
#  remember me functionality
#  device recognition (e.g. for risk-based authentication)
#  exception handling
#  use starlette middleware session
#  prevent re-signin, and invalidate prev session on resignin


class OAuth2Token(BaseModel):
    # name: str = Field(..., max_length=40)
    token_type: TokenType
    access_token: str = Field(..., max_length=512)
    refresh_token: str = Field(..., max_length=512)
    expires_at: datetime


async def auth_exception_handler(request: Request, exc: errors.AuthException):
    # TODO: return JSON response for non-browser requests (e.g. API clients) instead of redirecting to login page
    # Check if the request is a browser GET request (accepts text/html)
    if request.method.upper() != "GET" or "text/html" not in request.headers.get("accept", ""):
        return await fastapi_http_exception_handler(request, exc)

    match type(exc):
        case errors.InvalidToken:
            return RedirectResponse(url=request.url_for("login"), status_code=302)

    return await fastapi_http_exception_handler(request, exc)


def _raw_user(session: SessionDep, db: DatabaseDep):
    user = db.scalar(select(User)
                     .where(User.id == session.sub)
                     .where(User.deleted_at.is_(None))
                     )
    if user is None:
        raise errors.UserNotFound()

    return user


def active_user(raw_user: Annotated[User, Depends(_raw_user)], session: SessionDep):
    if session.requires_otp:
        raise errors.OTPRequired()

    if raw_user.deleted_at is not None:
        raise errors.UserNotFound()

    if not raw_user.email_verified:
        raise errors.EmailNotVerified()

    return raw_user


def optional_active_user(request: Request, db: DatabaseDep):
    try:
        token = auth_token(
            authorization=request.headers.get("Authorization"),
            user_session=request.cookies.get("user_session"),
        )
        sess = get_current_session(db, token)
        raw_user = _raw_user(sess, db)

        return active_user(raw_user, sess)
    except errors.AuthException:
        return None


def sudo(session: SessionDep):
    if session.sudo_exp is None or session.sudo_exp < datetime.now(timezone.utc):
        raise errors.SudoRequired()


UserDep = Annotated[User, Depends(active_user)]
OptionalUserDep = Annotated[User, Depends(optional_active_user)]
