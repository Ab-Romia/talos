"""
Authentication-related endpoints.
"""
from datetime import datetime, timezone, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from starlette.responses import RedirectResponse, HTMLResponse

from backend.auth.utils import jwt
from backend.auth.utils.helpers import sudo, SessionDep, UserDep, validate_signup_inputs
from backend.auth.utils.jwt import BaseJWTClaims
from backend.auth.utils.session import revoke, get_by_uid, revoke_by_uid, NewSessionDep
from config import cfg
from model import DatabaseDep
from model.identity import User, Session
from .password import create_password_identity, hash_password
from ..email.send import send_verification_email

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str


class UserVerificationClaims(BaseJWTClaims, CreateUserRequest):
    pass


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
def create_user(
        create_user: Annotated[CreateUserRequest, Form()],
        db: DatabaseDep
):
    # TODO:
    #  - Rate limit
    #  - Captcha

    validate_signup_inputs(create_user, db)

    claims = UserVerificationClaims(
        exp=datetime.now(timezone.utc) + timedelta(hours=1),
        password=hash_password(create_user.password),
        **create_user.model_dump()
    )
    token = jwt.create_token(claims)

    send_verification_email(create_user.email, token)

    return {"message": "Please check your email to verify your account."}


@router.get("/complete_signup")
def complete_signup(token: str):
    return HTMLResponse(f"TODO: Implement complete signup page. Token: {token}")


@router.post("/complete_signup")
def verify_email(
        token: Annotated[str, Form()],
        user_info: dict(str, str),
        session: NewSessionDep,
        db: DatabaseDep):
    # TODO:
    #  - move
    #  - Exception handling for:
    #  - Rate limit
    claims = jwt.verify_token(token, return_model=UserVerificationClaims)

    # TODO: Continue with signup process (more user info, 2FA setup, etc)

    try:
        user = User(
            username=claims.username,
            primary_email=claims.email,
            data=user_info,
        )
        db.add(user)
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Username or email already exists")

    create_password_identity(user_id=user.id,
                             password_hash=claims.password,
                             db=db)

    session.sub = user.id
    db.commit()

    return RedirectResponse(url="/complete_signup",
                            status_code=status.HTTP_302_FOUND)


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
    get_by_uid(user.id, db)


@router.delete("/sessions", dependencies=[Depends(sudo)])
async def revoke_current_token(user: UserDep, db: DatabaseDep):
    revoke_by_uid(user.id, db, except_id=None)


@router.get("/sessions/{session_id}", dependencies=[Depends(sudo)])
async def get_session_by_id(session_id: UUID, user: UserDep, db: DatabaseDep):
    sessions = get_by_uid(user.id, db)

    for session in sessions:
        if session.id == session_id:
            return session

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found")


@router.delete("/session/{session_id}", dependencies=[Depends(sudo)])
async def revoke_token(session_id: UUID, db: DatabaseDep):
    revoke(session_id, db)
