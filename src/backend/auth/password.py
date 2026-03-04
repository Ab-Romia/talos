from datetime import datetime, timezone, timedelta
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status, APIRouter, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_, update

from model.base import DepDB
from model.identity import User, IdentityProvider, Issuer
from .common import create_session, sudo_token, clear_all_sessions, active_user, create_token, \
    set_cookie

router = APIRouter()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


@router.post("/")
def password_authenticate(response: Response, db: DepDB, form_data: OAuth2PasswordRequestForm = Depends()):
    HTTP_EXCEPTION = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                   detail="Incorrect username or password.")

    username = form_data.username
    password = form_data.password
    email = form_data.username

    # TODO: make sure there is no chance that username can be same as email of another user
    row = db.execute(
        select(User, IdentityProvider.secret)
        .where(or_(User.username == username, User.primary_email == email))
        .where(IdentityProvider.user_id == User.id,
               IdentityProvider.issuer == Issuer.password)
    ).one_or_none()
    if row is None:
        raise HTTP_EXCEPTION

    user, secret = row

    assert secret is not None, "Password identity provider should always have a secret"

    if (user.email_verified is False
            or user.deleted_at is not None
            or not verify_password(password, secret)):
        raise HTTP_EXCEPTION

    # TODO: generalize to multiple 2fa methods
    requires_otp = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id)
        .where(IdentityProvider.issuer == Issuer.totp)
    )

    if requires_otp:
        exp = datetime.now(timezone.utc) + timedelta(minutes=5)
        return set_cookie(response, name="access_token", value=create_token(
            user_id=user.id,
            requires_otp=True,
            exp=exp,
            jti=None,
        ), session_cookie=True)
    else:
        return set_cookie(response, name="access_token", value=create_session(user.id, db=db))


@router.put("/change", dependencies=[Depends(sudo_token)])
def change_password(
        response: Response,
        user: Annotated[User, Depends(active_user)],
        db: DepDB,
        new_password: str,
):
    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.password)
        .values(secret=hash_password(new_password),
                verified_at=datetime.now())
    )

    db.commit()

    clear_all_sessions(user, db)

    token = create_session(user_id=user.id, db=db)
    set_cookie(response, name="access_token", value=token)

    return token
