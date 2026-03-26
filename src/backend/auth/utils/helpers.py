from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession
from starlette import status
from starlette.requests import Request
from starlette.responses import RedirectResponse

from backend.auth.core import CreateUserRequest
from backend.auth.utils import errors
from backend.auth.utils.session import SessionDep, auth_token, unverified_session, UnverifiedSessionDep
from model import DatabaseDep
from model.identity import User, Session


# TODO:
#  forgot password,
#  backup codes for totp
#  email verification,
#  multiple account support
#  sudo mode (re-auth for sensitive actions)
#  remember me functionality
#  device recognition (e.g. for risk-based authentication)
#  exception handling
#  use starlette middleware session
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


def active_user(session: UnverifiedSessionDep, db: DatabaseDep):
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
        sess = unverified_session(request, token)
        return active_user(next(sess), db)
    except errors.AuthException:
        return None


def sudo(session: SessionDep):
    if session.sudo_exp is None or session.sudo_exp < datetime.now(timezone.utc):
        raise errors.SudoRequired()


UserDep = Annotated[User, Depends(active_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_active_user)]


def validate_signup_inputs(create_user: CreateUserRequest, db: DatabaseSession):
    try:
        with db.begin_nested():
            db.add(User(username=create_user.username, primary_email=create_user.email))
            db.flush()
            db.rollback()
    except IntegrityError as e:
        print(f"IntegrityError during user creation: {e.orig}")
        err = str(e.orig)
        if "email_format" in err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Invalid email format")
        elif "ix_users_username" in err:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Username already exists")
        elif "ix_users_primary_email" in err:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Email already exists")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Invalid input")

    if len(create_user.password) >= 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Password must be at least 12 characters long")
