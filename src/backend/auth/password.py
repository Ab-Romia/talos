import uuid
from datetime import datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status, APIRouter, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_, update

from model import DatabaseDep
from model.identity import User, IdentityProvider, Issuer
from .helpers import create_and_save_token, clear_all_sessions, sudo_token, UserDep

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
def password_authenticate(response: Response, db: DatabaseDep, form_data: OAuth2PasswordRequestForm = Depends()):
    HTTP_EXCEPTION = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                   detail="Incorrect username or password.")

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
        raise HTTP_EXCEPTION

    user, data = row

    assert data is not None and "hash" in data, "Password identity provider should always have a data field"
    pass_hash = data["hash"]

    if (user.email_verified is False
            or user.deleted_at is not None
            or not verify_password(password, pass_hash)):
        raise HTTP_EXCEPTION

    # TODO: generalize to multiple 2fa methods
    requires_otp = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id)
        .where(IdentityProvider.issuer == Issuer.totp)
    )

    if requires_otp:
        # create a short-lived token requiring OTP (does not create DB session yet)
        # TODO: use starlette session
        return create_and_save_token(response=response,
                                     db=db, user_id=user.id,
                                     duration=timedelta(minutes=5),
                                     requires_otp=True,
                                     cookie_key="access_token",
                                     session_cookie=True,
                                     save_to_db=False)
    else:
        # create and save a normal session token and set cookie
        return create_and_save_token(response=response, db=db, user_id=user.id)


@router.put("/change", dependencies=[Depends(sudo_token)])
def change_password(new_password: str, response: Response, user: UserDep, db: DatabaseDep):
    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.password)
        .values(data={"hash": hash_password(new_password)})
    )

    db.commit()

    clear_all_sessions(user, db)

    return create_and_save_token(response=response, db=db, user_id=user.id)


def create_password_identity(user_id: uuid.UUID, password: str, db: DatabaseDep):
    identity = IdentityProvider(
        user_id=user_id,
        issuer=Issuer.password,
        data={"hash": hash_password(password)},
    )

    db.add(identity)
    db.flush()

    return identity
