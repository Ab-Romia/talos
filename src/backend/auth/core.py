from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, Response
from pydantic import BaseModel
from sqlalchemy import delete, update

from model import DatabaseDep
from model.identity import User, Session
from .dependencies import active_user, session, sudo_token, JWTClaims, SessionDep
from .helpers import create_oauth2_token, set_token_cookie, create_and_save_token
from .password import create_password_identity

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


# TODO: exception handling: auto rollback on error
@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def create_user(
        response: Response,
        create_user: Annotated[CreateUserRequest, Form()],
        db: DatabaseDep):
    # TODO:
    #  spam prevention:
    #  - only commit to database on email verify
    #  - ratelimit
    #  - captcha

    user = User(
        username=create_user.username,
        primary_email=create_user.primary_email,
        email_verified=True,  # TODO: add email verification flow
        name=create_user.name,
        data={},
        roles=[],
    )
    db.add(user)

    db.flush()  # get the id before commit

    # TODO: handle exceptions for duplicate usernames/emails
    # TODO: handle different identity providers

    create_password_identity(user_id=user.id, password=create_user.password, db=db)

    db.commit()

    return create_and_save_token(response, db, user_id=user.id, cookie_key="access_token")


@router.post("/logout")
async def logout(response: Response, db: DatabaseDep, session: SessionDep = None):
    if session:
        db.execute(
            delete(Session).where(Session.id == session.id)
        )
        db.commit()

        response.delete_cookie("access_token")
        response.delete_cookie("sudo_token")

        return {"success": True, "message": "Logged out successfully"}
    return {"success": False, "message": "No active session"}


class SudoRequest(BaseModel):
    passkey: str = None
    password: str = None
    otp: str = None


@router.post("/sudo")
async def sudo(
        response: Response,
        # login_credentials: SudoRequest,
        user: Annotated[User, Depends(active_user)],
        session: Annotated[Session, Depends(session)],
        db: DatabaseDep):
    # TODO: implement different sudo methods (password, otp, passkey)

    # create a short-lived sudo token (does not create a new DB session)
    expires = datetime.now() + timedelta(minutes=15)
    claims = JWTClaims(sub=user.id, exp=expires, sudo=True)
    sudo_token = create_oauth2_token(claims)
    set_token_cookie(response, key="sudo_token", value=sudo_token, session_cookie=True)
    return sudo_token


# @auth_router.post("/logout_all")


@router.post("/revoke", dependencies=[Depends(sudo_token)])
async def revoke_token(session_id: Annotated[UUID, Form()],
                       db: DatabaseDep):
    db.execute(
        delete(Session).where(Session.id == session_id)
    )
    db.commit()


@router.post("/refresh")
async def refresh_token(
        user: Annotated[User, Depends(active_user)],
        session: Annotated[Session, Depends(session)],
        db: DatabaseDep,
        response: Response
):
    """Refresh the current session token by updating its expiration and returning a new token with the same session ID."""
    new_expiration = datetime.now() + timedelta(days=30)

    # TODO: modify create_and_save_token to handle refreshing tokens without creating a new session
    # the session is guaranteed to exist by the dependency
    db.execute(
        update(Session)
        .where(Session.id == session.id)
        .values(expires_at=new_expiration)
    )
    db.commit()

    claims = JWTClaims(sub=user.id, jti=session.id, exp=new_expiration)
    token = create_oauth2_token(claims)

    set_token_cookie(response, key="access_token", value=token)
    return token
