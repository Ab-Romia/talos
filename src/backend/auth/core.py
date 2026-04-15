from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form
from langgraph_sdk.auth.exceptions import HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from config import cfg
from model import DatabaseDep
from model.identity import User, Session
from backend.auth.utils.helpers import sudo, SessionDep, UserDep
from .password import create_password_identity
from backend.auth.utils.session import UnverifiedSessionDep, revoke_session_by_id, get_sessions_by_uid, revoke_all_sessions

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def create_user(
        create_user: Annotated[CreateUserRequest, Form()],
        session: UnverifiedSessionDep,
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

    try:
        db.flush()  # get the id before commit
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )

    create_password_identity(user_id=user.id, password=create_user.password, db=db)

    # Create DB session record so active_user can find it
    db_session = Session(id=session.jti, user_id=user.id)
    db.add(db_session)

    session.sub = user.id

    db.commit()


@router.post("/logout")
async def logout(db: DatabaseDep, session: SessionDep):
    db.execute(
        delete(Session)
        .where(Session.id == session.jti)
    )
    db.commit()

    session.clear()

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


@router.get("/sessions", dependencies=[Depends(sudo)])
async def get_session(user: UserDep, db: DatabaseDep):
    get_sessions_by_uid(user.id, db)


@router.delete("/sessions", dependencies=[Depends(sudo)])
async def revoke_current_token(user: UserDep, db: DatabaseDep):
    revoke_all_sessions(db, user.id, except_id=None)


@router.get("/sessions/{session_id}", dependencies=[Depends(sudo)])
async def get_session_by_id(session_id: UUID, user: UserDep, db: DatabaseDep):
    sessions = get_sessions_by_uid(user.id, db)

    for session in sessions:
        if session.id == session_id:
            return session

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found")


@router.delete("/session/{session_id}", dependencies=[Depends(sudo)])
async def revoke_token(session_id: UUID, db: DatabaseDep):
    revoke_session_by_id(session_id, db)


@router.get("/me")
def get_current_user(user: UserDep):
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name,
        "email": user.primary_email,
    }
