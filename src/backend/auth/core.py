from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form
from pydantic import BaseModel
from sqlalchemy import delete

from config import cfg
from model import DatabaseDep
from model.identity import User, Session
from .helpers import sudo, SessionDep, UserDep
from .password import create_password_identity
from .session import NewSessionDep, revoke_session_by_id

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def create_user(
        create_user: Annotated[CreateUserRequest, Form()],
        session: NewSessionDep,
        db: DatabaseDep):
    # TODO:
    #  exception handling: auto rollback on error
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

    session.sub(user.id)

    db.commit()


@router.post("/logout")
async def logout(db: DatabaseDep, session: SessionDep):
    db.execute(
        delete(Session)
        .where(Session.id == session.jti)
    )
    db.commit()

    session.delete()

    return {"message": "Logged out successfully"}


class SudoRequest(BaseModel):
    passkey: str = None
    password: str = None
    otp: str = None


@router.post("/sudo")
async def activate_sudo(
        # login_credentials: SudoRequest,
        session: SessionDep,
):
    # TODO: implement different sudo methods (password, otp, passkey)

    session.sudo_exp = datetime.now(timezone.utc) + cfg().auth.sudo_max_age


@router.post("/revoke", dependencies=[Depends(sudo)])
async def revoke_token(session_id: Annotated[UUID, Form()], db: DatabaseDep):
    revoke_session_by_id(session_id, db)
