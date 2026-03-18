from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, Response
from pydantic import BaseModel
from sqlalchemy import delete

from model import DatabaseDep
from model.identity import User, Session
from .helpers import create_oauth2_token, set_token_cookie, create_and_save_token, JWTClaims, session, sudo_token, \
    SessionDep, UserDep
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
        user: UserDep,
        session: Annotated[Session, Depends(session)],
        db: DatabaseDep):
    # TODO: implement different sudo methods (password, otp, passkey)

    # create a short-lived sudo token (does not create a new DB session)
    claims = JWTClaims(
        sub=user.id,
        jti=session.id,
        exp=timedelta(minutes=15),
        sudo=True,
    )
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
