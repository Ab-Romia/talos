from datetime import datetime, timezone, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, Response
from pydantic import BaseModel

from backend.auth.common import active_user, create_token, \
    get_session, sudo_token, set_cookie_from_token
from model.base import DepDB
from model.identity import User, Session, OAuth2Token, TokenType

auth_router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


@auth_router.post("/signup", status_code=status.HTTP_201_CREATED)
async def create_user(db: DepDB, create_user: CreateUserRequest):
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


@auth_router.post("/logout")
async def logout(db: DepDB, session: Annotated[Session, Depends(get_session)] = None):
    if session:
        db.query(Session).filter(Session.id == session.id).delete()
        db.commit()


class SudoRequest(BaseModel):
    passkey: str = None
    password: str = None
    otp: str = None


@auth_router.post("/sudo")
async def sudo(
        login_credentials: SudoRequest,
        user: Annotated[User, Depends(active_user)],
        session: Annotated[Session, Depends(get_session)],
        db: DepDB):
    # TODO: implement different sudo methods (password, otp, passkey)

    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    return create_token(user.id, exp=expires, jti=session.id, requires_otp=True)


# @auth_router.post("/logout_all")


@auth_router.post("/revoke", dependencies=[Depends(sudo_token)])
async def revoke_token(session_id: Annotated[UUID, Form()],
                       db: DepDB):
    db.delete(db.query(Session).filter(Session.id == session_id))
    db.commit()


@auth_router.post("/refresh")
async def refresh_token(
        response: Response,
        user: Annotated[User, Depends(active_user)],
        session: Annotated[Session, Depends(get_session)],
        db: DepDB):
    new_expiration = datetime.now(timezone.utc) + timedelta(days=30)
    db.get_one(Session, session.id).expires_at = new_expiration
    db.commit()

    oauth = OAuth2Token(
        access_token=create_token(user.id, exp=new_expiration, jti=session.id),
        refresh_token="",
        token_type=TokenType.bearer,
        expires_at=new_expiration,
    )

    set_cookie_from_token(response, oauth, cookie_name="access_token")
    return oauth
