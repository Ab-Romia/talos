"""Authentication-related endpoints."""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status, Form, HTTPException, Body
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from sqlalchemy import select, or_

from config import cfg
from database import DatabaseDep
from utils.email import send_email
from utils.email_templates import verification_email
from utils.exceptions import ExceptionMapper
from utils.ratelimit import email_ratelimit
from .dependencies import sudo, UserDep
from .model import User
from .oauth import router as oauth_router
from .password import create_password_identity, hash_password, validate_password
from .password import router as pass_router
from .totp import router as totp_router
from .utils import jwt
from .utils import session as s
from .webauthn import router as webauthn_router
from .avatars import router as avatar_router, avatar_url_for

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(pass_router, prefix="/password")
router.include_router(totp_router, prefix="/totp")
router.include_router(oauth_router, prefix="/oauth")
router.include_router(webauthn_router, prefix="/passkey")
router.include_router(avatar_router)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InitSignupClaims(jwt.BaseJWTClaims):
    email: str


@router.post("/signup",
             status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(email_ratelimit("signup", "5/10minute"))])
async def initiate_signup(email: Annotated[str, Form()], db: DatabaseDep):
    # TODO:
    #  - Captcha

    email = (email or "").strip()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Please enter a valid email address.")

    try:
        with db.begin_nested():
            db.add(User(username='usr-' + uuid.uuid7().hex, primary_email=email))
            db.flush()
            db.rollback()
    except IntegrityError as e:
        ExceptionMapper(
            base_exc=IntegrityError,
            responses={
                "ix_users_primary_email": HTTPException(status_code=status.HTTP_409_CONFLICT,
                                                        detail="An account with this email already exists. Please sign in instead."),
                "email_format": HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                              detail="Invalid email format"),
            },
            default_response=HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                           detail="Invalid email format"),
            mapper=lambda exc: exc.orig.diag.constraint_name
        ).apply(e)

    token = jwt.create_token(InitSignupClaims(
        exp=datetime.now(timezone.utc) + timedelta(hours=1),
        email=email
    ))

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
    verify_url = f"{frontend_origin}/signup/complete?token={token}"
    html, text = verification_email(verify_url)
    await send_email(
        email,
        html,
        subject="Verify your Talos account",
        text=text,
    )

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
    claims = jwt.verify_token(email_token, return_model=InitSignupClaims)

    username = (username or "").strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9-]{3,31}$", username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 4–32 characters, start with a letter, and use only letters, numbers, and hyphens.",
        )
    if name is not None:
        name = name.strip()[:80] or None

    for auth_method in auth_info:
        match auth_method:
            case PasswordAuth(password=password):
                validate_password(password)
            case PasskeyAuth():
                pass  # TODO: implement passkey validation
            case OtpAuth():
                pass  # TODO: implement OTP validation

    try:
        user = User(
            username=username,
            primary_email=claims.email,
            name=name or username,
            signup_complete=True,
            # TODO: rest of info
        )
        db.add(user)
        db.flush()
    except IntegrityError as e:
        db.rollback()
        ExceptionMapper(
            base_exc=IntegrityError,
            responses={
                "ix_users_username": HTTPException(status_code=status.HTTP_409_CONFLICT,
                                                   detail="Username already exists"),
                "username_format": HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                                 detail="Invalid username format"),
                "ix_users_primary_email": HTTPException(status_code=status.HTTP_409_CONFLICT,
                                                        detail="Email already exists"),
                "email_format": HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                              detail="Invalid email format"),
            },
            default_response=HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                           detail="Invalid input"),
            mapper=lambda exc: exc.orig.diag.constraint_name
        ).apply(e)

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


def _serialize_session(row, current_jti) -> dict:
    return {
        "id": str(row.id),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "user_agent": row.user_agent,
        "current": row.id == current_jti,
    }


@router.get("/sessions", dependencies=[Depends(sudo)])
async def get_session(user: UserDep, db: DatabaseDep, session: s.SessionDep):
    rows = s.get_by_uid(user.id, db)
    return [_serialize_session(r, session.jti) for r in rows]


@router.delete("/sessions", dependencies=[Depends(sudo)])
async def revoke_current_token(user: UserDep, db: DatabaseDep):
    s.revoke_by_uid(user.id, db, except_id=None)


@router.get("/sessions/{session_id}", dependencies=[Depends(sudo)])
async def get_session_by_id(session_id: UUID, user: UserDep, db: DatabaseDep, session: s.SessionDep):
    for row in s.get_by_uid(user.id, db):
        if row.id == session_id:
            return _serialize_session(row, session.jti)

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
        "avatar_url": avatar_url_for(user),
    }


@router.delete("/me", dependencies=[Depends(sudo)])
def delete_current_user(user: UserDep, db: DatabaseDep):
    user.deleted_at = datetime.now(timezone.utc)
    s.revoke_by_uid(user.id, db)


@router.get("/users/search")
def search_users(q: str, user: UserDep, db: DatabaseDep):
    """Search users by username or email prefix. Returns up to 10 matches, excluding the caller."""
    q = q.strip()
    if len(q) < 2:
        return []
    pattern = f"{q}%"
    rows = db.scalars(
        select(User)
        .where(User.deleted_at.is_(None), User.signup_complete.is_(True), User.id != user.id)
        .where(or_(User.username.ilike(pattern), User.primary_email.ilike(pattern)))
        .order_by(User.username)
        .limit(10)
    ).all()
    return [
        {"id": str(u.id), "username": u.username, "name": u.name or u.username, "email": u.primary_email,
         "avatar_url": avatar_url_for(u)}
        for u in rows
    ]
