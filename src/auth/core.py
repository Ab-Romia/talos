"""Authentication-related endpoints."""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, HTTPException, Body
from fastapi.responses import RedirectResponse
from psycopg import errors as pg_errors
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from config import cfg
from model import DatabaseDep
from utils.email import send_email
from utils.ratelimit import email_ratelimit
from .model import User
from .password import create_password_identity, hash_password
from .utils import jwt
from .utils import session as s
from .utils.helpers import sudo, UserDep

router = APIRouter()


class InitSignupClaims(jwt.BaseJWTClaims):
    email: str


@router.post("/signup",
             status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(email_ratelimit("signup", "1/2minute"))])
async def initiate_signup(email: Annotated[str, Form()], db: DatabaseDep):
    # TODO:
    #  - Captcha

    try:
        with db.begin_nested():
            db.add(User(username='usr-' + uuid.uuid7().hex,
                        primary_email=email))
            db.flush()
            db.rollback()
    except IntegrityError as e:
        if "email_format" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")
        elif "ix_users_primary_email" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    token = jwt.create_token(InitSignupClaims(
        exp=datetime.now(timezone.utc) + timedelta(hours=1),
        email=email
    ))

    await send_email(email, f"http://localhost:8000/signup/complete?token={token}")

    return {"message": "Please check your email to verify your account."}


class PasswordAuth(BaseModel):
    auth_type: Literal["password"] = "password"
    password: str


class PasskeyAuth(BaseModel):
    auth_type: Literal["passkey"] = "passkey"
    # TODO: Add specific passkey fields if needed
    passkey: str


class OtpAuth(BaseModel):
    auth_type: Literal["otp"] = "otp"
    otp: str


AuthInfo = Annotated[PasswordAuth | PasskeyAuth | OtpAuth, Field(discriminator="auth_type")]


@router.post("/signup/complete", responses={
    302: {"description": "Redirect to complete signup"},
    401: {"description": "Invalid or expired token"},
})
def complete_signup(
        email_token: Annotated[str, Body()],
        username: Annotated[str, Body()],
        auth_info: Annotated[list[AuthInfo], Body()],
        session: s.NewSessionDep,
        db: DatabaseDep,
        name: Annotated[str | None, Body()] = None,
):
    # TODO:
    #  - Rate limit
    claims = jwt.verify_token(email_token, return_model=InitSignupClaims)

    for auth_method in auth_info:
        match auth_method:
            case PasswordAuth(password=password):
                if len(password) < 12:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                        detail="Password must be at least 8 characters long")
            case PasskeyAuth():
                pass  # TODO: implement passkey validation
            case OtpAuth():
                pass  # TODO: implement OTP validation

    try:
        user = User(
            username=username,
            primary_email=claims.email,
            name=name or username,
            # TODO: rest of info
        )
        db.add(user)
        db.flush()
    except IntegrityError as e:
        db.rollback()
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
                                detail=f"Invalid input: {err}")

    for auth_method in auth_info:
        match auth_method:
            case PasswordAuth(password=password):
                _ = create_password_identity(user.id, hash_password(password), db)
            case PasskeyAuth():
                pass  # TODO: implement passkey signup
            case OtpAuth():
                pass  # TODO: implement OTP signup

    session.sub = user.id
    db.commit()

    return RedirectResponse(url="/complete_signup",
                            status_code=status.HTTP_302_FOUND)


@router.post("/logout")
async def logout(db: DatabaseDep, session: s.SessionDep):
    s.revoke(session.jti, db)

    session.clear()

    return {"message": "Logged out successfully"}


class SudoRequest(BaseModel):
    auth_info: AuthInfo


@router.post("/sudo")
async def activate_sudo(session: s.SessionDep,
                        login_credentials: Annotated[SudoRequest | None, Body()]):
    # TODO: implement different sudo methods (password, otp, passkey)

    session.sudo_exp = datetime.now(timezone.utc) + cfg().auth.sudo_max_age


@router.get("/sessions", dependencies=[Depends(sudo)])
async def get_session(user: UserDep, db: DatabaseDep):
    s.get_by_uid(user.id, db)


@router.delete("/sessions", dependencies=[Depends(sudo)])
async def revoke_current_token(user: UserDep, db: DatabaseDep):
    s.revoke_by_uid(user.id, db, except_id=None)


@router.get("/sessions/{session_id}", dependencies=[Depends(sudo)])
async def get_session_by_id(session_id: UUID, user: UserDep, db: DatabaseDep):
    sessions = s.get_by_uid(user.id, db)

    for session in sessions:
        if session.id == session_id:
            return session

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                        detail="Session not found")


@router.delete("/session/{session_id}", dependencies=[Depends(sudo)])
async def revoke_token(session_id: UUID, db: DatabaseDep):
    s.revoke(session_id, db)


@router.get("/me")
def get_current_user(user: UserDep):
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name,
        "email": user.primary_email,
    }


@router.delete("/me", dependencies=[Depends(sudo)])
def delete_current_user(user: UserDep, db: DatabaseDep):
    user.deleted_at = datetime.now(timezone.utc)
    s.revoke_by_uid(user.id, db)
