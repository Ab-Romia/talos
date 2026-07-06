import os
import uuid
from typing import Annotated

import bcrypt
from fastapi import Depends, APIRouter, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_, update

from config import cfg
from database import DatabaseDep
from utils.email import send_email
from .dependencies import sudo
from .model import User, IdentityProvider, Issuer, Session as DBSession
from .utils import errors, jwt
from .utils.session import revoke_by_uid, SessionDep, NewSessionDep

router = APIRouter()

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_BYTES = 72  # bcrypt hard limit


def validate_password(password: str) -> None:
    """Enforce the password policy uniformly across signup / reset / change."""
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.",
        )
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long.",
        )


@router.post("/")
def password_authenticate(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        db: DatabaseDep,
        session: NewSessionDep,
):
    username = form_data.username
    password = form_data.password
    email = form_data.username

    # TODO: make sure there is no chance that username can be same as email of another user
    row = db.execute(
        select(User, IdentityProvider.data)
        .where(or_(User.username == username, User.primary_email == email))
        .where(IdentityProvider.user_id == User.id,
               IdentityProvider.issuer == Issuer.password)
    ).one_or_none()
    if row is None:
        raise errors.InvalidCredentials()

    user, data = row

    assert data is not None and "hash" in data, "Password identity provider should always have a data field"
    pass_hash = data["hash"]

    if user.signup_complete is False:
        raise errors.IncompleteUserProfile()
    if user.deleted_at is not None:
        raise errors.UserNotFound()
    if not verify_password(password, pass_hash):
        raise errors.InvalidCredentials()

    # TODO: generalize to multiple 2fa methods
    requires_otp = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id)
        .where(IdentityProvider.issuer == Issuer.totp)
    )

    db.merge(DBSession(id=session.jti, user_id=user.id))
    db.commit()

    session.sub = user.id
    if requires_otp:
        session.requires_otp = True


class ForgotPasswordClaims(jwt.BaseJWTClaims):
    requires_totp: bool
    identity_provider_id: uuid.UUID


@router.post("/forgot")
async def forgot_password_request(email: Annotated[str, Form()], db: DatabaseDep):
    identity = db.execute(
        select(IdentityProvider)
        .where(IdentityProvider.issuer == Issuer.password)
        .where(IdentityProvider.user.has(primary_email=email))
    ).scalar_one_or_none()

    if identity is None:
        # Don't reveal whether the email exists or not
        return

    claims = ForgotPasswordClaims(
        sub=identity.user_id,
        identity_provider_id=identity.id,
        requires_totp=db.scalar(
            select(IdentityProvider)
            .where(IdentityProvider.user_id == identity.user_id)
            .where(IdentityProvider.issuer == Issuer.totp)
        ) is not None,
        exp=jwt.now() + cfg().auth.password_reset_token_expiry
    )

    token = jwt.create_token(claims)

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
    reset_url = f"{frontend_origin}/reset-password?token={token}"
    await send_email(
        email,
        "We received a request to reset your Talos password.\n\n"
        "Use the link below to choose a new password:\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email.",
        subject="Reset your Talos password",
    )


@router.put("/reset")
def forgot_password(reset_token: Annotated[str, Form()],
                    reset_password: Annotated[str, Form()],
                    db: DatabaseDep):
    validate_password(reset_password)
    claims = jwt.verify_token(reset_token, return_model=ForgotPasswordClaims)

    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.id == claims.identity_provider_id)
        .values(data={"hash": hash_password(reset_password)})
    )
    db.commit()

    revoke_by_uid(claims.sub, db)


@router.put("/change", dependencies=[Depends(sudo)])
def change_password(
        new_password: Annotated[str, Form()],
        db: DatabaseDep,
        session: SessionDep
):
    validate_password(new_password)
    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.user_id == session.sub,
               IdentityProvider.issuer == Issuer.password)
        .values(data={"hash": hash_password(new_password)})
    )

    db.commit()

    revoke_by_uid(session.sub, db, except_id=session.jti)


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_password_identity(user_id: uuid.UUID, password_hash: str, db: DatabaseDep):
    identity = IdentityProvider(
        user_id=user_id,
        issuer=Issuer.password,
        data={"hash": password_hash},
    )

    db.add(identity)
    db.flush()

    return identity
