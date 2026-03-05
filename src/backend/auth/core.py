from datetime import datetime, timezone, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, Response
from pydantic import BaseModel
from sqlalchemy import delete, update

from model.base import DatabaseDep
from model.identity import User, Session
from .dependencies import active_user, get_session, sudo_token, JWTClaims
from .helpers import create_oauth2_token, set_token_cookie

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def create_user(db: DatabaseDep, create_user: CreateUserRequest):
    create_user_model = User(
        username=create_user.username,
        primary_email=create_user.primary_email,
        email_verified=True,  # TODO: add email verification flow
        name=create_user.name,
        data={},
        roles=[],
    )
    db.add(create_user_model)

    db.flush()  # get the id before commit

    # TODO: handle exceptions for duplicate usernames/emails
    # TODO: handle different identity providers

    db.commit()


@router.post("/logout")
async def logout(db: DatabaseDep, session: Annotated[Session, Depends(get_session)] = None):
    if session:
        db.execute(
            delete(Session).where(Session.id == session.id)
        )
        db.commit()


class SudoRequest(BaseModel):
    passkey: str = None
    password: str = None
    otp: str = None


@router.post("/sudo")
async def sudo(
        response: Response,
        login_credentials: SudoRequest,
        user: Annotated[User, Depends(active_user)],
        session: Annotated[Session, Depends(get_session)],
        db: DatabaseDep):
    # TODO: implement different sudo methods (password, otp, passkey)

    # create a short-lived sudo token (does not create a new DB session)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
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
        session: Annotated[Session, Depends(get_session)],
        db: DatabaseDep,
        response: Response
):
    """Refresh the current session token by updating its expiration and returning a new token with the same session ID."""
    new_expiration = datetime.now(timezone.utc) + timedelta(days=30)

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
