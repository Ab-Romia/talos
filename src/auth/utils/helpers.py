import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse

from auth.model import User
from auth.utils import errors
from auth.utils.session import SessionDep, auth_token, unverified_session, UnverifiedSessionDep, Session
from model import DatabaseDep


# TODO:
#  backup codes for totp
#  email verification,
#  multiple account support
#  remember me functionality
#  device recognition (e.g. for risk-based authentication)
#  exception handling
#  prevent re-signin, and invalidate prev session on resignin


async def auth_exception_handler(request: Request, exc: errors.AuthException):
    # TODO: return JSON response for non-browser requests (e.g. API clients) instead of redirecting to login page
    # Check if the request is a browser GET request (accepts text/html)
    if request.method.upper() != "GET" or "text/html" not in request.headers.get("accept", ""):
        return await fastapi_http_exception_handler(request, exc)

    match type(exc):
        case errors.InvalidCredentials:
            return RedirectResponse(url=request.url_for("login"), status_code=302)

    return await fastapi_http_exception_handler(request, exc)


def active_user(session: UnverifiedSessionDep, db: DatabaseDep) -> User:
    user = db.scalar(select(User)
                     .join(Session, User.id == Session.user_id)
                     .where(User.id == session.sub)
                     .where(Session.id == session.jti)
                     .where(User.deleted_at.is_(None)))
    if user is None:
        raise errors.UserNotFound()

    if session.requires_otp:
        raise errors.OTPRequired()

    if user.deleted_at is not None:
        raise errors.UserNotFound()

    if not user.signup_complete:
        raise errors.IncompleteUserProfile()

    return user


def optional_active_user(request: Request, db: DatabaseDep):
    try:
        token = auth_token(
            authorization=request.headers.get("Authorization"),
            user_session=request.cookies.get("user_session"),
        )
        sess = unverified_session(token, request)
        return active_user(next(sess), db)
    except errors.AuthException:
        return None


def sudo(session: SessionDep):
    """Dependency to require sudo mode for sensitive actions. Sudo mode is activated by re-authenticating the user and is valid for a short period of time."""
    if session.sudo_exp is None or session.sudo_exp < datetime.now(timezone.utc):
        raise errors.SudoRequired()


def user_id(session: SessionDep):
    """Dependency to get the user ID from the session. This can be used for actions that require authentication but not necessarily the full user object."""
    return session.sub


UserDep = Annotated[User, Depends(active_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_active_user)]
UserIdDep = Annotated[uuid.UUID, Depends(user_id)]
